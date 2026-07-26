"""Central logging/observability configuration.

Wires Python's stdlib `logging` to Azure Application Insights when
APPLICATIONINSIGHTS_CONNECTION_STRING is set (Container Apps/production), and
falls back to structured console logging only when it isn't (local dev/CI) —
so the app runs identically in both, no code branching needed elsewhere.

Every other module should just do `logger = logging.getLogger(__name__)` and
log normally; this module is the only place that knows about Azure Monitor.
"""
import os
import logging
import contextvars
import uuid

LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO').upper()

# Carries the current request's ID across async call stacks (set by RequestIdMiddleware
# in server.py) so every log line emitted while handling a request can include it,
# without having to thread a request_id parameter through every function signature.
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar('request_id', default='-')


class RequestIdLogFilter(logging.Filter):
    """Injects the current request ID into every log record as `%(request_id)s`."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


def configure_logging() -> None:
    """Configure logging once at process startup. Idempotent-ish: safe to call
    multiple times (e.g. under pytest-xdist workers) since basicConfig no-ops
    if handlers already exist, but we still guard explicitly for clarity."""
    root = logging.getLogger()
    if getattr(root, '_recruitment_pipeline_configured', False):
        return

    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        fmt='%(asctime)s %(levelname)-8s [%(request_id)s] %(name)s: %(message)s',
    ))
    handler.addFilter(RequestIdLogFilter())
    root.addHandler(handler)
    root.setLevel(LOG_LEVEL)

    connection_string = os.environ.get('APPLICATIONINSIGHTS_CONNECTION_STRING')
    if connection_string:
        # Local import: azure-monitor-opentelemetry pulls in the OpenTelemetry SDK,
        # which we don't want to require for local dev/CI runs that lack the connection string.
        from azure.monitor.opentelemetry import configure_azure_monitor
        configure_azure_monitor(
            connection_string=connection_string,
            # We already attach request_id via our own filter/handler above;
            # this only controls span/trace export, not our console formatting.
            logger_name='',  # root logger, so every module's logs are exported
        )
        logging.getLogger(__name__).info('Application Insights logging configured')
    else:
        logging.getLogger(__name__).warning(
            'APPLICATIONINSIGHTS_CONNECTION_STRING not set — logging to console only '
            '(expected in local dev/CI; should always be set in Azure).'
        )

    root._recruitment_pipeline_configured = True


def instrument_app(app) -> None:
    """Attach OpenTelemetry auto-instrumentation. Only meaningful when Azure Monitor
    is configured (see configure_logging); harmless no-op-ish otherwise since spans
    just won't be exported anywhere."""
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.pymongo import PymongoInstrumentor
    FastAPIInstrumentor.instrument_app(app)
    PymongoInstrumentor().instrument()
