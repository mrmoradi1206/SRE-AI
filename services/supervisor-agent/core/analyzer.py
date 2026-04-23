import logging

from aiops_shared.http_client import RetryableHTTPClient
from aiops_shared.schemas import AnalysisResponse

from .config import HISTORY_AGENT_URL, REPORT_AGENT_URL
from .llm_client import OpenRouterClient

logger = logging.getLogger(__name__)


class AnalysisService:
    def __init__(self, http_client: RetryableHTTPClient):
        self.http_client = http_client
        self.llm_client = OpenRouterClient(http_client)

    async def analyze_incident(self, incident_id: str) -> dict:
        incident_data = await self.http_client.get(f'{HISTORY_AGENT_URL}/incidents/{incident_id}')
        incident_payload = incident_data.json()['incident']
        search = await self.http_client.get(
            f"{HISTORY_AGENT_URL}/alerts/search",
            params={'fingerprint': incident_payload['fingerprint'], 'hours': 24},
        )
        context = search.json()
        analysis = await self.llm_client.analyze(context)
        validated = AnalysisResponse.model_validate(analysis)
        await self.http_client.post(f'{HISTORY_AGENT_URL}/internal/incidents/{incident_id}/analysis', json=validated.model_dump())
        try:
            await self.http_client.post(f'{REPORT_AGENT_URL}/report', json={'incident_id': incident_id})
        except Exception:
            logger.exception('failed to trigger report agent', extra={'incident_id': incident_id})
        return validated.model_dump()
