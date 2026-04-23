from aiops_shared.http_client import RetryableHTTPClient

from .config import MATTERMOST_WEBHOOK_URL, TEAMS_WEBHOOK_URL


class WebhookSender:
    def __init__(self, client: RetryableHTTPClient):
        self.client = client

    async def send(self, report: str, severity: str) -> dict:
        if MATTERMOST_WEBHOOK_URL:
            payload = {
                'text': f'Incident report ({severity})',
                'attachments': [{'color': '#FF0000' if severity == 'critical' else '#FFA500', 'text': report}],
            }
            await self.client.post(MATTERMOST_WEBHOOK_URL, json=payload)
            return {'channel': 'mattermost'}
        if TEAMS_WEBHOOK_URL:
            payload = {'text': report}
            await self.client.post(TEAMS_WEBHOOK_URL, json=payload)
            return {'channel': 'teams'}
        return {'channel': 'stdout'}
