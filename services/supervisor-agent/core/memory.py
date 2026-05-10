from __future__ import annotations

import json
import logging
import os
from typing import Any

import redis.asyncio as redis

from aiops_shared.utils import utcnow

from .config import REACT_MEMORY_TTL_SECONDS, REDIS_URL

logger = logging.getLogger(__name__)
WAR_ROOM_SESSION_TTL = int(os.getenv('WAR_ROOM_SESSION_TTL_SECONDS', str(4 * 3600)))


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


class WarRoomMemory:
    def __init__(self, redis_url: str = REDIS_URL) -> None:
        self.redis_url = redis_url
        self._client: redis.Redis | None = None

    def _get_client(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.from_url(self.redis_url, decode_responses=True)
        return self._client

    def _key(self, session_id: str) -> str:
        return f'sre-ai:war-room:session:{session_id}'

    async def append(self, session_id: str, role: str, content: str, extras: dict | None = None) -> None:
        entry = {'role': role, 'content': content, 'at': utcnow().isoformat()}
        if extras:
            entry.update(extras)
        try:
            key = self._key(session_id)
            client = self._get_client()
            await client.rpush(key, json.dumps(entry, default=str))
            await client.expire(key, WAR_ROOM_SESSION_TTL)
        except Exception as exc:  # noqa: BLE001
            logger.warning('war_room_memory_write_failed', extra={'error_type': type(exc).__name__})

    async def get_history(self, session_id: str, limit: int = 20) -> list[dict]:
        try:
            entries = await self._get_client().lrange(self._key(session_id), -limit, -1)
            return [json.loads(entry) for entry in entries]
        except Exception as exc:  # noqa: BLE001
            logger.warning('war_room_memory_read_failed', extra={'error_type': type(exc).__name__})
            return []
