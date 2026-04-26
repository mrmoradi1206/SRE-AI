from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

REQUEST_COUNT = Counter('sre_ai_http_requests_total', 'HTTP request count', ['service', 'method', 'path', 'status'])
REQUEST_LATENCY = Histogram('sre_ai_http_request_duration_seconds', 'HTTP request latency', ['service', 'method', 'path'])
REQUEST_ERRORS = Counter('sre_ai_http_errors_total', 'HTTP errors', ['service', 'method', 'path', 'status'])
REQUEST_IN_FLIGHT = Gauge('sre_ai_http_requests_in_flight', 'In-flight HTTP requests', ['service'])
EXTERNAL_CALLS = Counter('sre_ai_external_calls_total', 'External or inter-service calls', ['service', 'target', 'method', 'status'])
DLQ_EVENTS = Counter('sre_ai_dlq_events_total', 'Dead letter queue enqueues', ['service', 'operation'])
QUEUE_DEPTH = Gauge('sre_ai_queue_depth', 'Queue depth by topic', ['topic'])
AGENT_ACTIONS = Counter('sre_ai_agent_actions_total', 'Agent actions by type', ['service', 'action'])
DB_POOL_CHECKOUTS = Counter('sre_ai_db_pool_checkouts_total', 'DB pool checkouts', ['service'])
DB_POOL_CHECKINS = Counter('sre_ai_db_pool_checkins_total', 'DB pool checkins', ['service'])
DB_POOL_SIZE = Gauge('sre_ai_db_pool_size', 'Configured DB pool size', ['service'])


def metrics_router() -> APIRouter:
    router = APIRouter()

    @router.get('/metrics', include_in_schema=False)
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return router
