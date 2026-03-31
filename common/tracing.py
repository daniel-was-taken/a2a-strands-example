"""OpenTelemetry tracing setup.

Call ``configure_tracing(service_name=...)`` once at process startup.
When ``OTEL_EXPORTER_OTLP_ENDPOINT`` is not set the call is a no-op, so
local development is unaffected.

To enable tracing in production:
1. Install ``strands-agents[otel]`` (already included in pyproject.toml extras).
2. Set ``OTEL_EXPORTER_OTLP_ENDPOINT=http://your-otel-collector:4317``.

Usage::

    from common.tracing import configure_tracing
    configure_tracing(service_name="db-agent")
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def configure_tracing(service_name: str) -> None:
    """Initialise OTLP trace export if ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set.

    Args:
        service_name: Value for the ``service.name`` OTel resource attribute.
    """
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        logger.debug("OTEL_EXPORTER_OTLP_ENDPOINT not set — OpenTelemetry tracing disabled")
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
        trace.set_tracer_provider(provider)
        logger.info(
            "OpenTelemetry tracing configured",
            extra={"agent_name": service_name},
        )
    except ImportError:
        logger.warning(
            "opentelemetry-sdk not installed. "
            "Install 'strands-agents[otel]' to enable distributed tracing."
        )
