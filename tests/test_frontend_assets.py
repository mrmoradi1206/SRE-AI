from pathlib import Path


def test_ui_contains_dashboard_and_search_assets():
    root = Path(__file__).resolve().parents[1]
    app = (root / 'services' / 'nginx' / 'ui' / 'src' / 'App.jsx').read_text(encoding='utf-8')
    nginx_conf = (root / 'services' / 'nginx' / 'nginx.conf').read_text(encoding='utf-8')

    assert 'Recent alerts' in app
    assert 'Search summary, fingerprint, grouping key' in app
    assert 'location /api/' in nginx_conf
