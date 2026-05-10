from __future__ import annotations

import logging
import threading
from typing import Any
from uuid import UUID

from fastembed import TextEmbedding
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)
EMBEDDING_DIMENSIONS = 384
_model: TextEmbedding | None = None
_model_lock = threading.Lock()


def _embedding_text(*parts: Any) -> str:
    return ' | '.join(str(part or '') for part in parts if part is not None)[:12000]


def _get_model() -> TextEmbedding:
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                _model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
    return _model


def embed_text(value: str) -> list[float]:
    model = _get_model()
    embeddings = list(model.embed([value]))
    return [round(float(x), 6) for x in embeddings[0].tolist()]


def vector_literal(vector: list[float]) -> str:
    return '[' + ','.join(str(float(item)) for item in vector) + ']'


class IncidentRAG:
    async def save_resolved_incident(
        self,
        session: AsyncSession,
        *,
        incident_id: str | UUID,
        summary: str,
        root_cause: str,
        resolution: str,
        service: str | None = None,
        severity: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        embedding = vector_literal(embed_text(_embedding_text(summary, root_cause, resolution, service, severity)))
        result = await session.execute(
            text(
                """
                INSERT INTO incident_knowledge
                    (incident_id, service, severity, summary, root_cause, resolution, metadata, embedding)
                VALUES
                    (:incident_id, :service, :severity, :summary, :root_cause, :resolution, CAST(:metadata AS jsonb), CAST(:embedding AS vector))
                RETURNING id, created_at
                """
            ),
            {
                'incident_id': str(incident_id),
                'service': service,
                'severity': severity,
                'summary': summary,
                'root_cause': root_cause,
                'resolution': resolution,
                'metadata': __import__('json').dumps(metadata or {}),
                'embedding': embedding,
            },
        )
        row = result.mappings().one()
        return {'id': str(row['id']), 'incident_id': str(incident_id), 'created_at': row['created_at'].isoformat()}

    async def retrieve_similar_incidents(
        self,
        session: AsyncSession,
        *,
        query_text: str,
        incident_id: str | UUID | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        embedding = vector_literal(embed_text(query_text))
        params = {'embedding': embedding, 'limit': max(1, min(limit, 10))}
        where_clause = ''
        if incident_id:
            params['incident_id'] = str(incident_id)
            where_clause = 'WHERE incident_id::text <> :incident_id'
        result = await session.execute(
            text(
                f"""
                SELECT id, incident_id, service, severity, summary, root_cause, resolution, metadata, created_at,
                       1 - (embedding <=> CAST(:embedding AS vector)) AS score
                FROM incident_knowledge
                {where_clause}
                ORDER BY embedding <=> CAST(:embedding AS vector)
                LIMIT :limit
                """
            ),
            params,
        )
        return [
            {
                'id': str(row['id']),
                'incident_id': str(row['incident_id']),
                'service': row['service'],
                'severity': row['severity'],
                'summary': row['summary'],
                'root_cause': row['root_cause'],
                'resolution': row['resolution'],
                'metadata': row['metadata'] or {},
                'created_at': row['created_at'].isoformat() if row['created_at'] else None,
                'score': round(float(row['score'] or 0.0), 4),
            }
            for row in result.mappings().all()
        ]
