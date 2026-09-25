import os
from datetime import UTC, datetime, timedelta
from functools import wraps

import google.auth
from google.api_core.exceptions import GoogleAPICallError
from google.auth.exceptions import DefaultCredentialsError
from google.cloud import logging, monitoring_v3
from google.cloud.logging import DESCENDING


def _resolve_project_id() -> str | None:
    """Resolves the GCP project, falling back to ADC-discovered project.

    `adk deploy agent_engine` strips GOOGLE_CLOUD_PROJECT from the deployed
    agent's runtime env vars (it only uses it to pick the deploy target), so
    once deployed this env var is absent and we must fall back to the
    ambient credentials' project instead.
    """
    env_project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if env_project:
        return env_project
    try:
        _, adc_project = google.auth.default()
        return adc_project
    except DefaultCredentialsError:
        return None


project_id = _resolve_project_id()
time_format = "%Y-%m-%dT%H:%M:%S.%f%z"


def _since(hours: int = 1) -> str:
    """Formats the start of the lookback window for a Cloud Logging filter.

    Computed on every call, deliberately not stored in a module-level
    constant: the agent process is long-lived (`adk web` locally, an Agent
    Engine instance once deployed), so a constant would pin every query to
    the hour preceding the process start and, after an hour of uptime,
    report an ongoing incident as a quiet namespace.
    """
    return (datetime.now(UTC) - timedelta(hours=hours)).strftime(time_format)


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
    """Lists the alert policies configured and enabled on the project.

    These are the rules the project monitors, NOT the alerts currently
    firing: the Cloud Monitoring API does not publicly expose open incidents
    (alerts "actively ringing"), only their configuration. A policy in this
    list says nothing about the current state of the system, so never report
    one as an active alert or as evidence of an incident — use it only to
    know what is monitored, and confirm any actual symptom via
    get_k8s_events, get_pod_logs or get_recent_deploys.

    `time_range` is kept in the signature for future time-based filtering
    (e.g. via Cloud Logging) but is not used yet.

    Args:
        time_range: time window, e.g. "1h", "24h".
    """
    if not project_id:
        return {
            "error": (
                "Could not resolve a GCP project (no GOOGLE_CLOUD_PROJECT env"
                " var and no ADC-discovered project)."
            )
        }

    client = monitoring_v3.AlertPolicyServiceClient()
    policies = client.list_alert_policies(name=f"projects/{project_id}")

    alert_policies = [
        {
            "name": policy.display_name,
            "severity": policy.severity.name,
            "conditions": [condition.display_name for condition in policy.conditions],
        }
        for policy in policies
        if policy.enabled
    ]
    # The key and the note are part of the tool's answer to the model, not
    # decoration: named "alerts", this list reads as "alerts that are ringing"
    # and gets reported as an incident symptom.
    return {
        "time_range": time_range,
        "note": (
            "Alert policies configured on the project, not alerts currently"
            " firing (the Cloud Monitoring API does not expose open incidents)."
        ),
        "alert_policies": alert_policies,
    }


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
        return {
            "error": (
                "Could not resolve a GCP project (no GOOGLE_CLOUD_PROJECT env"
                " var and no ADC-discovered project)."
            )
        }

    log_filter = (
        f'resource.type="k8s_container"'
        f' AND resource.labels.namespace_name="{namespace}"'
        f' AND resource.labels.container_name="{pod}"'
        f' AND timestamp>="{_since()}"'
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
        return {
            "error": (
                "Could not resolve a GCP project (no GOOGLE_CLOUD_PROJECT env"
                " var and no ADC-discovered project)."
            )
        }

    log_filter = (
        f'(resource.type="k8s_event" OR resource.type="k8s_pod")'
        f' AND resource.labels.namespace_name="{namespace}"'
        f' AND timestamp>="{_since()}"'
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
    expose the Deployment name, the method (create/update/patch), and the
    author of the change instead.

    Args:
        namespace: Kubernetes namespace to inspect.
    """
    if not project_id:
        return {
            "error": (
                "Could not resolve a GCP project (no GOOGLE_CLOUD_PROJECT env"
                " var and no ADC-discovered project)."
            )
        }

    log_filter = (
        f'logName="projects/{project_id}/logs/cloudaudit.googleapis.com%2Factivity"'
        f' AND resource.type="k8s_cluster"'
        # Spelled out instead of the shorter `methodName:"deployments"`, which
        # also matches `...deployments.delete` — a deletion would then be
        # listed as a deploy and correlated with the incident as one.
        f' AND (protoPayload.methodName:"deployments.create"'
        f' OR protoPayload.methodName:"deployments.update"'
        f' OR protoPayload.methodName:"deployments.patch")'
        f' AND protoPayload.resourceName:"namespaces/{namespace}/deployments"'
        f' AND timestamp>="{_since()}"'
    )

    deploys = [
        {
            "timestamp": entry.timestamp.strftime(time_format),
            "deployment": entry.payload["resourceName"].split("/")[-1],
            "method": entry.payload["methodName"],
            "principal": entry.payload.get("authenticationInfo", {}).get("principalEmail"),
        }
        for entry in _fetch_log_entries(log_filter)
    ]
    return {"namespace": namespace, "deploys": deploys}
