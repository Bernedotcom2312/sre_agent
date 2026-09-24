from google.adk.agents.llm_agent import Agent

from .tools import get_alerts, get_k8s_events, get_pod_logs, get_recent_deploys

root_agent = Agent(
    model="gemini-3.5-flash-lite",
    name="root_agent",
    description="SRE copilot that diagnoses GKE incidents.",
    instruction=(
        "You are an SRE copilot. You must always ground your answers in real "
        "data fetched via your tools — never guess or answer from memory "
        "alone, even for a simple status question.\n\n"
        "For any question about the state of a namespace or an incident, "
        "first call get_k8s_events(namespace) and get_recent_deploys(namespace) "
        "to see recent events and deployments. Call get_alerts(time_range) to "
        "check firing alert policies. If a pod name is known or surfaced by "
        "get_k8s_events, call get_pod_logs(namespace, pod) to inspect its logs.\n\n"
        "Then correlate the alerts, logs, and events to identify the probable "
        "cause, and propose a timeline and a draft postmortem in markdown."
    ),
    tools=[get_alerts, get_pod_logs, get_k8s_events, get_recent_deploys],
)
