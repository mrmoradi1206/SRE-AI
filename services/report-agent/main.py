from fastapi import FastAPI

from aiops_shared.database import init_engine
from aiops_shared.utils import configure_logging

from api.routes import router
from core.config import SERVICE_NAME

configure_logging(SERVICE_NAME)
init_engine()

app = FastAPI(title='Report Agent', version='1.0.0')
app.include_router(router)
