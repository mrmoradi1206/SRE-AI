from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import gitlab

GITLAB_URL = os.getenv('GITLAB_URL', 'https://gitlab.com')
GITLAB_TOKEN = os.getenv('GITLAB_TOKEN', '')
DEFAULT_PROJECT = os.getenv('GITLAB_PROJECT_ID', '')


def _client(gitlab_url: str | None = None, token: str | None = None) -> gitlab.Gitlab:
    return gitlab.Gitlab(gitlab_url or GITLAB_URL, private_token=(token if token is not None else GITLAB_TOKEN) or None, timeout=10)


def _project_identifier(project_id: str | None, default_project: str | None = None) -> str:
    project = project_id or default_project or DEFAULT_PROJECT
    if not project:
        raise ValueError('GITLAB_PROJECT_ID is not configured and no project_id was provided')
    return project


def recent_changes(
    project_id: str | None = None,
    ref: str | None = None,
    days: int = 7,
    limit: int = 10,
    gitlab_url: str | None = None,
    token: str | None = None,
    default_project: str | None = None,
) -> dict[str, Any]:
    project_name = _project_identifier(project_id, default_project)
    client = _client(gitlab_url=gitlab_url, token=token)
    project = client.projects.get(project_name)
    since = (datetime.now(timezone.utc) - timedelta(days=max(1, days))).isoformat()

    commit_kwargs: dict[str, Any] = {'since': since, 'per_page': min(limit, 50), 'get_all': False}
    if ref:
        commit_kwargs['ref_name'] = ref
    commits = project.commits.list(**commit_kwargs)
    merge_requests = project.mergerequests.list(updated_after=since, per_page=min(limit, 50), get_all=False)

    return {
        'status': 'ok',
        'gitlab_url': gitlab_url or GITLAB_URL,
        'project_id': project_name,
        'ref': ref,
        'days': days,
        'commits': [
            {
                'id': item.id,
                'short_id': getattr(item, 'short_id', item.id[:8]),
                'title': getattr(item, 'title', ''),
                'author_name': getattr(item, 'author_name', ''),
                'created_at': getattr(item, 'created_at', None),
                'web_url': getattr(item, 'web_url', None),
            }
            for item in commits
        ],
        'merge_requests': [
            {
                'iid': item.iid,
                'title': item.title,
                'state': item.state,
                'author': getattr(getattr(item, 'author', None), 'get', lambda *_: None)('name') if isinstance(getattr(item, 'author', None), dict) else None,
                'updated_at': item.updated_at,
                'web_url': item.web_url,
            }
            for item in merge_requests
        ],
    }
