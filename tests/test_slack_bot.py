from unittest.mock import MagicMock

from slack_bot.app import AgentSessions, extract_reply, strip_mention


def test_strip_mention_removes_leading_mention():
    assert strip_mention("<@U123ABC> what's up in toto?") == "what's up in toto?"


def test_strip_mention_keeps_text_without_mention():
    assert strip_mention("what's up in toto?") == "what's up in toto?"


def test_strip_mention_returns_empty_for_bare_mention():
    assert strip_mention("<@U123ABC>") == ""


def test_extract_reply_concatenates_text_parts():
    events = [
        {"content": {"parts": [{"text": "Probable cause: OOMKilled."}]}},
        {"content": {"parts": [{"text": "See postmortem below."}]}},
    ]

    assert extract_reply(events) == "Probable cause: OOMKilled.\nSee postmortem below."


def test_extract_reply_skips_tool_call_parts_without_text():
    events = [
        {"content": {"parts": [{"function_call": {"name": "get_k8s_events"}}]}},
        {"content": {"parts": [{"text": "Root cause identified."}]}},
    ]

    assert extract_reply(events) == "Root cause identified."


def test_extract_reply_returns_placeholder_when_no_text():
    assert extract_reply([{"content": {"parts": []}}]) == "(the agent returned no text response)"


def test_agent_sessions_creates_session_once_per_thread():
    engine = MagicMock()
    engine.create_session.return_value = {"id": "session-1"}
    sessions = AgentSessions(engine)

    first = sessions.get_or_create("C1:1700000000.0", "U123")
    second = sessions.get_or_create("C1:1700000000.0", "U123")

    assert first == second == "session-1"
    engine.create_session.assert_called_once_with(user_id="U123")


def test_agent_sessions_creates_separate_sessions_per_thread():
    engine = MagicMock()
    engine.create_session.side_effect = [{"id": "session-1"}, {"id": "session-2"}]
    sessions = AgentSessions(engine)

    first = sessions.get_or_create("C1:1700000000.0", "U123")
    second = sessions.get_or_create("C1:1700000001.0", "U123")

    assert (first, second) == ("session-1", "session-2")
    assert engine.create_session.call_count == 2
