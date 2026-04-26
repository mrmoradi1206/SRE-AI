from aiops_shared.http_client import AsyncServiceClient


class NoopSender:
    def __init__(self, client: AsyncServiceClient) -> None:
        self.client = client

    async def send(self, *_args, **_kwargs) -> dict:
        return {'channel': 'none', 'status': 'stored-only'}
