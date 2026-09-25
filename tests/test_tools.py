from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from google.api_core.exceptions import GoogleAPICallError
from google.auth.exceptions import DefaultCredentialsError
from google.cloud.logging import DESCENDING

from sre_agent.tools import (
    get_alerts,
    get_k8s_events,
    get_pod_logs,
    get_recent_deploys,
    time_format,
)


def _fake_policy(display_name, enabled, severity, conditions):
    return SimpleNamespace(
        display_name=display_name,
        enabled=enabled,
        severity=SimpleNamespace(name=severity),
        conditions=[SimpleNamespace(display_name=c) for c in conditions],
    )


def _fake_log_entry(timestamp, payload):
    return SimpleNamespace(timestamp=timestamp, payload=payload)


def test_get_alerts_missing_project_id(monkeypatch):
    monkeypatch.setattr("sre_agent.tools.project_id", None)

    result = get_alerts("1h")

    assert "error" in result
    assert "GOOGLE_CLOUD_PROJECT" in result["error"]


@patch("sre_agent.tools.monitoring_v3.AlertPolicyServiceClient")
def test_get_alerts_filters_disabled_policies_and_maps_fields(mock_client_cls, monkeypatch):
    monkeypatch.setattr("sre_agent.tools.project_id", "my-project")
    mock_client = MagicMock()
    mock_client.list_alert_policies.return_value = [
        _fake_policy("High CPU", True, "CRITICAL", ["CPU > 90%"]),
        _fake_policy("Disabled alert", False, "WARNING", []),
    ]
    mock_client_cls.return_value = mock_client

    result = get_alerts("1h")

    mock_client.list_alert_policies.assert_called_once_with(name="projects/my-project")
    assert result["time_range"] == "1h"
    assert result["alert_policies"] == [
        {
            "name": "High CPU",
            "severity": "CRITICAL",
            "conditions": ["CPU > 90%"],
        }
    ]
    # The model reads this alongside the list; without it, configured policies
    # get reported as alerts that are ringing.
    assert "not alerts currently firing" in result["note"]


@patch("sre_agent.tools.monitoring_v3.AlertPolicyServiceClient")
def test_get_alerts_handles_missing_credentials(mock_client_cls, monkeypatch):
    monkeypatch.setattr("sre_agent.tools.project_id", "my-project")
    mock_client_cls.side_effect = DefaultCredentialsError("no ADC found")

    result = get_alerts("1h")

    assert "error" in result
    assert "gcloud auth application-default login" in result["error"]


@patch("sre_agent.tools.monitoring_v3.AlertPolicyServiceClient")
def test_get_alerts_handles_api_error(mock_client_cls, monkeypatch):
    monkeypatch.setattr("sre_agent.tools.project_id", "my-project")
    mock_client = MagicMock()
    mock_client.list_alert_policies.side_effect = GoogleAPICallError("quota exceeded")
    mock_client_cls.return_value = mock_client

    result = get_alerts("1h")

    assert result == {"error": "GCP API error in get_alerts: quota exceeded"}


def test_get_pod_logs_missing_project_id(monkeypatch):
    monkeypatch.setattr("sre_agent.tools.project_id", None)

    result = get_pod_logs("toto", "tata")

    assert "error" in result
    assert "GOOGLE_CLOUD_PROJECT" in result["error"]


@patch("sre_agent.tools.logging.Client")
def test_get_pod_logs_handles_missing_credentials(mock_client_cls, monkeypatch):
    monkeypatch.setattr("sre_agent.tools.project_id", "my-project")
    mock_client_cls.side_effect = DefaultCredentialsError("no ADC found")

    result = get_pod_logs("toto", "tata")

    assert "error" in result
    assert "gcloud auth application-default login" in result["error"]


@patch("sre_agent.tools.logging.Client")
def test_get_pod_logs_handles_api_error(mock_client_cls, monkeypatch):
    monkeypatch.setattr("sre_agent.tools.project_id", "my-project")
    mock_client = MagicMock()
    mock_client.list_entries.side_effect = GoogleAPICallError("quota exceeded")
    mock_client_cls.return_value = mock_client

    result = get_pod_logs("toto", "tata")

    assert result == {"error": "GCP API error in get_pod_logs: quota exceeded"}


