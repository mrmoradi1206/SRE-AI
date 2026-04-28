import { useEffect, useMemo, useState } from 'react';
import { Link, NavLink, Route, Routes, useNavigate, useParams, useSearchParams } from 'react-router-dom';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api';
const PROVIDER_LABELS = {
  openrouter: 'OpenRouter',
  llmgateway: 'LLM Gateway',
  gapgpt: 'GapGPT',
};
const SYSTEM_PROMPTS = {
  history: 'Ingest alerts, deduplicate by fingerprint, persist append-only incident history, and expose query APIs.',
  supervisor: 'Analyze trusted incident context and untrusted alert payloads, then produce structured lifecycle guidance.',
  report: 'Turn structured incident analysis into a concise human-readable SRE report for operators.',
};
const SAMPLE_ALERT = {
  source: 'ui-test',
  severity: 'critical',
  summary: 'Checkout latency is above SLO',
  labels: {
    alertname: 'HighCheckoutLatency',
    service: 'checkout',
    instance: 'checkout-api-1',
    namespace: 'payments',
  },
  annotations: {
    description: 'p95 latency has exceeded 2s for 10 minutes.',
  },
};
const NAV_ITEMS = [
  { to: '/', label: 'Dashboard', hint: 'Command overview' },
  { to: '/incidents', label: 'Incidents', hint: 'Triage queue' },
  { to: '/workflow', label: 'Test Workflow', hint: 'End-to-end drill' },
  { to: '/agents', label: 'Agents', hint: 'Service readiness' },
  { to: '/settings', label: 'LLM Settings', hint: 'Model routing' },
];
const OPS_SIGNALS = [
  ['99.95%', 'target SLO'],
  ['< 4h', 'default SLA'],
  ['3', 'AI agents'],
];

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

function providerLabel(provider) {
  return PROVIDER_LABELS[provider] || provider;
}

function formatDate(value) {
  if (!value) return 'not available';
  return new Date(value).toLocaleString();
}

function EmptyState({ title, copy }) {
  return (
    <div className="empty-state">
      <span aria-hidden="true">+</span>
      <strong>{title}</strong>
      <p>{copy}</p>
    </div>
  );
}

function JsonBlock({ data, title = 'JSON' }) {
  return (
    <details className="json-viewer" open>
      <summary>{title}</summary>
      <pre>{typeof data === 'string' ? data : JSON.stringify(data, null, 2)}</pre>
    </details>
  );
}

function ProviderBadge({ provider }) {
  return <span className="provider-badge">{providerLabel(provider || 'unknown')}</span>;
}

function ModelBadge({ model }) {
  return <span className="model-badge">{model || 'model not selected'}</span>;
}

function WorkflowRail({ trace = [] }) {
  const statusFor = (name) => trace.find((step) => step.name === name)?.status || 'pending';
  return (
    <div className="workflow-rail">
      {[
        ['history.ingest', 'Alert'],
        ['history.context', 'History'],
        ['supervisor.analyze', 'Supervisor'],
        ['report.generate', 'Report'],
      ].map(([name, label]) => (
        <div key={name} className={`workflow-node node-${statusFor(name)}`}>
          <span>{label}</span>
          <small>{statusFor(name)}</small>
        </div>
      ))}
    </div>
  );
}

function SeverityChip({ severity }) {
  const normalized = (severity || 'unknown').toLowerCase();
  return <span className={`severity-chip severity-${normalized}`}>{normalized}</span>;
}

