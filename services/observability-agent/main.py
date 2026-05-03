from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    query: str = Field(default='up', max_length=500)
    datasource: str = Field(default='mock', max_length=80)
    incident_id: str | None = Field(default=None, max_length=120)


app = FastAPI(title='observability-agent', version='0.1.0')


@app.get('/health')
async def health() -> dict[str, Any]:
    return {
        'status': 'ok',
        'service': 'observability-agent',
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }


@app.post('/api/v1/query')
async def query_observability(payload: QueryRequest) -> dict[str, Any]:
    return {
        'status': 'ok',
        'datasource': payload.datasource,
        'query': payload.query,
        'incident_id': payload.incident_id,
        'result_type': 'mock',
        'summary': 'Dummy observability response for ReAct supervisor tool testing.',
        'series': [
            {'metric': 'mock_error_rate', 'value': 0.02, 'unit': 'ratio'},
            {'metric': 'mock_p95_latency_ms', 'value': 420, 'unit': 'ms'},
        ],
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }
