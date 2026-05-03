from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Query
from pydantic import BaseModel, Field
import gitlab

from integrations.config import load_config, public_config, save_config
from integrations.gitlab_client import recent_changes


class GitLabConfig(BaseModel):
    url: str = Field(default='https://gitlab.com', max_length=500)
    token: str | None = Field(default=None, max_length=500)
    default_project: str = Field(default='', max_length=240)


class RepoConfig(BaseModel):
    gitlab: GitLabConfig = Field(default_factory=GitLabConfig)


app = FastAPI(title='repo-agent', version='0.2.0')


def _gitlab_config() -> dict[str, Any]:
    return load_config().get('gitlab', {})


@app.get('/health')
async def health() -> dict[str, Any]:
    gitlab_config = _gitlab_config()
    return {
        'status': 'ok',
        'service': 'repo-agent',
        'gitlab_url': gitlab_config.get('url', 'https://gitlab.com'),
        'gitlab_token_configured': bool(gitlab_config.get('token')),
        'gitlab_project_configured': bool(gitlab_config.get('default_project')),
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }


@app.get('/api/v1/config')
async def get_config() -> dict[str, Any]:
    return public_config()


@app.put('/api/v1/config')
async def put_config(payload: RepoConfig) -> dict[str, Any]:
    return public_config(save_config(payload.model_dump()))


@app.post('/api/v1/test/gitlab')
async def test_gitlab() -> dict[str, Any]:
    gitlab_config = _gitlab_config()
    project = gitlab_config.get('default_project') or ''
    if not project:
        return {'ok': False, 'configured': False, 'error': 'Set a GitLab project ID or path before testing.'}
    try:
        data = recent_changes(
            project_id=project,
            days=1,
            limit=1,
            gitlab_url=gitlab_config.get('url'),
            token=gitlab_config.get('token'),
            default_project=gitlab_config.get('default_project'),
        )
        return {'ok': True, 'configured': True, 'gitlab_url': gitlab_config.get('url'), 'project_id': project, 'data': data}
    except (ValueError, gitlab.GitlabError) as exc:
        return {'ok': False, 'configured': True, 'gitlab_url': gitlab_config.get('url'), 'project_id': project, 'error': str(exc)}


@app.get('/api/v1/repo/changes')
async def repo_changes(
    project_id: str | None = Query(default=None, max_length=240),
    ref: str | None = Query(default=None, max_length=120),
    days: int = Query(default=7, ge=1, le=90),
    limit: int = Query(default=10, ge=1, le=50),
) -> dict[str, Any]:
    gitlab_config = _gitlab_config()
    try:
        return recent_changes(
            project_id=project_id,
            ref=ref,
            days=days,
            limit=limit,
            gitlab_url=gitlab_config.get('url'),
            token=gitlab_config.get('token'),
            default_project=gitlab_config.get('default_project'),
        )
    except ValueError as exc:
        return {'status': 'error', 'error': str(exc), 'commits': [], 'merge_requests': []}
    except gitlab.GitlabError as exc:
        return {'status': 'error', 'error': f'gitlab request failed: {exc}', 'commits': [], 'merge_requests': []}
