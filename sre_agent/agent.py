from google.adk.agents.llm_agent import Agent

from .tools import get_alerts, get_k8s_events, get_pod_logs, get_recent_deploys

root_agent = Agent(
    model="gemini-3.5-flash",
    name="root_agent",
    description="SRE copilot that diagnoses GKE incidents.",
    instruction=(
        "You are an SRE copilot. Correlate alerts, logs, and Kubernetes events "
        "to identify the probable cause of an incident, then propose a "
        "timeline and a draft postmortem in markdown."
    ),
    tools=[get_alerts, get_pod_logs, get_k8s_events, get_recent_deploys],
)