function Shell({ children }) {
  const [theme, setTheme] = useState(() => localStorage.getItem('sre-ai-theme') || 'light');

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem('sre-ai-theme', theme);
  }, [theme]);

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand-card">
          <div className="brand-mark">SA</div>
          <div>
            <p className="eyebrow">SRE-AI</p>
            <h1>Control Room</h1>
          </div>
          <p className="sidebar-copy">A production-minded command surface for alert history, AI-assisted triage, and operator reporting.</p>
        </div>
        <nav aria-label="Primary navigation">
          {NAV_ITEMS.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.to === '/'}>
              <span>{item.label}</span>
              <small>{item.hint}</small>
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-status">
          <span className="live-dot" />
          <div>
            <strong>Live operations</strong>
            <p>History, supervisor, and reports routed through nginx</p>
          </div>
        </div>
      </aside>
      <main className="content">
        <header className="topbar">
          <div>
            <p className="eyebrow">Operational overview</p>
            <h2>AIOps incident dashboard</h2>
          </div>
          <div className="topbar-actions">
            <span className="topbar-note">Searchable timelines, safe pagination, provider-aware AI actions</span>
            <button type="button" className="ghost-button" onClick={() => setTheme(theme === 'light' ? 'dark' : 'light')}>
              {theme === 'light' ? 'Dark mode' : 'Light mode'}
            </button>
          </div>
        </header>
        {children}
      </main>
    </div>
  );
}

function MetricCard({ title, value, subtitle, tone = 'neutral' }) {
  return (
    <div className={`metric-card panel tone-${tone}`}>
      <p className="eyebrow">{title}</p>
      <h3>{value}</h3>
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
        <div className="hero-copy">
          <p className="eyebrow">System pulse</p>
          <h3>Recent signal and incident posture</h3>
          <p>
            The dashboard surfaces append-only alert history, current lifecycle state, and recent alert activity without
            unbounded queries.
          </p>
        </div>
        <div className="ops-strip">
          {OPS_SIGNALS.map(([value, label]) => (
            <span key={label}>
              <strong>{value}</strong>
              <small>{label}</small>
            </span>
          ))}
        </div>
      </div>
      <MetricCard title="Open incidents" value={stats?.open_incidents_count ?? '--'} subtitle="Active operator attention" tone="warning" />
      <MetricCard title="Investigating" value={stats?.investigating_incidents_count ?? '--'} subtitle="Supervisor-assisted triage" tone="info" />
      <MetricCard title="Mitigating" value={stats?.mitigating_incidents_count ?? '--'} subtitle="Remediation in progress" tone="accent" />
      <MetricCard title="Resolved in 24h" value={stats?.resolved_last_24h ?? '--'} subtitle="Closed-loop outcomes" tone="success" />

      <div className="panel">
        <div className="panel-header">
          <div>
            <p className="eyebrow">Queue</p>
            <h3>Recent incidents</h3>
          </div>
          <Link to="/incidents">See all</Link>
        </div>
        {error ? <p className="error-text">{error}</p> : null}
        <div className="incident-list compact">
          {incidents.map((incident) => (
            <Link key={incident.id} className="incident-row" to={`/incidents/${incident.id}`}>
              <div>
                <strong>{incident.summary || incident.fingerprint.slice(0, 14)}</strong>
                <p>{formatDate(incident.last_seen_at)}</p>
              </div>
              <div className="incident-meta">
                <SeverityChip severity={incident.severity} />
                <StatusChip status={incident.status} />
              </div>
            </Link>
          ))}
          {!incidents.length && !error ? <EmptyState title="No incidents yet" copy="Ingest an alert or run the test workflow to populate this queue." /> : null}
        </div>
      </div>

      <div className="panel">
        <div className="panel-header">
          <div>
            <p className="eyebrow">Signal</p>
            <h3>Recent alerts</h3>
          </div>
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
              <p>{formatDate(alert.created_at)}</p>
            </article>
          ))}
          {!recentAlerts.length && !error ? <EmptyState title="Quiet window" copy="No alerts returned for the last 24 hours." /> : null}
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
        <div>
          <p className="eyebrow">Triage queue</p>
          <h3>Incidents</h3>
        </div>
        <span className="count-pill">{data.total} total</span>
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
              <p>{incident.grouping_key.slice(0, 18)}... last seen {formatDate(incident.last_seen_at)}</p>
            </div>
            <div className="incident-meta">
              <span>{incident.alert_count} alerts</span>
              <SeverityChip severity={incident.severity} />
              <StatusChip status={incident.status} />
            </div>
          </Link>
        ))}
        {!data.items.length && !error ? <EmptyState title="No matching incidents" copy="Adjust the filters or generate a sample alert from the workflow page." /> : null}
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
          <div><strong>First seen</strong><p>{formatDate(incident.first_seen_at)}</p></div>
          <div><strong>Last seen</strong><p>{formatDate(incident.last_seen_at)}</p></div>
          <div><strong>SLA deadline</strong><p>{incident.sla_deadline ? formatDate(incident.sla_deadline) : 'n/a'}</p></div>
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
              <p>{formatDate(alert.created_at)}</p>
              <pre>{JSON.stringify(alert.payload, null, 2)}</pre>
            </article>
          ))}
          {!incident.alerts.length ? <EmptyState title="No alert samples loaded" copy="This incident detail request returned no alert payloads." /> : null}
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
                <span>{formatDate(event.created_at)}</span>
              </div>
              <pre>{JSON.stringify({ metadata: event.metadata, payload: event.payload }, null, 2)}</pre>
            </article>
          ))}
          {!incident.timeline.length ? <EmptyState title="No timeline events" copy="No event stream entries are available for this incident." /> : null}
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