@patch("sre_agent.tools.logging.Client")
def test_get_pod_logs_maps_log_entries(mock_client_cls, monkeypatch):
    monkeypatch.setattr("sre_agent.tools.project_id", "my-project")
    entry_1 = _fake_log_entry(
        timestamp=datetime(2026, 9, 24, 10, 0, 0, tzinfo=UTC),
        payload="INFO : healthcheck",
    )
    entry_2 = _fake_log_entry(
        timestamp=datetime(2026, 9, 24, 10, 0, 5, tzinfo=UTC),
        payload="ERROR : CrashLoopBackOff",
    )
    mock_client = MagicMock()
    mock_client.list_entries.return_value = [entry_1, entry_2]
    mock_client_cls.return_value = mock_client

    result = get_pod_logs("toto", "tata")

    mock_client_cls.assert_called_once_with(project="my-project")
    _, call_kwargs = mock_client.list_entries.call_args
    assert call_kwargs["order_by"] == DESCENDING
    assert call_kwargs["max_results"] == 100
    assert 'resource.type="k8s_container"' in call_kwargs["filter_"]
    assert 'resource.labels.namespace_name="toto"' in call_kwargs["filter_"]
    assert 'resource.labels.container_name="tata"' in call_kwargs["filter_"]
    assert result == {
        "namespace": "toto",
        "pod": "tata",
        "logs": [
            {
                "timestamp": entry_1.timestamp.strftime(time_format),
                "message": "INFO : healthcheck",
            },
            {
                "timestamp": entry_2.timestamp.strftime(time_format),
                "message": "ERROR : CrashLoopBackOff",
            },
        ],
    }


@patch("sre_agent.tools.logging.Client")
def test_get_pod_logs_recomputes_the_time_window_on_every_call(mock_client_cls, monkeypatch):
    """The lookback window must be derived from the clock at call time.

    Patching the module's `datetime` only affects a window computed inside
    the call: a module-level constant would keep the timestamp it got at
    import time, which is the regression this guards against.
    """
    monkeypatch.setattr("sre_agent.tools.project_id", "my-project")
    mock_client = MagicMock()
    mock_client.list_entries.return_value = []
    mock_client_cls.return_value = mock_client

    with patch("sre_agent.tools.datetime") as mock_datetime:
        mock_datetime.now.return_value = datetime(2026, 9, 24, 12, 0, 0, tzinfo=UTC)
        get_pod_logs("toto", "tata")

    _, call_kwargs = mock_client.list_entries.call_args
    assert 'timestamp>="2026-09-24T11:00:00.000000+0000"' in call_kwargs["filter_"]


@patch("sre_agent.tools.logging.Client")
def test_get_pod_logs_returns_empty_logs_when_no_entries(mock_client_cls, monkeypatch):
    monkeypatch.setattr("sre_agent.tools.project_id", "my-project")
    mock_client = MagicMock()
    mock_client.list_entries.return_value = []
    mock_client_cls.return_value = mock_client

    result = get_pod_logs("toto", "tata")

    mock_client.list_entries.assert_called_once()
    assert result == {"namespace": "toto", "pod": "tata", "logs": []}


def test_get_k8s_events_missing_project_id(monkeypatch):
    monkeypatch.setattr("sre_agent.tools.project_id", None)

    result = get_k8s_events("toto")

    assert "error" in result
    assert "GOOGLE_CLOUD_PROJECT" in result["error"]


@patch("sre_agent.tools.logging.Client")
def test_get_k8s_events_handles_missing_credentials(mock_client_cls, monkeypatch):
    monkeypatch.setattr("sre_agent.tools.project_id", "my-project")
    mock_client_cls.side_effect = DefaultCredentialsError("no ADC found")

    result = get_k8s_events("toto")

    assert "error" in result
    assert "gcloud auth application-default login" in result["error"]


@patch("sre_agent.tools.logging.Client")
def test_get_k8s_events_handles_api_error(mock_client_cls, monkeypatch):
    monkeypatch.setattr("sre_agent.tools.project_id", "my-project")
    mock_client = MagicMock()
    mock_client.list_entries.side_effect = GoogleAPICallError("quota exceeded")
    mock_client_cls.return_value = mock_client

    result = get_k8s_events("toto")

    assert result == {"error": "GCP API error in get_k8s_events: quota exceeded"}


@patch("sre_agent.tools.logging.Client")
def test_get_k8s_events_maps_log_entries(mock_client_cls, monkeypatch):
    monkeypatch.setattr("sre_agent.tools.project_id", "my-project")
    entry_1 = _fake_log_entry(
        timestamp=datetime(2026, 9, 24, 10, 0, 0, tzinfo=UTC),
        payload={
            "reason": "BackOff",
            "message": "Back-off restarting failed container",
            "involvedObject": {"name": "pod1"},
        },
    )
    entry_2 = _fake_log_entry(
        timestamp=datetime(2026, 9, 24, 10, 0, 5, tzinfo=UTC),
        payload={
            "reason": "OOMKilled",
            "message": "Memory excedeed",
            "involvedObject": {"name": "pod2"},
        },
    )
    mock_client = MagicMock()
    mock_client.list_entries.return_value = [entry_1, entry_2]
    mock_client_cls.return_value = mock_client

    result = get_k8s_events("toto")

    mock_client_cls.assert_called_once_with(project="my-project")
    _, call_kwargs = mock_client.list_entries.call_args
    assert call_kwargs["order_by"] == DESCENDING
    assert call_kwargs["max_results"] == 100
    assert 'resource.type="k8s_event"' in call_kwargs["filter_"]
    assert 'resource.labels.namespace_name="toto"' in call_kwargs["filter_"]
    assert result == {
        "namespace": "toto",
        "events": [
            {
                "timestamp": entry_1.timestamp.strftime(time_format),
                "reason": entry_1.payload["reason"],
                "message": entry_1.payload["message"],
                "object": entry_1.payload["involvedObject"]["name"],
            },
            {
                "timestamp": entry_2.timestamp.strftime(time_format),
                "reason": entry_2.payload["reason"],
                "message": entry_2.payload["message"],
                "object": entry_2.payload["involvedObject"]["name"],
            },
        ],
    }


