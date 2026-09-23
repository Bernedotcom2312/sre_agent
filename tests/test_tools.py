from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from google.api_core.exceptions import GoogleAPICallError
from google.auth.exceptions import DefaultCredentialsError

from sre_agent.tools import get_alerts


def _fake_policy(display_name, enabled, severity, conditions):
    return SimpleNamespace(
        display_name=display_name,
        enabled=enabled,
        severity=SimpleNamespace(name=severity),
        conditions=[SimpleNamespace(display_name=c) for c in conditions],
    )


def test_get_alerts_missing_project_id(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)

    result = get_alerts("1h")

    assert "error" in result
    assert "GOOGLE_CLOUD_PROJECT" in result["error"]


@patch("sre_agent.tools.monitoring_v3.AlertPolicyServiceClient")
def test_get_alerts_filters_disabled_policies_and_maps_fields(mock_client_cls, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "my-project")
    mock_client = MagicMock()
    mock_client.list_alert_policies.return_value = [
        _fake_policy("High CPU", True, "CRITICAL", ["CPU > 90%"]),
        _fake_policy("Disabled alert", False, "WARNING", []),
    ]
    mock_client_cls.return_value = mock_client

    result = get_alerts("1h")

    mock_client.list_alert_policies.assert_called_once_with(name="projects/my-project")
    assert result == {
        "time_range": "1h",
        "alerts": [
            {
                "name": "High CPU",
                "severity": "CRITICAL",
                "conditions": ["CPU > 90%"],
            }
        ],
    }


@patch("sre_agent.tools.monitoring_v3.AlertPolicyServiceClient")
def test_get_alerts_handles_missing_credentials(mock_client_cls, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "my-project")
    mock_client_cls.side_effect = DefaultCredentialsError("no ADC found")

    result = get_alerts("1h")

    assert "error" in result
    assert "gcloud auth application-default login" in result["error"]


@patch("sre_agent.tools.monitoring_v3.AlertPolicyServiceClient")
def test_get_alerts_handles_api_error(mock_client_cls, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "my-project")
    mock_client = MagicMock()
    mock_client.list_alert_policies.side_effect = GoogleAPICallError("quota exceeded")
    mock_client_cls.return_value = mock_client

    result = get_alerts("1h")

    assert result == {"error": "Erreur API Cloud Monitoring: quota exceeded"}
