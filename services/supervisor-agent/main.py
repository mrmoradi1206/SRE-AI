import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from aiops_shared.logging_config import configure_logging
from aiops_shared.metrics import metrics_router
from aiops_shared.tracing_config import instrument_app

from api.routes import plain_router, router
from core.config import SERVICE_NAME
from core.rag import _get_model
from core.worker import run_retry_worker, run_supervisor_queue_worker

configure_logging(SERVICE_NAME)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await asyncio.to_thread(_get_model)
        logger.info("embedding_model_warmed_up")
    except Exception as exc:  # noqa: BLE001
        logger.warning("embedding_model_warmup_failed", extra={"error": str(exc)})
    stop_event = asyncio.Event()
    queue_task = asyncio.create_task(run_supervisor_queue_worker(stop_event))
    retry_task = asyncio.create_task(run_retry_worker(stop_event))
    try:
        yield
    finally:
        stop_event.set()
        for task in (queue_task, retry_task):
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


app = FastAPI(title='supervisor-agent', version='3.0.0', lifespan=lifespan)
instrument_app(app, SERVICE_NAME)
app.include_router(plain_router)
app.include_router(router)
app.include_router(metrics_router())
