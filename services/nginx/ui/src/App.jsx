import { useEffect, useMemo, useState } from 'react';
import { Link, NavLink, Route, Routes, useNavigate, useParams, useSearchParams } from 'react-router-dom';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api';

async function apiFetch(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed: ${response.status}`);
  }
  return response.json();
}

function StatusChip({ status }) {
  const normalized = (status || 'unknown').toLowerCase();
  return <span className={`status-chip status-${normalized}`}>{normalized}</span>;
}

function SeverityChip({ severity }) {
  const normalized = (severity || 'unknown').toLowerCase();
  return <span className={`severity-chip severity-${normalized}`}>{normalized}</span>;
}

function Shell({ children }) {
  return (
    <div className="shell">
      <aside className="sidebar">
        <div>
          <p className="eyebrow">SRE-AI</p>
          <h1>Control Room</h1>
          <p className="sidebar-copy">History keeps the append-only signal, supervisor manages lifecycle, report builds operator context.</p>
        </div>
        <nav>
          <NavLink to="/">Dashboard</NavLink>
          <NavLink to="/incidents">Incidents</NavLink>
          <NavLink to="/agents">Agents</NavLink>
          <NavLink to="/settings">Settings</NavLink>
        </nav>
      </aside>
      <main className="content">
        <header className="topbar">
          <div>
            <p className="eyebrow">Operational overview</p>
            <h2>AIOps incident dashboard</h2>
          </div>
          <span className="topbar-note">Searchable timeline, safe pagination, provider-aware AI actions</span>
        </header>
        {children}
      </main>
    </div>
  );
}

function MetricCard({ title, value, subtitle }) {
  return (
    <div className="metric-card panel">
      <p className="eyebrow">Metric</p>
      <h3>{value}</h3>
      <p>{title}</p>
      {subtitle ? <small>{subtitle}</small> : null}
    </div>
  );
}

function DashboardPage() {
  const [stats, setStats] = useState(null);
  const [incidents, setIncidents] = useState([]);
  const [recentAlerts, setRecentAlerts] = useState([]);
  const [error, setError] = useState('');

  useEffect(() => {
    Promise.all([
      apiFetch('/history/dashboard'),
      apiFetch('/history/incidents?page=1&page_size=6'),
      apiFetch('/history/alerts/recent?hours=24&limit=6'),
    ])
      .then(([dashboard, incidentList, recent]) => {
        setStats(dashboard);
        setIncidents(incidentList.items || []);
        setRecentAlerts(recent.items || []);
      })
      .catch((err) => setError(err.message));
  }, []);

  return (
    <section className="page-grid">
      <div className="hero-card span-2">
        <p className="eyebrow">System pulse</p>
        <h3>Recent signal and incident posture</h3>
        <p>
          The dashboard surfaces append-only alert history, current lifecycle state, and recent alert activity without
          unbounded queries.
        </p>
      </div>
      <MetricCard title="Open incidents" value={stats?.open_incidents_count ?? '--'} />
      <MetricCard title="Investigating" value={stats?.investigating_incidents_count ?? '--'} />
      <MetricCard title="Mitigating" value={stats?.mitigating_incidents_count ?? '--'} />
      <MetricCard title="Resolved in 24h" value={stats?.resolved_last_24h ?? '--'} />

      <div className="panel">
        <div className="panel-header">
          <h3>Recent incidents</h3>
          <Link to="/incidents">See all</Link>
        </div>
        {error ? <p className="error-text">{error}</p> : null}
        <div className="incident-list compact">
          {incidents.map((incident) => (
            <Link key={incident.id} className="incident-row" to={`/incidents/${incident.id}`}>
              <div>
                <strong>{incident.summary || incident.fingerprint.slice(0, 14)}</strong>
                <p>{new Date(incident.last_seen_at).toLocaleString()}</p>
              </div>
              <div className="incident-meta">
                <SeverityChip severity={incident.severity} />
                <StatusChip status={incident.status} />
              </div>
            </Link>
          ))}
        </div>
      </div>

      <div className="panel">
        <div className="panel-header">
          <h3>Recent alerts</h3>
          <span>24h summary</span>
        </div>
        <div className="stack-list">
          {recentAlerts.map((alert) => (
            <article key={alert.id} className="stack-item">
              <div className="incident-meta">
                <SeverityChip severity={alert.severity} />
                <span>{alert.source || 'unknown source'}</span>
              </div>
              <strong>{alert.event_key}</strong>
              <p>{new Date(alert.created_at).toLocaleString()}</p>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}

function IncidentsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [data, setData] = useState({ items: [], total: 0, page: 1, page_size: 20 });
  const [error, setError] = useState('');

  const statusFilter = searchParams.get('status') || '';
  const query = searchParams.get('query') || '';

  useEffect(() => {
    const params = new URLSearchParams();
    if (statusFilter) params.set('status', statusFilter);
    if (query) params.set('query', query);
    params.set('page', '1');
    params.set('page_size', '20');
    apiFetch(`/history/incidents?${params.toString()}`)
      .then(setData)
      .catch((err) => setError(err.message));
  }, [statusFilter, query]);

  return (
    <section className="panel">
      <div className="panel-header">
        <h3>Incidents</h3>
        <span>{data.total} total</span>
      </div>
      <div className="toolbar">
        <input
          placeholder="Search summary, fingerprint, grouping key"
          value={query}
          onChange={(event) => setSearchParams((current) => {
            const next = new URLSearchParams(current);
            if (event.target.value) next.set('query', event.target.value);
            else next.delete('query');
            return next;
          })}
        />
        <select
          value={statusFilter}
          onChange={(event) => setSearchParams((current) => {
            const next = new URLSearchParams(current);
            if (event.target.value) next.set('status', event.target.value);
            else next.delete('status');
            return next;
          })}
        >
          <option value="">All statuses</option>
          <option value="open">Open</option>
          <option value="investigating">Investigating</option>
          <option value="mitigating">Mitigating</option>
          <option value="resolved">Resolved</option>
          <option value="closed">Closed</option>
        </select>
      </div>
      {error ? <p className="error-text">{error}</p> : null}
      <div className="incident-list">
        {data.items.map((incident) => (
          <Link key={incident.id} className="incident-row" to={`/incidents/${incident.id}`}>
            <div>
              <strong>{incident.summary || incident.fingerprint}</strong>
              <p>{incident.grouping_key.slice(0, 18)}…</p>
            </div>
            <div className="incident-meta">
              <span>{incident.alert_count} alerts</span>
              <SeverityChip severity={incident.severity} />
              <StatusChip status={incident.status} />
            </div>
          </Link>
        ))}
      </div>
    </section>
  );
}

function IncidentDetailPage() {
  const { incidentId } = useParams();
  const navigate = useNavigate();
  const [incident, setIncident] = useState(null);
  const [report, setReport] = useState(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const load = async () => {
    try {
      const detail = await apiFetch(`/history/incidents/${incidentId}`);
      setIncident(detail);
      try {
        const latestReport = await apiFetch(`/report/${incidentId}`);
        setReport(latestReport);
      } catch {
        setReport(null);
      }
    } catch (err) {
      setError(err.message);
    }
  };

  useEffect(() => {
    load();
  }, [incidentId]);

  const act = async (path, body) => {
    setBusy(true);
    setMessage('');
    setError('');
    try {
      const result = await apiFetch(path, { method: 'POST', body: JSON.stringify(body) });
      setMessage(JSON.stringify(result, null, 2));
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const correlationNodes = useMemo(() => {
    if (!incident) return [];
    return incident.timeline.slice(0, 10).map((event) => ({
      id: event.event_id,
      label: `${event.actor}:${event.event_type}`,
    }));
  }, [incident]);

  if (!incident) {
    return <section className="panel">{error ? <p className="error-text">{error}</p> : <p>Loading incident...</p>}</section>;
  }

  return (
    <section className="page-grid detail-grid">
      <div className="panel span-2">
        <div className="panel-header">
          <div>
            <p className="eyebrow">Incident detail</p>
            <h3>{incident.summary || incident.fingerprint}</h3>
          </div>
          <div className="incident-meta">
            <SeverityChip severity={incident.severity} />
            <StatusChip status={incident.status} />
          </div>
        </div>
        <div className="detail-meta-grid">
          <div><strong>Fingerprint</strong><p>{incident.fingerprint}</p></div>
          <div><strong>Grouping key</strong><p>{incident.grouping_key}</p></div>
          <div><strong>First seen</strong><p>{new Date(incident.first_seen_at).toLocaleString()}</p></div>
          <div><strong>Last seen</strong><p>{new Date(incident.last_seen_at).toLocaleString()}</p></div>
          <div><strong>SLA deadline</strong><p>{incident.sla_deadline ? new Date(incident.sla_deadline).toLocaleString() : 'n/a'}</p></div>
          <div><strong>MTTR</strong><p>{incident.mttr_seconds ?? 'n/a'}s</p></div>
        </div>
        <div className="action-row wrap">
          <button disabled={busy} onClick={() => act('/supervisor/analyze', { incident_id: incident.id })}>Ask Supervisor</button>
          <button disabled={busy} onClick={() => act('/supervisor/investigate', { incident_id: incident.id, reason: 'Investigate from UI' })}>Investigate</button>
          <button disabled={busy} onClick={() => act('/supervisor/mitigate', { incident_id: incident.id, reason: 'Mitigate from UI' })}>Mitigate</button>
          <button disabled={busy} onClick={() => act('/supervisor/resolve', { incident_id: incident.id, reason: 'Resolve from UI' })}>Resolve</button>
          <button disabled={busy} onClick={() => act(`/report/${incident.id}`, {})}>Generate Report</button>
          <button className="ghost-button" onClick={() => navigate('/incidents')}>Back</button>
        </div>
        {message ? <pre>{message}</pre> : null}
        {error ? <p className="error-text">{error}</p> : null}
      </div>

      <div className="panel">
        <div className="panel-header">
          <h3>Raw alert samples</h3>
          <span>{incident.alerts.length} loaded</span>
        </div>
        <div className="stack-list">
          {incident.alerts.map((alert) => (
            <article key={alert.id} className="stack-item">
              <div className="incident-meta">
                <SeverityChip severity={alert.severity} />
                <span>{alert.source || 'unknown source'}</span>
              </div>
              <strong>{alert.event_key}</strong>
              <p>{new Date(alert.created_at).toLocaleString()}</p>
              <pre>{JSON.stringify(alert.payload, null, 2)}</pre>
            </article>
          ))}
        </div>
      </div>

      <div className="panel">
        <div className="panel-header">
          <h3>Correlation stub</h3>
          <span>{correlationNodes.length} nodes</span>
        </div>
        <div className="stack-list">
          {correlationNodes.map((node) => (
            <article key={node.id} className="stack-item">
              <strong>{node.label}</strong>
              <p>{node.id}</p>
            </article>
          ))}
        </div>
      </div>

      <div className="panel span-2">
        <div className="panel-header">
          <h3>Timeline</h3>
          <span>{incident.timeline.length} events</span>
        </div>
        <div className="timeline-grid">
          {incident.timeline.map((event) => (
            <article key={event.event_id} className="timeline-item">
              <div className="timeline-meta">
                <strong>{event.event_type}</strong>
                <span>{event.actor}</span>
                <span>{new Date(event.created_at).toLocaleString()}</span>
              </div>
              <pre>{JSON.stringify({ metadata: event.metadata, payload: event.payload }, null, 2)}</pre>
            </article>
          ))}
        </div>
      </div>

      <div className="panel span-2">
        <div className="panel-header">
          <h3>Latest report</h3>
          <span>{report ? 'stored' : 'not generated yet'}</span>
        </div>
        {report ? <pre>{report.report_event.report}</pre> : <p>No report event exists for this incident yet.</p>}
      </div>
    </section>
  );
}

function AgentsPage() {
  const [health, setHealth] = useState([]);
  const [error, setError] = useState('');

  useEffect(() => {
    Promise.all([apiFetch('/history/health'), apiFetch('/report/health'), apiFetch('/supervisor/health')])
      .then((results) => setHealth(results))
      .catch((err) => setError(err.message));
  }, []);

  return (
    <section className="panel">
      <div className="panel-header">
        <h3>Agent health</h3>
      </div>
      {error ? <p className="error-text">{error}</p> : null}
      <div className="health-grid">
        {health.map((item) => (
          <article key={item.service} className="health-card">
            <p className="eyebrow">{item.service}</p>
            <h4>{item.status}</h4>
            <p>Database: {item.database}</p>
            <p>Readiness: {item.readiness}</p>
            <p>{item.timestamp}</p>
          </article>
        ))}
      </div>
    </section>
  );
}

function SettingsPage() {
  const [form, setForm] = useState({ provider: 'openrouter', model: 'openai/gpt-4o-mini', api_key: '', extra_config: '{}' });
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    apiFetch('/supervisor/settings')
      .then((settings) => {
        setForm({
          provider: settings.provider || 'openrouter',
          model: settings.model || 'openai/gpt-4o-mini',
          api_key: settings.api_key || '',
          extra_config: JSON.stringify(settings.extra_config || {}, null, 2),
        });
      })
      .catch((err) => setError(err.message));
  }, []);

  const save = async (event) => {
    event.preventDefault();
    setMessage('');
    setError('');
    try {
      const payload = {
        provider: form.provider,
        model: form.model,
        api_key: form.api_key,
        extra_config: JSON.parse(form.extra_config || '{}'),
      };
      const result = await apiFetch('/supervisor/settings', { method: 'PUT', body: JSON.stringify(payload) });
      setMessage(`Saved settings for ${result.provider} / ${result.model}`);
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <section className="panel">
      <div className="panel-header">
        <h3>AI settings</h3>
        <span>Stored in postgres</span>
      </div>
      <form className="settings-form" onSubmit={save}>
        <label>
          Provider
          <select value={form.provider} onChange={(event) => setForm({ ...form, provider: event.target.value })}>
            <option value="openrouter">OpenRouter</option>
            <option value="gateway">Snapp Gateway</option>
          </select>
        </label>
        <label>
          Model
          <input value={form.model} onChange={(event) => setForm({ ...form, model: event.target.value })} />
        </label>
        <label>
          API key
          <input type="password" value={form.api_key} onChange={(event) => setForm({ ...form, api_key: event.target.value })} />
        </label>
        <label>
          Extra config
          <textarea rows="8" value={form.extra_config} onChange={(event) => setForm({ ...form, extra_config: event.target.value })} />
        </label>
        <div className="action-row">
          <button type="submit">Save settings</button>
        </div>
      </form>
      {message ? <p className="success-text">{message}</p> : null}
      {error ? <p className="error-text">{error}</p> : null}
    </section>
  );
}

export default function App() {
  return (
    <Shell>
      <Routes>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/incidents" element={<IncidentsPage />} />
        <Route path="/incidents/:incidentId" element={<IncidentDetailPage />} />
        <Route path="/agents" element={<AgentsPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Routes>
    </Shell>
  );
}
