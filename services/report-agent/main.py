from fastapi import FastAPI

from aiops_shared.logging_config import configure_logging
from aiops_shared.metrics import metrics_router
from aiops_shared.tracing_config import instrument_app

from api.routes import router
from core.config import SERVICE_NAME

configure_logging(SERVICE_NAME)

app = FastAPI(title='report-agent', version='3.0.0')
instrument_app(app, SERVICE_NAME)
app.include_router(router)
app.include_router(metrics_router())
