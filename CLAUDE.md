# SRE Agent — Incident diagnosis copilot

## Goal

Reduce MTTR (a DORA metric) by giving an agent the ability to correlate
alerts, logs, and GKE events, then propose a diagnosis and a draft
postmortem.

## Stack

- **Agent framework**: Google ADK (Agent Development Kit), Python.
- **Data sources**: Cloud Monitoring (alerts, metrics), Cloud Logging,
  Kubernetes events (`kubectl get events` or exported to Cloud Logging).
- **Deployment target**: GKE (official ADK + GKE tutorial) or Agent Engine.
- **Interface**: `adk web` locally for dev; Slack or a web chat once
  deployed.

## Architecture

Single agent for the POC (multi-agent via A2A could be considered later to
separate "collection" from "synthesis"). All tools are **read-only**
(function calling):

- `get_alerts(time_range)`
- `get_pod_logs(namespace, pod)`
- `get_k8s_events(namespace)`
- `get_recent_deploys(namespace)` — deploy → incident correlation

Expected output: a structured summary (probable cause, timeline, impact) +
a draft postmortem in markdown.

## Key constraints

- **Read-only**: no tool may modify cluster state, trigger a deployment, or
  write to an external system. The agent diagnoses, it does not act.
- GCP/GKE credentials must never be committed; use standard authentication
  (ADC, mounted service account) and keep those files out of the repo.
- Prioritize code that's testable locally with `adk web` before any
  deployment to GKE/Agent Engine.

## Conventions

- **Commits**: must strictly follow the
  [Conventional Commits](https://www.conventionalcommits.org/) format
  (`feat: `, `fix: `, `chore: `, `docs: `, `refactor: `, `test: `, etc.).

## Project status

Core agent and tools are implemented (see `sre_agent/`): `get_alerts` and
`get_pod_logs` are wired to real GCP APIs, `get_k8s_events` and
`get_recent_deploys` use Cloud Audit Logs. What's left: simulating an
incident, deployment, DORA metric tracking.
