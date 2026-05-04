from fastapi import FastAPI
from contextlib import asynccontextmanager

from aiops_shared.logging_config import configure_logging
from aiops_shared.metrics import metrics_router
from aiops_shared.tracing_config import instrument_app

from api.routes import router
from core.config import SERVICE_NAME
from core.alertmanager_poll import start_alertmanager_poller, stop_alertmanager_poller

configure_logging(SERVICE_NAME)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await start_alertmanager_poller()
    try:
        yield
    finally:
        await stop_alertmanager_poller()


app = FastAPI(title='history-agent', version='3.1.0', lifespan=lifespan)
instrument_app(app, SERVICE_NAME)
app.include_router(router)
app.include_router(metrics_router())
