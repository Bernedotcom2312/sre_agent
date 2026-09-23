import os

from google.api_core.exceptions import GoogleAPICallError
from google.auth.exceptions import DefaultCredentialsError
from google.cloud import monitoring_v3


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
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project_id:
        return {"error": "GOOGLE_CLOUD_PROJECT n'est pas défini dans l'environnement."}

    try:
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

    except DefaultCredentialsError:
        return {
            "error": (
                "Authentification GCP manquante. Lance "
                "`gcloud auth application-default login` puis réessaie."
            )
        }
    except GoogleAPICallError as exc:
        return {"error": f"Erreur API Cloud Monitoring: {exc.message}"}


def get_pod_logs(namespace: str, pod: str) -> dict:
    """Récupère les dernières lignes de logs d'un pod Kubernetes via Cloud Logging.

    Args:
        namespace: namespace Kubernetes du pod.
        pod: nom du pod.
    """
    return {
        "namespace": namespace,
        "pod": pod,
        "logs": [
            "2026-09-23T09:11:40Z ERROR OOMKilled: container exceeded memory limit",
            "2026-09-23T09:11:35Z WARN  request latency p99 > 2000ms",
        ],
    }


def get_k8s_events(namespace: str) -> dict:
    """Récupère les events Kubernetes récents d'un namespace.

    Args:
        namespace: namespace Kubernetes à inspecter.
    """
    return {
        "namespace": namespace,
        "events": [
            {
                "reason": "BackOff",
                "message": "Back-off restarting failed container",
                "object": "pod/payments-api-7d4f9c-abcde",
            }
        ],
    }


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
