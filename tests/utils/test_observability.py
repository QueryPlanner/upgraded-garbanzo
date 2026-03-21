"""Tests for observability configuration."""

import logging
import os
from unittest.mock import patch

import pytest

from agent.utils.observability import configure_otel_resource, setup_logging


class TestConfigureOtelResource:
    """Tests for configure_otel_resource function."""

    def test_sets_otel_resource_attributes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that OTEL_RESOURCE_ATTRIBUTES is set."""
        monkeypatch.delenv("OTEL_RESOURCE_ATTRIBUTES", raising=False)
        configure_otel_resource("test-agent")

        assert "OTEL_RESOURCE_ATTRIBUTES" in os.environ
        assert "service.instance.id" in os.environ["OTEL_RESOURCE_ATTRIBUTES"]
        assert "service.name=test-agent" in os.environ["OTEL_RESOURCE_ATTRIBUTES"]

    def test_uses_telemetry_namespace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that TELEMETRY_NAMESPACE is used."""
        monkeypatch.setenv("TELEMETRY_NAMESPACE", "production")
        monkeypatch.delenv("OTEL_RESOURCE_ATTRIBUTES", raising=False)

        configure_otel_resource("test-agent")

        assert "service.namespace=production" in os.environ["OTEL_RESOURCE_ATTRIBUTES"]

    def test_uses_k_revision(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that K_REVISION is used for service version."""
        monkeypatch.setenv("K_REVISION", "v1.2.3")
        monkeypatch.delenv("OTEL_RESOURCE_ATTRIBUTES", raising=False)

        configure_otel_resource("test-agent")

        assert "service.version=v1.2.3" in os.environ["OTEL_RESOURCE_ATTRIBUTES"]

    def test_configures_langfuse_when_keys_present(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that Langfuse is configured when keys are present."""
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_HEADERS", raising=False)
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_PROTOCOL", raising=False)

        configure_otel_resource("test-agent")

        assert "OTEL_EXPORTER_OTLP_ENDPOINT" in os.environ
        assert "langfuse.com" in os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"]
        assert "OTEL_EXPORTER_OTLP_HEADERS" in os.environ
        assert "OTEL_EXPORTER_OTLP_PROTOCOL" in os.environ
        assert os.environ["OTEL_EXPORTER_OTLP_PROTOCOL"] == "http/protobuf"

    def test_uses_custom_langfuse_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that custom Langfuse URL is used."""
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
        monkeypatch.setenv("LANGFUSE_BASE_URL", "https://custom.langfuse.com")
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_HEADERS", raising=False)
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_PROTOCOL", raising=False)

        configure_otel_resource("test-agent")

        assert "custom.langfuse.com" in os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"]

    def test_respects_existing_otel_endpoint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that existing OTEL_EXPORTER_OTLP_ENDPOINT is not overwritten."""
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://existing.endpoint")

        configure_otel_resource("test-agent")

        assert os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] == "https://existing.endpoint"

    def test_no_langfuse_without_keys(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that Langfuse is not configured without keys."""
        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_HEADERS", raising=False)
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_PROTOCOL", raising=False)

        configure_otel_resource("test-agent")

        assert "OTEL_EXPORTER_OTLP_ENDPOINT" not in os.environ
        assert "OTEL_EXPORTER_OTLP_HEADERS" not in os.environ


class TestSetupLogging:
    """Tests for setup_logging function."""

    def test_sets_log_level_info(self) -> None:
        """Test that INFO level is passed to basicConfig."""
        with patch("agent.utils.observability.logging.basicConfig") as mock_config:
            setup_logging("INFO")
            mock_config.assert_called_once()
            assert mock_config.call_args[1]["level"] == logging.INFO

    def test_sets_log_level_debug(self) -> None:
        """Test that DEBUG level is passed to basicConfig."""
        with patch("agent.utils.observability.logging.basicConfig") as mock_config:
            setup_logging("DEBUG")
            mock_config.assert_called_once()
            assert mock_config.call_args[1]["level"] == logging.DEBUG

    def test_sets_log_level_warning(self) -> None:
        """Test that WARNING level is passed to basicConfig."""
        with patch("agent.utils.observability.logging.basicConfig") as mock_config:
            setup_logging("WARNING")
            mock_config.assert_called_once()
            assert mock_config.call_args[1]["level"] == logging.WARNING

    def test_handles_lowercase_level(self) -> None:
        """Test that lowercase level names work."""
        with patch("agent.utils.observability.logging.basicConfig") as mock_config:
            setup_logging("info")
            mock_config.assert_called_once()
            assert mock_config.call_args[1]["level"] == logging.INFO

    def test_defaults_to_info_for_invalid_level(self) -> None:
        """Test that invalid level defaults to INFO."""
        with patch("agent.utils.observability.logging.basicConfig") as mock_config:
            setup_logging("INVALID")
            mock_config.assert_called_once()
            assert mock_config.call_args[1]["level"] == logging.INFO

    def test_sets_urllib3_level(self) -> None:
        """Test that urllib3 logger level is set to WARNING."""
        with patch("agent.utils.observability.logging.basicConfig"):
            setup_logging("DEBUG")
            urllib3_logger = logging.getLogger("urllib3")
            assert urllib3_logger.level == logging.WARNING
