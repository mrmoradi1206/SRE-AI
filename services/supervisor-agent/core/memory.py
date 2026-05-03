from __future__ import annotations

import json
import logging
from typing import Any

import redis.asyncio as redis

from .config import REACT_MEMORY_TTL_SECONDS, REDIS_URL

logger = logging.getLogger(__name__)


class ReActMemory:
    def __init__(self, redis_url: str = REDIS_URL, ttl_seconds: int = REACT_MEMORY_TTL_SECONDS) -> None:
        self.redis_url = redis_url
        self.ttl_seconds = ttl_seconds
        self._client: redis.Redis | None = None

    def _key(self, incident_id: str) -> str:
        return f'sre-ai:supervisor:react:{incident_id}'

    def _get_client(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.from_url(self.redis_url, decode_responses=True)
        return self._client

    async def get_history(self, incident_id: str, limit: int = 20) -> list[dict[str, Any]]:
        try:
            start = -max(1, limit)
            entries = await self._get_client().lrange(self._key(incident_id), start, -1)
            return [json.loads(entry) for entry in entries]
        except Exception as exc:  # noqa: BLE001
            logger.warning('react_memory_read_failed', extra={'incident_id': incident_id, 'error_type': type(exc).__name__})
            return []

    async def append(self, incident_id: str, entry: dict[str, Any]) -> None:
        try:
            payload = json.dumps(entry, default=str, separators=(',', ':'))
            key = self._key(incident_id)
            client = self._get_client()
            await client.rpush(key, payload)
            await client.expire(key, self.ttl_seconds)
        except Exception as exc:  # noqa: BLE001
            logger.warning('react_memory_write_failed', extra={'incident_id': incident_id, 'error_type': type(exc).__name__})