function WorkflowTestPage() {
  const [rawAlert, setRawAlert] = useState(JSON.stringify(SAMPLE_ALERT, null, 2));
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const runWorkflow = async () => {
    setBusy(true);
    setError('');
    setResult(null);
    try {
      const parsed = JSON.parse(rawAlert);
      const response = await apiFetch('/test-workflow', { method: 'POST', body: JSON.stringify(parsed) });
      setResult(response);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="page-grid">
      <div className="hero-card span-2">
        <div className="hero-copy">
          <p className="eyebrow">Guided simulation</p>
          <h3>Run Alert - History - Supervisor - Report</h3>
          <p>Paste a raw alert payload, run the full workflow, and review sanitized LLM traces plus intermediate node output.</p>
        </div>
        <WorkflowRail trace={result?.trace || []} />
      </div>

      <div className="panel">
        <div className="panel-header">
          <div>
            <p className="eyebrow">Input</p>
            <h3>Raw alert JSON</h3>
          </div>
          <button type="button" className="ghost-button" onClick={() => setRawAlert(JSON.stringify(SAMPLE_ALERT, null, 2))}>Reset sample</button>
        </div>
        <textarea className="json-input" value={rawAlert} onChange={(event) => setRawAlert(event.target.value)} />
        <div className="action-row wrap">
          <button type="button" disabled={busy} onClick={runWorkflow}>{busy ? 'Running workflow...' : 'Test Alert'}</button>
        </div>
        {error ? <p className="error-text">{error}</p> : null}
      </div>

      <div className="panel">
        <div className="panel-header">
          <div>
            <p className="eyebrow">Trace</p>
            <h3>Workflow result</h3>
          </div>
          <StatusChip status={result?.status || 'pending'} />
        </div>
        {result ? (
          <div className="stack-list">
            <JsonBlock title="Step trace" data={result.trace || []} />
            <JsonBlock title="LLM request/response trace (sanitized)" data={result.llm_calls || []} />
            <JsonBlock title="Supervisor reasoning" data={result.supervisor || {}} />
            <JsonBlock title="Final report" data={result.report || {}} />
          </div>
        ) : (
          <EmptyState title="Awaiting workflow" copy="Run a test alert to see the full structured trace." />
        )}
      </div>

      <div className="panel span-2">
        <div className="panel-header">
          <div>
            <p className="eyebrow">Agent contract</p>
            <h3>Node system prompts</h3>
          </div>
          <span>Provider-agnostic behavior</span>
        </div>
        <div className="prompt-grid">
          {Object.entries(SYSTEM_PROMPTS).map(([node, prompt]) => (
            <article key={node} className="prompt-card">
              <p className="eyebrow">{node}</p>
              <p>{prompt}</p>
            </article>
          ))}
        </div>
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
    <section className="page-grid">
      <div className="hero-card span-2">
        <div className="hero-copy">
          <p className="eyebrow">Fleet readiness</p>
          <h3>Agent health</h3>
          <p>Every agent exposes health and readiness endpoints through the nginx API facade for quick operator verification.</p>
        </div>
        <div className="ops-strip">
          <span><strong>{health.length || '--'}</strong><small>responses</small></span>
          <span><strong>{error ? 'degraded' : 'normal'}</strong><small>view state</small></span>
        </div>
      </div>
      {error ? <p className="error-text">{error}</p> : null}
      <div className="health-grid span-2">
        {health.map((item) => (
          <article key={item.service} className="health-card">
            <p className="eyebrow">{item.service}</p>
            <h4>{item.status}</h4>
            <p>Database: {item.database}</p>
            <p>Readiness: {item.readiness}</p>
            <p>{item.timestamp}</p>
          </article>
        ))}
        {!health.length && !error ? <EmptyState title="Loading health checks" copy="Waiting for history, supervisor, and report endpoints." /> : null}
      </div>
    </section>
  );
}

function SettingsPage() {
  const [config, setConfig] = useState(null);
  const [draft, setDraft] = useState(null);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [testing, setTesting] = useState('');
  const [testResults, setTestResults] = useState({});
  const [secretStatus, setSecretStatus] = useState({});
  const [secretDraft, setSecretDraft] = useState({});

  const load = async () => {
    setError('');
    try {
      const [nextConfig, nextSecrets] = await Promise.all([
        apiFetch('/config/llm'),
        apiFetch('/config/llm/secrets'),
      ]);
      setConfig(nextConfig);
      setDraft(JSON.parse(JSON.stringify(nextConfig)));
      setSecretStatus(nextSecrets.providers || {});
      setSecretDraft({});
    } catch (err) {
      setError(err.message);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const updateAgent = (agent, patch) => {
    setDraft((current) => {
      const next = JSON.parse(JSON.stringify(current));
      const currentAgent = next.agents[agent];
      const updated = { ...currentAgent, ...patch };
      if (patch.provider && patch.provider !== currentAgent.provider) {
        updated.model = next.models[patch.provider]?.[0] || '';
      }
      next.agents[agent] = updated;
      return next;
    });
  };

  const save = async () => {
    setMessage('');
    setError('');
    try {
      const saved = await apiFetch('/config/llm', { method: 'POST', body: JSON.stringify(draft) });
      setConfig(saved);
      setDraft(JSON.parse(JSON.stringify(saved)));
      setMessage('LLM configuration saved and reloaded. Agents will use it on their next call.');
    } catch (err) {
      setError(err.message);
    }
  };

  const testAgent = async (agent) => {
    setTesting(agent);
    setMessage('');
    setError('');
    try {
      const result = await apiFetch(`/config/llm/test/${agent}`, { method: 'POST' });
      setTestResults((current) => ({ ...current, [agent]: result }));
    } catch (err) {
      setTestResults((current) => ({ ...current, [agent]: { ok: false, content: err.message } }));
    } finally {
      setTesting('');
    }
  };

  const saveSecrets = async () => {
    setMessage('');
    setError('');
    try {
      const secrets = Object.fromEntries(Object.entries(secretDraft).filter(([, value]) => value));
      await apiFetch('/config/llm/secrets', { method: 'POST', body: JSON.stringify({ secrets }) });
      setSecretDraft({});
      setMessage('API keys saved to the runtime secret store. No key values are shown or committed.');
      const nextSecrets = await apiFetch('/config/llm/secrets');
      setSecretStatus(nextSecrets.providers || {});
    } catch (err) {
      setError(err.message);
    }
  };

  if (!draft) {
    return <section className="panel">{error ? <p className="error-text">{error}</p> : <p>Loading LLM settings...</p>}</section>;
  }

  const agents = Object.keys(draft.agents || {});

  return (
    <section className="page-grid">
      <div className="hero-card span-2">
        <div className="hero-copy">
          <p className="eyebrow">LLM Settings</p>
          <h3>Live model routing per agent</h3>
          <p>Switch providers and models without rebuilding containers. The backend reloads this file-backed config on each LLM call.</p>
        </div>
        <div className="provider-strip">
          {draft.providers.map((provider) => <span key={provider}>{providerLabel(provider)}</span>)}
        </div>
      </div>

      {agents.map((agent) => {
        const selection = draft.agents[agent];
        const models = draft.models[selection.provider] || [];
        const result = testResults[agent];
        return (
          <article key={agent} className="panel llm-agent-card">
            <div className="panel-header">
              <div>
                <p className="eyebrow">Agent</p>
                <h3>{agent}</h3>
              </div>
              <StatusChip status={result?.ok ? 'resolved' : 'open'} />
            </div>
            <div className="badge-row">
              <ProviderBadge provider={selection.provider} />
              <ModelBadge model={selection.model} />
            </div>
            <details className="prompt-details">
              <summary>System prompt</summary>
              <p>{SYSTEM_PROMPTS[agent] || 'Provider-agnostic agent prompt managed by backend configuration.'}</p>
            </details>
            <label>
              Provider
              <select value={selection.provider} onChange={(event) => updateAgent(agent, { provider: event.target.value })}>
                {draft.providers.map((provider) => <option key={provider} value={provider}>{providerLabel(provider)}</option>)}
              </select>
            </label>
            <label>
              Model
              <select value={selection.model} onChange={(event) => updateAgent(agent, { model: event.target.value })}>
                {models.map((model) => <option key={model} value={model}>{model}</option>)}
              </select>
            </label>
            <div className="action-row wrap">
              <button type="button" onClick={save}>Save & reload config</button>
              <button type="button" className="ghost-button" disabled={testing === agent} onClick={() => testAgent(agent)}>
                {testing === agent ? 'Testing...' : 'Test LLM call'}
              </button>
            </div>
            {result ? <pre>{JSON.stringify(result, null, 2)}</pre> : null}
          </article>
        );
      })}

      <div className="panel span-2">
        <div className="panel-header">
          <div>
            <p className="eyebrow">Secrets</p>
            <h3>Runtime API keys</h3>
          </div>
          <button type="button" className="ghost-button" onClick={saveSecrets}>Save API Keys</button>
        </div>
        <p>Keys are written to the ignored runtime secret store and never displayed after save. Leave a field blank to keep the current value.</p>
        <div className="secret-grid">
          {Object.entries(draft.provider_settings || {}).map(([provider, settings]) => {
            const envName = settings.api_key_env;
            const status = secretStatus[provider] || {};
            return (
              <label key={provider}>
                {providerLabel(provider)} API key
                <span className="field-hint">
                  {envName} - {status.env_configured || status.configured ? 'configured' : 'not configured'}
                </span>
                <input
                  type="password"
                  value={secretDraft[envName] || ''}
                  placeholder="Paste key to update runtime secret"
                  onChange={(event) => setSecretDraft((current) => ({ ...current, [envName]: event.target.value }))}
                />
              </label>
            );
          })}
        </div>
      </div>

      <div className="panel span-2">
        <div className="panel-header">
          <h3>Current config</h3>
          <button type="button" className="ghost-button" onClick={load}>Refresh</button>
        </div>
        {message ? <p className="success-text">{message}</p> : null}
        {error ? <p className="error-text">{error}</p> : null}
        <pre>{JSON.stringify(config || draft, null, 2)}</pre>
      </div>
    </section>
  );
}

export default function App() {
  return (
    <Shell>
      <Routes>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/workflow" element={<WorkflowTestPage />} />
        <Route path="/incidents" element={<IncidentsPage />} />
        <Route path="/incidents/:incidentId" element={<IncidentDetailPage />} />
        <Route path="/agents" element={<AgentsPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Routes>
    </Shell>
  );
}