@patch("sre_agent.tools.logging.Client")
def test_get_k8s_events_returns_empty_logs_when_no_entries(mock_client_cls, monkeypatch):
    monkeypatch.setattr("sre_agent.tools.project_id", "my-project")
    mock_client = MagicMock()
    mock_client.list_entries.return_value = []
    mock_client_cls.return_value = mock_client

    result = get_k8s_events("toto")

    mock_client.list_entries.assert_called_once()
    assert result == {"namespace": "toto", "events": []}


def test_get_recent_deploys_missing_project_id(monkeypatch):
    monkeypatch.setattr("sre_agent.tools.project_id", None)

    result = get_recent_deploys("toto")

    assert "error" in result
    assert "GOOGLE_CLOUD_PROJECT" in result["error"]


@patch("sre_agent.tools.logging.Client")
def test_get_recent_deploys_handles_missing_credentials(mock_client_cls, monkeypatch):
    monkeypatch.setattr("sre_agent.tools.project_id", "my-project")
    mock_client_cls.side_effect = DefaultCredentialsError("no ADC found")

    result = get_recent_deploys("toto")

    assert "error" in result
    assert "gcloud auth application-default login" in result["error"]


@patch("sre_agent.tools.logging.Client")
def test_get_recent_deploys_handles_api_error(mock_client_cls, monkeypatch):
    monkeypatch.setattr("sre_agent.tools.project_id", "my-project")
    mock_client = MagicMock()
    mock_client.list_entries.side_effect = GoogleAPICallError("quota exceeded")
    mock_client_cls.return_value = mock_client

    result = get_recent_deploys("toto")

    assert result == {"error": "GCP API error in get_recent_deploys: quota exceeded"}


@patch("sre_agent.tools.logging.Client")
def test_get_recent_deploys_maps_log_entries(mock_client_cls, monkeypatch):
    monkeypatch.setattr("sre_agent.tools.project_id", "my-project")
    entry_1 = _fake_log_entry(
        timestamp=datetime(2026, 9, 24, 10, 0, 0, tzinfo=UTC),
        payload={
            "resourceName": "namespaces/toto/deployments/payments-api",
            "methodName": "io.k8s.apps.v1.deployments.update",
            "authenticationInfo": {"principalEmail": "ci@my-project.iam.gserviceaccount.com"},
        },
    )
    entry_2 = _fake_log_entry(
        timestamp=datetime(2026, 9, 24, 10, 5, 0, tzinfo=UTC),
        payload={
            "resourceName": "namespaces/toto/deployments/payments-worker",
            "methodName": "io.k8s.apps.v1.deployments.create",
            "authenticationInfo": {"principalEmail": "alice@example.com"},
        },
    )
    mock_client = MagicMock()
    mock_client.list_entries.return_value = [entry_1, entry_2]
    mock_client_cls.return_value = mock_client

    result = get_recent_deploys("toto")

    mock_client_cls.assert_called_once_with(project="my-project")
    _, call_kwargs = mock_client.list_entries.call_args
    assert call_kwargs["order_by"] == DESCENDING
    assert call_kwargs["max_results"] == 100
    assert 'protoPayload.methodName:"deployments.create"' in call_kwargs["filter_"]
    assert 'protoPayload.methodName:"deployments.update"' in call_kwargs["filter_"]
    assert 'protoPayload.methodName:"deployments.patch"' in call_kwargs["filter_"]
    # A deletion is not a deploy: it must not be able to match the filter.
    assert "deployments.delete" not in call_kwargs["filter_"]
    assert 'protoPayload.resourceName:"namespaces/toto/deployments"' in call_kwargs["filter_"]
    assert result == {
        "namespace": "toto",
        "deploys": [
            {
                "timestamp": entry_1.timestamp.strftime(time_format),
                "deployment": "payments-api",
                "method": "io.k8s.apps.v1.deployments.update",
                "principal": "ci@my-project.iam.gserviceaccount.com",
            },
            {
                "timestamp": entry_2.timestamp.strftime(time_format),
                "deployment": "payments-worker",
                "method": "io.k8s.apps.v1.deployments.create",
                "principal": "alice@example.com",
            },
        ],
    }


@patch("sre_agent.tools.logging.Client")
def test_get_recent_deploys_returns_empty_deploys_when_no_entries(mock_client_cls, monkeypatch):
    monkeypatch.setattr("sre_agent.tools.project_id", "my-project")
    mock_client = MagicMock()
    mock_client.list_entries.return_value = []
    mock_client_cls.return_value = mock_client

    result = get_recent_deploys("toto")

    mock_client.list_entries.assert_called_once()
    assert result == {"namespace": "toto", "deploys": []}
