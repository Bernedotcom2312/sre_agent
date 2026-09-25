"""Slack front end for the SRE Agent.

Runs as a small Flask/WSGI HTTP service that receives Slack's Events API
callbacks (app_mention), forwards the message to the agent already deployed
on Vertex AI Agent Engine, and posts the reply back in the same thread. The
bot never talks to GCP/GKE directly — it only relays natural-language
messages to the agent, whose own tools stay read-only (see CLAUDE.md).

Designed to run on Cloud Run with min-instances=0: no traffic means no
running container, so cost stays near zero between mentions (see
scripts/deploy-slack-bot-cloud-run.sh). Slack requires an HTTP ack within 3
seconds; Bolt handles that itself for Events API callbacks (it acks
immediately and runs the listener in a background thread), so
`handle_mention` only needs to ignore Slack's retried deliveries (see below)
rather than race that deadline itself.

Run locally with: `uv run --group slack python -m slack_bot.app`
(needs a public URL, e.g. via ngrok, for Slack to reach it).
"""

import logging
import os
import re
import threading

import vertexai
from dotenv import load_dotenv
from flask import Flask
from flask import request as flask_request
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler
from vertexai import agent_engines

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_MENTION_RE = re.compile(r"<@[^>]+>\s*")


def strip_mention(text: str) -> str:
    """Removes the leading `@bot-name` mention Slack includes in the event text."""
    return _MENTION_RE.sub("", text, count=1).strip()


def extract_reply(events: list[dict]) -> str:
    """Concatenates the model's text parts across the agent's streamed events.

    Tool-call/tool-result parts don't carry a `text` key and are skipped, so
    only the agent's final natural-language answer is posted to Slack.
    """
    chunks = [
        part["text"]
        for event in events
        for part in event.get("content", {}).get("parts", [])
        if part.get("text")
    ]
    return "\n".join(chunks) or "(the agent returned no text response)"


class AgentSessions:
    """Maps a Slack thread to its Agent Engine session, so a thread keeps its
    own conversation context (the agent remembers earlier turns in it).

    The mapping lives in this process's memory, which bounds how the service
    may be deployed: it is only correct on a single instance (hence
    `--max-instances=1` in scripts/deploy-slack-bot-cloud-run.sh), since a
    second instance would not know the threads the first one has seen and
    would restart their conversations from scratch, at random. Scaling to
    zero between mentions drops the mapping too — a thread mentioned again
    after an idle period starts a fresh session. Acceptable for a POC;
    surviving a restart or more than one instance means moving this to a
    shared store (Firestore, Redis).
    """

    def __init__(self, engine):
        self._engine = engine
        self._session_ids: dict[str, str] = {}
        # Bolt dispatches each event in its own thread, so two mentions posted
        # in the same Slack thread can reach get_or_create concurrently. Without
        # the lock both miss the cache and create a session, and the second one
        # overwrites the first — losing the context of the turn in flight.
        self._lock = threading.Lock()

    def get_or_create(self, thread_key: str, user_id: str) -> str:
        with self._lock:
            session_id = self._session_ids.get(thread_key)
            if session_id is None:
                session = self._engine.create_session(user_id=user_id)
                session_id = session["id"]
                self._session_ids[thread_key] = session_id
            return session_id


def build_bolt_app() -> App:
    project = os.environ["GOOGLE_CLOUD_PROJECT"]
    # Deliberately not GOOGLE_CLOUD_LOCATION: that one picks the Gemini model
    # endpoint (e.g. "global") and can differ from the region the agent was
    # actually deployed to via `adk deploy agent_engine --region=...`.
    location = os.environ["AGENT_ENGINE_LOCATION"]
    resource_name = os.environ["AGENT_ENGINE_RESOURCE_NAME"]

    vertexai.init(project=project, location=location)
    engine = agent_engines.get(resource_name)
    sessions = AgentSessions(engine)

    app = App(
        token=os.environ["SLACK_BOT_TOKEN"],
        signing_secret=os.environ["SLACK_SIGNING_SECRET"],
    )

    @app.event("app_mention")
    def handle_mention(event, say, request):
        # Bolt auto-acks Events API requests immediately and runs this
        # listener in a background thread afterwards (outside the original
        # Flask request context — hence reading headers off the Bolt
        # `request` here, not Flask's global `request` proxy, which would
        # raise "working outside of request context" in that thread). Since
        # the ack already happened before our (possibly slow) agent round
        # trip even starts, Slack has nothing to time out on — the only
        # thing left to guard against is Slack retrying the delivery for an
        # unrelated reason and us answering the same mention twice.
        if request.headers.get("x-slack-retry-num"):
            logger.info("Ignoring Slack retry for event %s", event.get("event_ts"))
            return

        channel = event["channel"]
        thread_ts = event.get("thread_ts") or event["ts"]
        thread_key = f"{channel}:{thread_ts}"
        user_id = event["user"]
        text = strip_mention(event["text"])

        if not text:
            say(
                text="Ask me something, e.g. `@SRE Agent what's going on in namespace toto?`",
                thread_ts=thread_ts,
            )
            return

        try:
            session_id = sessions.get_or_create(thread_key, user_id)
            events = list(engine.stream_query(user_id=user_id, session_id=session_id, message=text))
            reply = extract_reply(events)
        except Exception:
            logger.exception("Agent Engine query failed for thread %s", thread_key)
            reply = "Sorry, I hit an error querying the agent. Check the bot logs."

        say(text=reply, thread_ts=thread_ts)

    return app


flask_app = Flask(__name__)

_bolt_app: App | None = None
_bolt_handler: SlackRequestHandler | None = None


def get_bolt_handler() -> SlackRequestHandler:
    """Builds the Bolt app (and its Agent Engine client) lazily, on first
    request rather than at import time, so importing this module (e.g. from
    tests) never requires GCP/Slack credentials to be configured."""
    global _bolt_app, _bolt_handler
    if _bolt_handler is None:
        _bolt_app = build_bolt_app()
        _bolt_handler = SlackRequestHandler(_bolt_app)
    return _bolt_handler


@flask_app.route("/slack/events", methods=["POST"])
def slack_events():
    return get_bolt_handler().handle(flask_request)


@flask_app.route("/", methods=["GET"])
def health():
    return "ok", 200


if __name__ == "__main__":
    flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
