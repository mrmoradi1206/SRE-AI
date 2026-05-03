from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Query
from pydantic import BaseModel, Field
import gitlab

from aiops_shared.llm_client import LLMError, run_llm
from aiops_shared.llm_config import LLMConfigError, get_agent_llm_config, get_agent_system_prompt
from integrations.config import load_config, public_config, save_config
from integrations.gitlab_client import recent_changes


class GitLabConfig(BaseModel):
    url: str = Field(default='https://gitlab.com', max_length=500)
    token: str | None = Field(default=None, max_length=500)
    default_project: str = Field(default='', max_length=240)


class RepoConfig(BaseModel):
    gitlab: GitLabConfig = Field(default_factory=GitLabConfig)


class RepoAnalyzeRequest(BaseModel):
    incident_id: str | None = Field(default=None, max_length=120)
    incident: dict[str, Any] = Field(default_factory=dict)
    alerts: list[dict[str, Any]] = Field(default_factory=list)
    service: str | None = Field(default=None, max_length=160)
    project_id: str | None = Field(default=None, max_length=240)
    ref: str | None = Field(default=None, max_length=120)
    days: int = Field(default=7, ge=1, le=90)
    limit: int = Field(default=10, ge=1, le=50)


app = FastAPI(title='repo-agent', version='0.3.0')


def _gitlab_config() -> dict[str, Any]:
    return load_config().get('gitlab', {})


def _safe_json(value: Any, limit: int = 16000) -> str:
    import json

    return json.dumps(value, default=str)[:limit]


def _fetch_changes(payload: RepoAnalyzeRequest | None = None, **kwargs: Any) -> dict[str, Any]:
    gitlab_config = _gitlab_config()
    project_id = kwargs.get('project_id') if payload is None else payload.project_id
    ref = kwargs.get('ref') if payload is None else payload.ref
    days = kwargs.get('days', 7) if payload is None else payload.days
    limit = kwargs.get('limit', 10) if payload is None else payload.limit
    return recent_changes(
        project_id=project_id,
        ref=ref,
        days=days,
        limit=limit,
        gitlab_url=gitlab_config.get('url'),
        token=gitlab_config.get('token'),
        default_project=gitlab_config.get('default_project'),
    )


@app.get('/health')
async def health() -> dict[str, Any]:
    gitlab_config = _gitlab_config()
    return {
        'status': 'ok',
        'service': 'repo-agent',
        'llm_enabled': True,
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


@app.post('/api/v1/analyze')
async def analyze_repo(payload: RepoAnalyzeRequest) -> dict[str, Any]:
    try:
        changes = _fetch_changes(payload)
    except (ValueError, gitlab.GitlabError) as exc:
        changes = {'status': 'error', 'error': str(exc), 'commits': [], 'merge_requests': []}
    try:
        selection = get_agent_llm_config('repo')
        response = await run_llm(
            selection['provider'],
            selection['model'],
            [
                {'role': 'system', 'content': get_agent_system_prompt('repo')},
                {'role': 'user', 'content': _safe_json({'task': 'Analyze recent repository changes against the incident and respond with strict JSON.', 'request': payload.model_dump(), 'changes': changes})},
            ],
            temperature=0.1,
            max_tokens=700,
        )
        return {'status': 'ok', 'agent': 'repo-agent', 'provider': response['provider'], 'model': response['model'], 'analysis': response['content'], 'changes': changes, 'llm_trace': response.get('trace')}
    except (LLMConfigError, LLMError) as exc:
        return {'status': 'fallback', 'agent': 'repo-agent', 'analysis': 'LLM analysis unavailable; returning GitLab change evidence only.', 'error': str(exc), 'changes': changes}


@app.get('/api/v1/repo/changes')
async def repo_changes(
    project_id: str | None = Query(default=None, max_length=240),
    ref: str | None = Query(default=None, max_length=120),
    days: int = Query(default=7, ge=1, le=90),
    limit: int = Query(default=10, ge=1, le=50),
) -> dict[str, Any]:
    try:
        return _fetch_changes(project_id=project_id, ref=ref, days=days, limit=limit)
    except ValueError as exc:
        return {'status': 'error', 'error': str(exc), 'commits': [], 'merge_requests': []}
    except gitlab.GitlabError as exc:
        return {'status': 'error', 'error': f'gitlab request failed: {exc}', 'commits': [], 'merge_requests': []}
