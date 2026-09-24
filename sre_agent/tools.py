import os
from datetime import UTC, datetime, timedelta
from functools import wraps

from google.api_core.exceptions import GoogleAPICallError
from google.auth.exceptions import DefaultCredentialsError
from google.cloud import logging, monitoring_v3
from google.cloud.logging import DESCENDING

project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
last_hour = datetime.now(UTC) - timedelta(hours=1)
time_format = "%Y-%m-%dT%H:%M:%S.%f%z"


def handle_gcp_errors(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except DefaultCredentialsError:
            return {
                "error": (
                    "Missing GCP authentication. Run "
                    "`gcloud auth application-default login` then try again."
                )
            }
        except GoogleAPICallError as exc:
            return {"error": f"GCP API error in {func.__name__}: {exc.message}"}

    return wrapper


@handle_gcp_errors
def get_alerts(time_range: str) -> dict:
    """Fetches the active Cloud Monitoring alert policies for the project.

    Note: the Cloud Monitoring API does not publicly expose the list of
    currently firing incidents (alerts "actively ringing"), only the
    configured alert policies. We therefore return the enabled policies as a
    proxy for the monitored alerts. `time_range` is kept in the signature for
    future time-based filtering (e.g. via Cloud Logging) but is not used yet.

    Args:
        time_range: time window, e.g. "1h", "24h".
    """
    if not project_id:
        return {"error": "GOOGLE_CLOUD_PROJECT is not set in the environment."}

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
    """Queries Cloud Logging and returns the entries matching the filter."""
    logging_client = logging.Client(project=project_id)
    return logging_client.list_entries(
        order_by=DESCENDING, filter_=filter_, max_results=max_results
    )


@handle_gcp_errors
def get_pod_logs(namespace: str, pod: str) -> dict:
    """Fetches the latest log lines for a Kubernetes pod via Cloud Logging.

    Args:
        namespace: Kubernetes namespace of the pod.
        pod: container name to match against (resource.labels.container_name).
    """
    if not project_id:
        return {"error": "GOOGLE_CLOUD_PROJECT is not set in the environment."}

    log_filter = (
        f"resource.type:k8s_container"
        f' AND resource.labels.namespace_name="{namespace}"'
        f' AND resource.labels.container_name="{pod}"'
        f' AND timestamp>="{last_hour.strftime(time_format)}"'
    )

    logs = [
        {
            "timestamp": entry.timestamp.strftime(time_format),
            "message": entry.payload,
        }
        for entry in _fetch_log_entries(log_filter)
    ]
    return {"namespace": namespace, "pod": pod, "logs": logs}


@handle_gcp_errors
def get_k8s_events(namespace: str) -> dict:
    """Fetches recent Kubernetes events for a namespace.

    Args:
        namespace: Kubernetes namespace to inspect.
    """
    if not project_id:
        return {"error": "GOOGLE_CLOUD_PROJECT is not set in the environment."}

    log_filter = (
        f'(resource.type="k8s_event" OR resource.type="k8s_pod")'
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
        for entry in _fetch_log_entries(log_filter)
    ]
    return {"namespace": namespace, "events": events}


@handle_gcp_errors
def get_recent_deploys(namespace: str) -> dict:
    """Fetches recent deployments for a namespace via GKE Cloud Audit Logs,
    to spot a deploy -> incident correlation.

    Relies on the Admin Activity audit logs
    (`cloudaudit.googleapis.com/activity`), which log Deployment creations and
    updates. These logs don't carry the associated git commit (unless a
    specific annotation is added by CI, which isn't handled here), so we
    expose the revision, the method (create/update/patch), and the author of
    the change instead.

    Args:
        namespace: Kubernetes namespace to inspect.
    """
    if not project_id:
        return {"error": "GOOGLE_CLOUD_PROJECT is not set in the environment."}

    log_filter = (
        f'logName="projects/{project_id}/logs/cloudaudit.googleapis.com%2Factivity"'
        f' AND resource.type="k8s_cluster"'
        f' AND protoPayload.methodName:"deployments"'
        f' AND protoPayload.resourceName:"namespaces/{namespace}/deployments"'
        f' AND timestamp>="{last_hour.strftime(time_format)}"'
    )

    deploys = [
        {
            "timestamp": entry.timestamp.strftime(time_format),
            "revision": entry.payload["resourceName"].split("/")[-1],
            "method": entry.payload["methodName"],
            "principal": entry.payload.get("authenticationInfo", {}).get("principalEmail"),
        }
        for entry in _fetch_log_entries(log_filter)
    ]
    return {"namespace": namespace, "deploys": deploys}
