def get_alerts(time_range: str) -> dict:
    """Récupère les alertes Cloud Monitoring actives sur une période donnée.

    Args:
        time_range: fenêtre temporelle, ex: "1h", "24h".
    """
    return {
        "alerts": [
            {
                "name": "CPU high",
                "severity": "warning",
                "resource": "payments-api",
                "started_at": "2026-09-23T09:12:00Z",
            }
        ]
    }


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
