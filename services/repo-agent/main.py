from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, Query
import gitlab

from integrations.gitlab_client import GITLAB_TOKEN, GITLAB_URL, recent_changes

app = FastAPI(title='repo-agent', version='0.1.0')


@app.get('/health')
async def health() -> dict[str, Any]:
    return {
        'status': 'ok',
        'service': 'repo-agent',
        'gitlab_url': GITLAB_URL,
        'gitlab_token_configured': bool(GITLAB_TOKEN),
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }


@app.get('/api/v1/repo/changes')
async def repo_changes(
    project_id: str | None = Query(default=None, max_length=240),
    ref: str | None = Query(default=None, max_length=120),
    days: int = Query(default=7, ge=1, le=90),
    limit: int = Query(default=10, ge=1, le=50),
) -> dict[str, Any]:
    try:
        return recent_changes(project_id=project_id, ref=ref, days=days, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except gitlab.GitlabError as exc:
        raise HTTPException(status_code=502, detail=f'gitlab request failed: {exc}') from exc
