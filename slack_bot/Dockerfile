# Minimal image for the Slack bot only (not sre_agent/) — keeps the Cloud Run
# container small so cold starts (and therefore billed CPU time) stay short.
# Build context is this directory (see scripts/deploy-slack-bot-cloud-run.sh,
# which passes --source=slack_bot to `gcloud run deploy`).
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./slack_bot

ENV PYTHONUNBUFFERED=1

# --timeout must cover the slowest agent round trip: Slack's own 3s ack
# deadline doesn't apply here (see app.py), but gunicorn's worker timeout
# does. Match Cloud Run's own request timeout (see deploy script).
CMD exec gunicorn --bind 0.0.0.0:${PORT:-8080} --workers 1 --threads 8 --timeout 300 slack_bot.app:flask_app
