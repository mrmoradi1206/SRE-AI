from pathlib import Path


def test_ui_contains_dashboard_and_search_assets():
    root = Path(__file__).resolve().parents[1]
    app = (root / 'services' / 'nginx' / 'ui' / 'src' / 'App.jsx').read_text(encoding='utf-8')
    nginx_conf = (root / 'services' / 'nginx' / 'nginx.conf').read_text(encoding='utf-8')

    assert 'Recent alerts' in app
    assert 'Search summary, fingerprint, grouping key' in app
    assert 'LLM Settings' in app
    assert 'Test Workflow' in app
    assert 'Alertmanager integration' in app
    assert '/api/alertmanager/webhook' in app
    assert 'Mattermost delivery' in app
    assert '/report/integrations/mattermost' in app
    assert 'Why there is no history model' in app
    assert 'Test LLM call' in app
    assert 'Runtime API keys' in app
    assert 'location = /api/alertmanager/webhook' in nginx_conf
    assert 'location /api/config/' in nginx_conf
    assert 'location = /api/test-workflow' in nginx_conf
    assert 'location /api/' in nginx_conf
