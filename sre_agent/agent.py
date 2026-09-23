from google.adk.agents.llm_agent import Agent

from .tools import get_alerts, get_k8s_events, get_pod_logs, get_recent_deploys

root_agent = Agent(
    model='gemini-3.5-flash',
    name='root_agent',
    description='Copilote SRE qui diagnostique des incidents GKE.',
    instruction=(
        'Tu es un copilote SRE. Corrèle les alertes, logs et events Kubernetes '
        'pour identifier la cause probable d\'un incident, puis propose une '
        'timeline et un brouillon de postmortem en markdown.'
    ),
    tools=[get_alerts, get_pod_logs, get_k8s_events, get_recent_deploys],
)
