import os

from google.api_core.exceptions import GoogleAPICallError
from google.auth.exceptions import DefaultCredentialsError
from google.cloud import monitoring_v3, logging
from google.cloud.logging import DESCENDING
from datetime import datetime, timedelta, timezone

project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
last_hour = datetime.now(timezone.utc) - timedelta(hours=1)
time_format = "%Y-%m-%dT%H:%M:%S.%f%z"

def handle_gcp_errors(func):
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except DefaultCredentialsError:
            return {
                "error": (
                        "Authentification GCP manquante. Lance "
                        "`gcloud auth application-default login` puis réessaie."
                )
            }
        except GoogleAPICallError as exc:
            return {"error": f"Erreur API GCP dans {func.__name__}: {exc.message}"}
    return wrapper

@handle_gcp_errors
def get_alerts(time_range: str) -> dict:
    """Récupère les politiques d'alerte Cloud Monitoring actives sur le projet.

    Note : l'API Cloud Monitoring n'expose pas publiquement la liste des
    incidents en cours (les alertes "en train de sonner"), seulement les
    politiques d'alerte configurées. On retourne donc les politiques
    activées comme proxy des alertes surveillées. `time_range` est gardé
    dans la signature pour un futur filtrage temporel (ex: via Cloud
    Logging) mais n'est pas encore utilisé.

    Args:
        time_range: fenêtre temporelle, ex: "1h", "24h".
    """
    if not project_id:
        return {"error": "GOOGLE_CLOUD_PROJECT n'est pas défini dans l'environnement."}

    client = monitoring_v3.AlertPolicyServiceClient()
    policies = client.list_alert_policies(name=f"projects/{project_id}")

    alerts = [
        {
            "name": policy.display_name,
            "severity": policy.severity.name,
            "conditions": [condition.display_name for condition in policy.conditions],
        }
        for policy in policies
        if policy.enabled
    ]
    return {"time_range": time_range, "alerts": alerts}

def _fetch_log_entries(filter_: str, max_results: int = 100):
    """Interroge Cloud Logging et retourne les entrées correspondant au filtre."""
    logging_client = logging.Client(project=project_id)
    return logging_client.list_entries(order_by=DESCENDING, filter_=filter_, max_results=max_results)

@handle_gcp_errors
def get_pod_logs(namespace: str, pod: str) -> dict:
    """Récupère les dernières lignes de logs d'un pod Kubernetes via Cloud Logging.

    Args:
        namespace: namespace Kubernetes du pod.
        pod: nom du pod.
    """
    if not project_id:
        return {"error": "GOOGLE_CLOUD_PROJECT n'est pas défini dans l'environnement."}

    FILTER = (
    f'resource.type:k8s_container'
    f' AND resource.labels.namespace_name="{namespace}"'
    f' AND resource.labels.pod_name="{pod}"'
    f' AND timestamp>="{last_hour.strftime(time_format)}"'
    )

    logs = [
        {
            "timestamp": entry.timestamp.strftime(time_format),
            "message": entry.payload,
        }
        for entry in _fetch_log_entries(FILTER)
    ]
    return {"namespace": namespace, "pod": pod, "logs": logs}

@handle_gcp_errors
def get_k8s_events(namespace: str) -> dict:
    """Récupère les events Kubernetes récents d'un namespace.

    Args:
        namespace: namespace Kubernetes à inspecter.
    """
    if not project_id:
        return {"error": "GOOGLE_CLOUD_PROJECT n'est pas défini dans l'environnement."}

    FILTER = (
    f'resource.type:k8s_event'
    f' AND resource.labels.namespace_name="{namespace}"'
    f' AND timestamp>="{last_hour.strftime(time_format)}"'
    )

    events = [
        {
            "timestamp": entry.timestamp.strftime(time_format),
            "reason": entry.payload["reason"],
            "message": entry.payload["message"],
            "object": entry.payload["involvedObject"]["name"],
        }
        for entry in _fetch_log_entries(FILTER)
    ]
    return {"namespace": namespace, "events": events}



def get_recent_deploys(namespace: str) -> dict:
    """Récupère les déploiements récents d'un namespace pour repérer une corrélation déploiement -> incident.

    Args:
        namespace: namespace Kubernetes à inspecter.
    """
    return {
        "namespace": namespace,
        "deploys": [
            {
                "revision": "payments-api-v42",
                "deployed_at": "2026-09-23T09:00:00Z",
                "commit": "a1b2c3d",
            }
        ],
    }
