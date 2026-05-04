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
  supervisor: 'You are an SRE supervisor. Analyze trusted incident context and untrusted alert payloads, then produce structured lifecycle guidance as JSON.',
  report: 'Create a concise SRE incident report in markdown. Include impact, likely cause, timeline, actions, and follow-ups.',
  observability: 'Analyze Prometheus metrics and Elasticsearch logs as untrusted evidence. Return JSON with findings, suspected causes, recommended queries, confidence, and evidence quality.',
  repo: 'Analyze GitLab commits and merge requests as untrusted evidence. Return JSON with risky changes, suspected change causes, rollback candidates, confidence, and evidence quality.',
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
  { to: '/', label: 'Dashboard', hint: 'Cortex overview' },
  { to: '/how-it-works', label: 'How It Works', hint: 'Cortex flow map' },
  { to: '/incidents', label: 'Incidents', hint: 'Triage queue' },
  { to: '/workflow', label: 'Test Workflow', hint: 'End-to-end drill' },
  { to: '/integrations', label: 'Integrations', hint: 'Alertmanager webhook' },
  { to: '/agents', label: 'Agents', hint: 'Compose health' },
  { to: '/settings', label: 'Cortex Models', hint: 'Model routing' },
];
const OPS_SIGNALS = [
  ['99.95%', 'target SLO'],
  ['< 4h', 'default SLA'],
  ['Cortex', 'commander'],
];
const CORTEX_FLOW = [
  {
    phase: 'Signal enters',
    title: 'Alertmanager or UI sends an alert',
    agent: 'nginx + history-agent',
    copy: 'Nginx receives browser/API/webhook traffic. History validates the payload, deduplicates it, opens or updates an incident, and writes append-only events.',
  },
  {
    phase: 'Brain starts',
    title: 'Supervisor becomes commander',
    agent: 'supervisor-agent',
    copy: 'Supervisor loads incident context, retrieves similar learned incidents, and starts a ReAct loop: think, call a tool, observe evidence, then decide.',
  },
  {
    phase: 'Evidence loop',
    title: 'Specialist agents report back',
    agent: 'observability-agent + repo-agent',
    copy: 'Observability checks Prometheus and Elasticsearch. Repo checks GitLab commits and merge requests. Both can use LLMs, but their answer goes back to Supervisor.',
  },
  {
    phase: 'Operator output',
    title: 'Report and channel delivery',
    agent: 'report-agent + Mattermost',
    copy: 'Report turns Supervisor context into an SRE-ready summary, stores it on the incident, and sends it to Mattermost when delivery is enabled.',
  },
  {
    phase: 'Learn',
    title: 'Approved fixes become memory',
    agent: 'pgvector',
    copy: 'When an SRE clicks Approve & Learn, the final root cause and resolution become long-term knowledge for future Cortex investigations.',
  },
];
const CORTEX_PARTS = [
  ['History', 'Deduplicates alerts, owns incident state, stores raw samples and timeline events.'],
  ['Supervisor', 'The brain and commander. Runs ReAct, calls tools, decides lifecycle and next actions.'],
  ['Observability', 'Reads Prometheus metrics and Elasticsearch logs, then returns evidence to Supervisor.'],
  ['Repo', 'Reads GitLab commits/MRs, finds risky changes, and returns code evidence to Supervisor.'],
  ['Report', 'Builds final incident reports and sends them to Mattermost or other channels.'],
  ['Memory', 'Redis keeps short-term ReAct traces. pgvector stores approved long-term lessons.'],
  ['Integrations', 'Alertmanager, Mattermost, Prometheus, Elasticsearch, GitLab, LLM providers, and proxies.'],
  ['UI', 'Cortex Command Center for triage, agent logs, investigations, configuration, and cleanup.'],
];
const SRE_OPERATOR_PLAYBOOK = [
  {
    stage: '1. Prepare the control plane',
    goal: 'Make Cortex trustworthy before an incident starts.',
    actions: [
      'Open Integrations and connect Alertmanager, Mattermost, Prometheus, Elasticsearch, and GitLab.',
      'Open Cortex Models and verify each LLM-backed agent has the right provider, model, prompt, API key, and proxy.',
      'Open Agents and confirm every service is healthy before relying on automated investigation.',
    ],
    button: 'Integrations',
    to: '/integrations',
  },
  {
    stage: '2. Triage incoming incidents',
    goal: 'Understand impact quickly and decide if Cortex should investigate.',
    actions: [
      'Open Incidents, filter by status or severity, and pick the newest/highest-risk incident.',
      'Read the incident header, alert samples, SLA deadline, service labels, and timeline.',
      'Click Ask Cortex Supervisor or Investigate so the commander gathers evidence from agents.',
    ],
    button: 'Incidents',
    to: '/incidents',
  },
  {
    stage: '3. Validate the agent evidence',
    goal: 'Use Cortex as a co-pilot, not a black box.',
    actions: [
      'Review Cortex command log to confirm Observability and Repo reported back to Supervisor.',
      'Expand ReAct Thought, Action, and Observation steps to understand why Supervisor made its decision.',
      'Run Prometheus, Elasticsearch, or GitLab widgets manually when you need extra proof.',
    ],
    button: 'How traces look',
    to: '/workflow',
  },
  {
    stage: '4. Execute and communicate',
    goal: 'Move the incident forward with clear operator actions.',
    actions: [
      'Use Mitigate when a workaround, rollback, scale-up, or traffic shift starts.',
      'Generate Cortex Report when you need a clean update for Mattermost or stakeholders.',
      'Keep the timeline clean: delete only test/noise events, never real audit evidence during production incidents.',
    ],
    button: 'Run drill',
    to: '/workflow',
  },
  {
    stage: '5. Resolve and teach Cortex',
    goal: 'Close the loop so the next incident is faster.',
    actions: [
      'Click Resolve only after Alertmanager/service signals are healthy and the customer impact is gone.',
      'Click Approve & Learn, edit the root cause and resolution, and save the final human-approved lesson.',
      'Use the latest report and command log for post-incident review and follow-up tasks.',
    ],
    button: 'Review queue',
    to: '/incidents',
  },
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


function safeJson(value) {
  try {
    return typeof value === 'string' ? JSON.parse(value) : value;
  } catch {
    return value;
  }
}

function eventCategory(event) {
  const text = `${event.actor || ''} ${event.event_type || ''}`.toLowerCase();
  if (text.includes('supervisor')) return 'supervisor';
  if (text.includes('observability') || text.includes('prometheus') || text.includes('elastic')) return 'observability';
  if (text.includes('repo') || text.includes('gitlab')) return 'repo';
  if (text.includes('report') || text.includes('mattermost')) return 'report';
  if (text.includes('history') || text.includes('alert')) return 'history';
  return 'system';
}

function eventSummary(event) {
  const metadata = safeJson(event.metadata) || {};
  const payload = safeJson(event.payload) || {};
  const candidates = [
    metadata.summary,
    metadata.action,
    metadata.reason,
    metadata.message,
    payload.summary,
    payload.description,
    payload.status,
    payload.reason,
  ];
  const value = candidates.find((item) => typeof item === 'string' && item.trim());
  if (value) return value.length > 220 ? `${value.slice(0, 220)}...` : value;
  return `${event.actor || 'system'} recorded ${event.event_type || 'an event'}.`;
}

function InvestigationTimeline({ events, busy, onDeleteEvent }) {
  const [filter, setFilter] = useState('all');
  const filters = ['all', 'supervisor', 'observability', 'repo', 'report', 'history', 'system'];
  const visibleEvents = events.filter((event) => filter === 'all' || eventCategory(event) === filter);

  return (
    <div className="panel span-2 investigation-timeline-panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Investigation</p>
          <h3>Timeline</h3>
        </div>
        <span className="count-pill">{visibleEvents.length}/{events.length} events</span>
      </div>
      <div className="timeline-filter-row">
        {filters.map((item) => (
          <button
            key={item}
            type="button"
            className={filter === item ? 'timeline-filter active' : 'timeline-filter'}
            onClick={() => setFilter(item)}
          >
            {item}
          </button>
        ))}
      </div>
      {!visibleEvents.length ? (
        <EmptyState title="No timeline events" copy="No event stream entries match this filter for the incident." />
      ) : (
        <div className="investigation-timeline">
          {visibleEvents.map((event, index) => {
            const category = eventCategory(event);
            return (
              <article key={event.event_id} className={`investigation-event event-${category}`}>
                <div className="timeline-rail" aria-hidden="true">
                  <span>{String(index + 1).padStart(2, '0')}</span>
                </div>
                <div className="investigation-event-body">
                  <div className="investigation-event-head">
                    <div>
                      <span className="count-pill">{category}</span>
                      <h4>{event.event_type || 'timeline event'}</h4>
                      <p>{eventSummary(event)}</p>
                    </div>
                    <div className="investigation-event-meta">
                      <strong>{event.actor || 'system'}</strong>
                      <span>{formatDate(event.created_at)}</span>
                    </div>
                  </div>
                  <div className="action-row wrap">
                    <details className="json-viewer compact-json">
                      <summary>Raw metadata and payload</summary>
                      <pre>{JSON.stringify({ metadata: safeJson(event.metadata), payload: safeJson(event.payload) }, null, 2)}</pre>
                    </details>
                    <button
                      type="button"
                      className="danger-button small-button"
                      disabled={busy}
                      onClick={() => onDeleteEvent(event)}
                    >
                      Delete event
                    </button>
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}

function incidentServiceName(incident) {
  const alert = incident?.alerts?.[0];
  const labels = alert?.payload?.labels || {};
  return labels.service || labels.job || labels.app || labels.alertname || incident?.summary || '';
}

function ReActTracePanel({ trace, loading }) {
  const steps = trace?.steps || [];
  return (
    <div className="panel span-2 cot-panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Supervisor ReAct</p>
          <h3>Chain of Thought Trace</h3>
        </div>
        <span className="count-pill">{loading ? 'polling' : `${steps.length} steps`}</span>
      </div>
      {!steps.length ? (
        <EmptyState title="No ReAct steps yet" copy="Ask Supervisor or wait while an investigating incident is analyzed." />
      ) : (
        <div className="cot-list">
          {steps.map((step, index) => (
            <article key={`${step.iteration || index}-${index}`} className="cot-step">
              <div className="cot-step-header">
                <span className="count-pill">Iteration {step.iteration || index + 1}</span>
                {step.final ? <StatusChip status="resolved" /> : <StatusChip status="investigating" />}
              </div>
              {step.thought ? (
                <div className="cot-thought">
                  <strong>Thought</strong>
                  <p>{step.thought}</p>
                </div>
              ) : null}
              {step.action ? (
                <div className="cot-action">
                  <strong>Action</strong>
                  <span className="tool-badge">{step.action.name || 'tool'}</span>
                  {step.action.input ? <code>{typeof step.action.input === 'string' ? step.action.input : JSON.stringify(step.action.input)}</code> : null}
                </div>
              ) : null}
              {step.observation ? (
                <div className="cot-observation">
                  <strong>Observation</strong>
                  <pre>{JSON.stringify(safeJson(step.observation), null, 2)}</pre>
                </div>
              ) : null}
              {step.final ? <JsonBlock title="Final decision" data={step.final} /> : null}
            </article>
          ))}
        </div>
      )}
    </div>
  );
}

function IncidentIntegrationsPanel({ incident }) {
  const serviceName = incidentServiceName(incident);
  const [query, setQuery] = useState(serviceName ? `up{job=~"${serviceName}.*"}` : 'up');
  const [projectId, setProjectId] = useState('');
  const [metrics, setMetrics] = useState(null);
  const [logs, setLogs] = useState(null);
  const [repo, setRepo] = useState(null);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    setQuery(serviceName ? `up{job=~"${serviceName}.*"}` : 'up');
  }, [serviceName]);

  const loadMetrics = async () => {
    setBusy('metrics');
    setError('');
    try {
      setMetrics(await apiFetch('/observability/api/v1/metrics/query', { method: 'POST', body: JSON.stringify({ incident_id: incident.id, query }) }));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy('');
    }
  };

  const loadLogs = async () => {
    setBusy('logs');
    setError('');
    try {
      const params = new URLSearchParams({ service: serviceName, minutes: '60' });
      setLogs(await apiFetch(`/observability/api/v1/logs/errors?${params.toString()}`));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy('');
    }
  };

  const loadRepo = async () => {
    setBusy('repo');
    setError('');
    try {
      const params = new URLSearchParams({ days: '7', limit: '10' });
      if (projectId) params.set('project_id', projectId);
      setRepo(await apiFetch(`/repo/api/v1/repo/changes?${params.toString()}`));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy('');
    }
  };

  return (
    <div className="panel span-2">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Live integrations</p>
          <h3>Metrics, logs, and repo changes</h3>
        </div>
        <span className="count-pill">{serviceName || 'service unknown'}</span>
      </div>
      <div className="integration-grid">
        <div className="copy-card integration-card">
          <label>
            PromQL
            <input value={query} onChange={(event) => setQuery(event.target.value)} />
          </label>
          <button type="button" disabled={busy === 'metrics'} onClick={loadMetrics}>{busy === 'metrics' ? 'Querying...' : 'Query Prometheus'}</button>
          {metrics ? <JsonBlock title="Prometheus result" data={metrics.data || metrics} /> : null}
        </div>
        <div className="copy-card integration-card">
          <p><strong>Elasticsearch errors</strong></p>
          <p>Searches recent ERROR, Exception, and Traceback logs for the detected service.</p>
          <button type="button" disabled={busy === 'logs' || !serviceName} onClick={loadLogs}>{busy === 'logs' ? 'Searching...' : 'Search recent errors'}</button>
          {logs ? <JsonBlock title="Error logs" data={logs.entries || logs} /> : null}
        </div>
        <div className="copy-card integration-card">
          <label>
            GitLab project ID/path
            <input value={projectId} onChange={(event) => setProjectId(event.target.value)} placeholder="group/project or numeric ID" />
          </label>
          <button type="button" disabled={busy === 'repo'} onClick={loadRepo}>{busy === 'repo' ? 'Loading...' : 'Fetch GitLab changes'}</button>
          {repo ? <JsonBlock title="Recent commits and MRs" data={repo} /> : null}
        </div>
      </div>
      {error ? <p className="error-text">{error}</p> : null}
    </div>
  );
}


function SimilarIncidentsPanel({ similar }) {
  const items = similar?.items || [];
  return (
    <div className="panel span-2">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Long-term memory</p>
          <h3>Similar Past Incidents</h3>
        </div>
        <span className="count-pill">{items.length} matches</span>
      </div>
      {!items.length ? (
        <EmptyState title="No learned incidents yet" copy="Approve resolved incidents to build the pgvector knowledge base." />
      ) : (
        <div className="stack-list">
          {items.map((item) => (
            <article key={item.id} className="stack-item memory-card">
              <div className="incident-meta">
                <SeverityChip severity={item.severity} />
                <span className="count-pill">score {item.score}</span>
              </div>
              <strong>{item.summary}</strong>
              <p>{item.service || 'unknown service'} - {formatDate(item.created_at)}</p>
              <JsonBlock title="Root cause and resolution" data={{ root_cause: item.root_cause, resolution: item.resolution }} />
            </article>
          ))}
        </div>
      )}
    </div>
  );
}

function ApproveLearnModal({ incident, trace, report, onClose, onSaved }) {
  const finalStep = [...(trace?.steps || [])].reverse().find((step) => step.final)?.final || {};
  const [rootCause, setRootCause] = useState(finalStep.root_cause || '');
  const [resolution, setResolution] = useState(report?.report_event?.report || finalStep.reasoning_trace || '');
  const [summary, setSummary] = useState(incident.summary || incident.fingerprint || '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const save = async () => {
    setBusy(true);
    setError('');
    try {
      await apiFetch(`/supervisor/incidents/${incident.id}/approve`, {
        method: 'POST',
        body: JSON.stringify({ root_cause: rootCause, resolution, summary, severity: incident.severity }),
      });
      await onSaved();
      onClose();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true">
      <div className="modal-card panel">
        <div className="panel-header">
          <div>
            <p className="eyebrow">Human feedback loop</p>
            <h3>Approve & Learn</h3>
          </div>
          <button type="button" className="ghost-button" onClick={onClose}>Close</button>
        </div>
        <label>
          Incident summary
          <input value={summary} onChange={(event) => setSummary(event.target.value)} />
        </label>
        <label>
          Final root cause
          <textarea rows="5" value={rootCause} onChange={(event) => setRootCause(event.target.value)} />
        </label>
        <label>
          Resolution / operator notes
          <textarea rows="8" value={resolution} onChange={(event) => setResolution(event.target.value)} />
        </label>
        <div className="action-row wrap">
          <button type="button" disabled={busy || rootCause.length < 3 || resolution.length < 3} onClick={save}>{busy ? 'Saving...' : 'Save to long-term memory'}</button>
          <button type="button" className="ghost-button" disabled={busy} onClick={onClose}>Cancel</button>
        </div>
        {error ? <p className="error-text">{error}</p> : null}
      </div>
    </div>
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
          <div className="brand-topline">
            <div className="brand-mark">CX</div>
            <span className="brand-status">Live command</span>
          </div>
          <div className="brand-title">
            <p className="eyebrow">Cortex</p>
            <h1>Incident Command</h1>
          </div>
          <p className="sidebar-copy">
            Supervisor-led incident intelligence for alerts, evidence, decisions, reports, and SRE learning.
          </p>
          <div className="brand-signals" aria-label="Cortex core capabilities">
            <span>Brain</span>
            <span>Agents</span>
            <span>Reports</span>
          </div>
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
            <p>Supervisor commands Cortex agents through nginx</p>
          </div>
        </div>
      </aside>
      <main className="content">
        <header className="topbar">
          <div>
            <p className="eyebrow">Operational overview</p>
            <h2>Cortex incident command</h2>
          </div>
          <div className="topbar-actions">
            <span className="topbar-note">Supervisor-first agent logs, evidence, and actions</span>
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
          <p className="eyebrow">Cortex pulse</p>
          <h3>Signals, commander state, and incident posture</h3>
          <p>
            Cortex surfaces append-only alert history, Supervisor decisions, and recent signal activity without
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

function HowItWorksPage() {
  return (
    <section className="page-grid how-page">
      <div className="hero-card span-2 cortex-hero">
        <div className="hero-copy">
          <p className="eyebrow">How Cortex works</p>
          <h3>One command brain, many specialist senses</h3>
          <p>
            Cortex is built like an incident-response nervous system: alerts enter through the edge, History keeps the
            memory, Supervisor commands the investigation, specialist agents bring evidence, and Report turns the final
            decision into operator-ready communication.
          </p>
          <div className="action-row wrap">
            <Link className="hero-cta" to="/integrations">Connect integrations</Link>
            <Link className="hero-cta secondary" to="/workflow">Run test workflow</Link>
          </div>
        </div>
        <div className="cortex-orbit" aria-label="Cortex agent relationship diagram">
          <div className="orbit-ring ring-one" />
          <div className="orbit-ring ring-two" />
          <div className="orbit-core">Supervisor</div>
          <span className="orbit-node node-history">History</span>
          <span className="orbit-node node-obs">Observability</span>
          <span className="orbit-node node-repo">Repo</span>
          <span className="orbit-node node-report">Report</span>
        </div>
      </div>

      <div className="panel span-2 cortex-map-panel">
        <div className="panel-header">
          <div>
            <p className="eyebrow">Live flow</p>
            <h3>Alert to resolution</h3>
          </div>
          <span className="count-pill">Supervisor-first</span>
        </div>
        <div className="flow-river" aria-label="Cortex request flow">
          {CORTEX_FLOW.map((step, index) => (
            <article key={step.phase} className="flow-step">
              <div className="flow-marker">{index + 1}</div>
              <div>
                <span className="count-pill">{step.phase}</span>
                <h4>{step.title}</h4>
                <strong>{step.agent}</strong>
                <p>{step.copy}</p>
              </div>
            </article>
          ))}
        </div>
      </div>

      <div className="panel span-2">
        <div className="panel-header">
          <div>
            <p className="eyebrow">Architecture</p>
            <h3>Cortex parts</h3>
          </div>
          <span className="count-pill">{CORTEX_PARTS.length} modules</span>
        </div>
        <div className="part-grid">
          {CORTEX_PARTS.map(([title, copy]) => (
            <article key={title} className="part-card">
              <div className="part-glyph">{title.slice(0, 2).toUpperCase()}</div>
              <h4>{title}</h4>
              <p>{copy}</p>
            </article>
          ))}
        </div>
      </div>

      <div className="panel cortex-loop-card">
        <div className="panel-header">
          <div>
            <p className="eyebrow">ReAct loop</p>
            <h3>How Supervisor thinks</h3>
          </div>
        </div>
        <div className="loop-stack">
          <div><span>Thought</span><p>What is the most likely failure path?</p></div>
          <div><span>Action</span><p>Call observability or repo tools for evidence.</p></div>
          <div><span>Observation</span><p>Read metrics, logs, commits, and previous incident memories.</p></div>
          <div><span>Decision</span><p>Recommend investigation, mitigation, resolution, and report content.</p></div>
        </div>
      </div>

      <div className="panel cortex-loop-card">
        <div className="panel-header">
          <div>
            <p className="eyebrow">Operator loop</p>
            <h3>How SREs use it</h3>
          </div>
        </div>
        <div className="operator-path">
          <Link to="/incidents">Open incident</Link>
          <span>Review agent logs</span>
          <span>Run integrations</span>
          <span>Generate report</span>
          <span>Approve & Learn</span>
        </div>
        <p className="muted-text">The UI keeps raw payloads available, but the primary experience is the Cortex command log and investigation timeline.</p>
      </div>

      <div className="panel span-2 sre-playbook-panel">
        <div className="panel-header">
          <div>
            <p className="eyebrow">SRE operator playbook</p>
            <h3>What you should do with Cortex during real operations</h3>
          </div>
          <span className="count-pill">Human-in-command</span>
        </div>
        <p className="playbook-intro">
          Cortex does the repetitive evidence gathering, timeline writing, and report drafting. The SRE stays in
          control: verify the evidence, choose the safe action, communicate clearly, and approve what the system should
          remember.
        </p>
        <div className="sre-playbook-grid">
          {SRE_OPERATOR_PLAYBOOK.map((item) => (
            <article key={item.stage} className="sre-playbook-card">
              <div className="playbook-card-header">
                <div>
                  <span className="count-pill">{item.stage}</span>
                  <h4>{item.goal}</h4>
                </div>
                <Link className="ghost-button small-button" to={item.to}>{item.button}</Link>
              </div>
              <ul>
                {item.actions.map((action) => <li key={action}>{action}</li>)}
              </ul>
            </article>
          ))}
        </div>
        <div className="operator-principles">
          <div>
            <strong>Trust but verify</strong>
            <p>Use LLM output as a fast hypothesis. Confirm with metrics, logs, repo changes, and service health.</p>
          </div>
          <div>
            <strong>Keep audit history clean</strong>
            <p>Delete test data when needed, but preserve real incident evidence for review and learning.</p>
          </div>
          <div>
            <strong>Teach the system</strong>
            <p>Approve only accurate root causes and resolutions so pgvector memory improves future investigations.</p>
          </div>
        </div>
      </div>
    </section>
  );
}

function IncidentsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [data, setData] = useState({ items: [], total: 0, page: 1, page_size: 20 });
  const [error, setError] = useState('');
  const [deletingId, setDeletingId] = useState('');

  const statusFilter = searchParams.get('status') || '';
  const query = searchParams.get('query') || '';

  const loadIncidents = () => {
    const params = new URLSearchParams();
    if (statusFilter) params.set('status', statusFilter);
    if (query) params.set('query', query);
    params.set('page', '1');
    params.set('page_size', '20');
    return apiFetch(`/history/incidents?${params.toString()}`)
      .then(setData)
      .catch((err) => setError(err.message));
  };

  useEffect(() => {
    loadIncidents();
  }, [statusFilter, query]);

  const deleteIncident = async (incident) => {
    const label = incident.summary || incident.fingerprint;
    if (!window.confirm(`Delete this incident and all its alerts/events?\n\n${label}`)) return;
    setDeletingId(incident.id);
    setError('');
    try {
      await apiFetch(`/history/incidents/${incident.id}`, { method: 'DELETE' });
      await loadIncidents();
    } catch (err) {
      setError(err.message);
    } finally {
      setDeletingId('');
    }
  };

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
          <article key={incident.id} className="incident-row">
            <Link className="incident-main-link" to={`/incidents/${incident.id}`}>
              <div>
                <strong>{incident.summary || incident.fingerprint}</strong>
                <p>{incident.grouping_key.slice(0, 18)}... last seen {formatDate(incident.last_seen_at)}</p>
              </div>
            </Link>
            <div className="incident-meta">
              <span>{incident.alert_count} alerts</span>
              <SeverityChip severity={incident.severity} />
              <StatusChip status={incident.status} />
              <button
                type="button"
                className="danger-button"
                disabled={deletingId === incident.id}
                onClick={() => deleteIncident(incident)}
              >
                Delete
              </button>
            </div>
          </article>
        ))}
        {!data.items.length && !error ? <EmptyState title="No matching incidents" copy="Adjust the filters or generate a sample alert from the workflow page." /> : null}
      </div>
    </section>
  );
}


function CortexCommandPanel({ workflowSummary, trace, report }) {
  const agents = ['supervisor-agent', 'observability-agent', 'repo-agent', 'history-agent', 'report-agent'];
  const byAgent = workflowSummary?.by_agent || {};
  const traceSteps = trace?.steps || [];
  const supervisorFinal = [...traceSteps].reverse().find((step) => step.final)?.final;
  const commander = workflowSummary?.commander_flow || {
    brain: 'supervisor-agent',
    contract: 'Supervisor is the commander. Tool agents return evidence to Supervisor before final operator output.',
  };

  const actionPreview = (action) => {
    const text = typeof action.action === 'string' ? action.action : JSON.stringify(action.action || '');
    return text.length > 320 ? `${text.slice(0, 320)}...` : text;
  };

  return (
    <div className="panel span-2 cortex-command-panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Cortex command log</p>
          <h3>Supervisor brain and agent responses</h3>
        </div>
        <span className="count-pill">{workflowSummary?.actions?.length || 0} actions</span>
      </div>
      <p className="commander-copy">{commander.contract}</p>
      <div className="commander-strip">
        <div>
          <span>Brain</span>
          <strong>{commander.brain || 'supervisor-agent'}</strong>
        </div>
        <div>
          <span>Observability reports</span>
          <strong>{commander.observability_reports_to_supervisor ? 'seen' : 'waiting'}</strong>
        </div>
        <div>
          <span>Repo reports</span>
          <strong>{commander.repo_reports_to_supervisor ? 'seen' : 'waiting'}</strong>
        </div>
        <div>
          <span>Final report</span>
          <strong>{report || workflowSummary?.final_report ? 'generated' : 'pending'}</strong>
        </div>
      </div>

      {supervisorFinal ? <JsonBlock title="Supervisor final decision" data={supervisorFinal} /> : null}

      <div className="agent-ledger-grid">
        {agents.map((agent) => {
          const actions = byAgent[agent] || [];
          return (
            <article key={agent} className={`agent-ledger-card ${agent === 'supervisor-agent' ? 'commander-card' : ''}`}>
              <div className="panel-header compact">
                <div>
                  <p className="eyebrow">{agent === 'supervisor-agent' ? 'Commander' : 'Agent'}</p>
                  <h3>{agent}</h3>
                </div>
                <span className="count-pill">{actions.length}</span>
              </div>
              {!actions.length ? (
                <p className="muted-text">No recorded action for this incident yet.</p>
              ) : (
                <div className="agent-action-list">
                  {actions.map((action) => (
                    <details key={`${agent}-${action.sequence}-${action.event_type}`} className="agent-action-item">
                      <summary>
                        <span>{action.event_type}</span>
                        <small>{formatDate(action.at)}</small>
                      </summary>
                      <p>{actionPreview(action)}</p>
                      {action.details?.recommended_actions?.length ? <JsonBlock title="Recommended actions" data={action.details.recommended_actions} /> : null}
                      {action.details?.llm_trace ? <JsonBlock title="LLM trace" data={action.details.llm_trace} /> : null}
                      {action.details ? <JsonBlock title="Raw action detail" data={safeJson(action.details)} /> : null}
                    </details>
                  ))}
                </div>
              )}
            </article>
          );
        })}
      </div>
    </div>
  );
}

function IncidentDetailPage() {
  const { incidentId } = useParams();
  const navigate = useNavigate();
  const [incident, setIncident] = useState(null);
  const [report, setReport] = useState(null);
  const [workflowSummary, setWorkflowSummary] = useState(null);
  const [reactTrace, setReactTrace] = useState(null);
  const [similarIncidents, setSimilarIncidents] = useState(null);
  const [approveOpen, setApproveOpen] = useState(false);
  const [traceLoading, setTraceLoading] = useState(false);
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
      try {
        const summary = await apiFetch(`/report/${incidentId}/workflow-summary`);
        setWorkflowSummary(summary);
      } catch {
        setWorkflowSummary(null);
      }
      try {
        const trace = await apiFetch(`/supervisor/incidents/${incidentId}/trace`);
        setReactTrace(trace);
      } catch {
        setReactTrace(null);
      }
      try {
        const similar = await apiFetch(`/supervisor/incidents/${incidentId}/similar`);
        setSimilarIncidents(similar);
      } catch {
        setSimilarIncidents(null);
      }
    } catch (err) {
      setError(err.message);
    }
  };

  useEffect(() => {
    load();
  }, [incidentId]);

  useEffect(() => {
    if (!incident || incident.status !== 'investigating') return undefined;
    let cancelled = false;
    const refreshTrace = async () => {
      setTraceLoading(true);
      try {
        const trace = await apiFetch(`/supervisor/incidents/${incidentId}/trace`);
        if (!cancelled) setReactTrace(trace);
      } catch {
        // Keep the latest successful trace visible while polling.
      } finally {
        if (!cancelled) setTraceLoading(false);
      }
    };
    refreshTrace();
    const timer = window.setInterval(refreshTrace, 3000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [incident?.status, incidentId]);

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

  const deleteCurrentIncident = async () => {
    if (!window.confirm(`Delete this incident and all its alerts/events?\n\n${incident.summary || incident.fingerprint}`)) return;
    setBusy(true);
    setMessage('');
    setError('');
    try {
      const result = await apiFetch(`/history/incidents/${incident.id}`, { method: 'DELETE' });
      setMessage(JSON.stringify(result, null, 2));
      navigate('/incidents');
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const deleteEvent = async (event) => {
    if (!window.confirm(`Delete this event from the incident timeline?\n\n${event.event_type}`)) return;
    setBusy(true);
    setMessage('');
    setError('');
    try {
      const result = await apiFetch(`/history/incidents/${incident.id}/events/${event.event_id}`, { method: 'DELETE' });
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
            <p className="eyebrow">Cortex incident</p>
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
          <button disabled={busy} onClick={() => act('/supervisor/analyze', { incident_id: incident.id })}>Ask Cortex Supervisor</button>
          <button disabled={busy} onClick={() => act('/supervisor/investigate', { incident_id: incident.id, reason: 'Investigate from UI' })}>Investigate</button>
          <button disabled={busy} onClick={() => act('/supervisor/mitigate', { incident_id: incident.id, reason: 'Mitigate from UI' })}>Mitigate</button>
          <button disabled={busy} onClick={() => act('/supervisor/resolve', { incident_id: incident.id, reason: 'Resolve from UI' })}>Resolve</button>
          <button disabled={busy} onClick={() => act(`/report/${incident.id}`, {})}>Generate Cortex Report</button>
          <button disabled={busy} onClick={() => setApproveOpen(true)}>Approve & Learn</button>
          <button className="danger-button" disabled={busy} onClick={deleteCurrentIncident}>Delete Incident</button>
          <button className="ghost-button" onClick={() => navigate('/incidents')}>Back</button>
        </div>
        {message ? <pre>{message}</pre> : null}
        {error ? <p className="error-text">{error}</p> : null}
      </div>

      <CortexCommandPanel workflowSummary={workflowSummary} trace={reactTrace} report={report} />

      <ReActTracePanel trace={reactTrace} loading={traceLoading} />

      <SimilarIncidentsPanel similar={similarIncidents} />

      <IncidentIntegrationsPanel incident={incident} />

      {approveOpen ? (
        <ApproveLearnModal
          incident={incident}
          trace={reactTrace}
          report={report}
          onClose={() => setApproveOpen(false)}
          onSaved={load}
        />
      ) : null}

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

      <InvestigationTimeline events={incident.timeline} busy={busy} onDeleteEvent={deleteEvent} />

      <div className="panel span-2">
        <div className="panel-header">
          <h3>Latest report</h3>
          <span>{report ? 'stored' : 'not generated yet'}</span>
        </div>
        {report ? <pre>{report.report_event.report}</pre> : <p>No report event exists for this incident yet.</p>}
      </div>

      <div className="panel span-2">
        <div className="panel-header">
          <div>
            <p className="eyebrow">Cortex report</p>
            <h3>All agent actions and channel delivery</h3>
          </div>
          <span>{workflowSummary?.actions?.length || 0} actions</span>
        </div>
        {workflowSummary ? (
          <div className="stack-list">
            <div className="timeline-grid">
              {workflowSummary.actions.map((action) => (
                <article key={`${action.sequence}-${action.event_type}`} className="timeline-item">
                  <div className="timeline-meta">
                    <strong>{action.agent}</strong>
                    <span>{action.event_type}</span>
                    <span>{formatDate(action.at)}</span>
                  </div>
                  <p>{action.action}</p>
                </article>
              ))}
            </div>
            <JsonBlock title="Delivery records" data={workflowSummary.deliveries || []} />
            <details className="json-viewer" open>
              <summary>Copyable markdown summary</summary>
              <pre>{workflowSummary.markdown}</pre>
            </details>
          </div>
        ) : (
          <p>No agent activity summary is available yet.</p>
        )}
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
  const nodes = [
    { name: 'history-agent', path: '/history/health', json: true },
    { name: 'report-agent', path: '/report/health', json: true },
    { name: 'supervisor-agent', path: '/supervisor/health', json: true },
    { name: 'observability-agent', path: '/observability/health', json: true },
    { name: 'repo-agent', path: '/repo/health', json: true },
    { name: 'prometheus', path: '/nodes/prometheus/health', json: false },
    { name: 'alertmanager', path: '/nodes/alertmanager/health', json: false },
    { name: 'grafana', path: '/nodes/grafana/health', json: true },
    { name: 'node-exporter', path: '/nodes/node-exporter/metrics', json: false },
  ];

  const loadHealth = async () => {
    setError('');
    const results = await Promise.all(nodes.map(async (node) => {
      try {
        const response = await fetch(`${API_BASE}${node.path}`);
        const body = node.json ? await response.json() : await response.text();
        return {
          service: node.name,
          status: response.ok ? 'ok' : 'failed',
          readiness: response.ok ? 'ready' : `http ${response.status}`,
          database: body?.database || 'n/a',
          detail: typeof body === 'string' ? body.slice(0, 180) : body,
          timestamp: body?.timestamp || new Date().toISOString(),
        };
      } catch (err) {
        return { service: node.name, status: 'failed', readiness: err.message, database: 'n/a', detail: err.message, timestamp: new Date().toISOString() };
      }
    }));
    setHealth(results);
  };

  useEffect(() => {
    loadHealth().catch((err) => setError(err.message));
    const timer = window.setInterval(() => loadHealth().catch((err) => setError(err.message)), 10000);
    return () => window.clearInterval(timer);
  }, []);

  const okCount = health.filter((item) => item.status === 'ok').length;

  return (
    <section className="page-grid">
      <div className="hero-card span-2">
        <div className="hero-copy">
          <p className="eyebrow">Fleet readiness</p>
          <h3>Docker compose node health</h3>
          <p>Health checks cover app agents plus Prometheus, Alertmanager, Grafana, Redis-backed ReAct memory dependencies, and node-exporter reachability.</p>
        </div>
        <div className="ops-strip">
          <span><strong>{okCount}/{health.length || nodes.length}</strong><small>healthy</small></span>
          <span><strong>{error ? 'degraded' : 'polling'}</strong><small>10s refresh</small></span>
        </div>
      </div>
      {error ? <p className="error-text">{error}</p> : null}
      <div className="health-grid span-2">
        {health.map((item) => (
          <article key={item.service} className="health-card">
            <div className="panel-header compact">
              <div>
                <p className="eyebrow">{item.service}</p>
                <h4>{item.status}</h4>
              </div>
              <StatusChip status={item.status} />
            </div>
            <p>Database: {item.database}</p>
            <p>Readiness: {item.readiness}</p>
            <p>{formatDate(item.timestamp)}</p>
            <details className="json-viewer">
              <summary>Raw detail</summary>
              <pre>{typeof item.detail === 'string' ? item.detail : JSON.stringify(item.detail, null, 2)}</pre>
            </details>
          </article>
        ))}
        {!health.length && !error ? <EmptyState title="Loading health checks" copy="Waiting for compose node endpoints." /> : null}
      </div>
    </section>
  );
}

function MattermostIntegration() {
  const [config, setConfig] = useState(null);
  const [draft, setDraft] = useState({ enabled: false, webhook_url: '', channel: '', username: 'Cortex Report Agent', icon_url: '' });
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState('');

  const load = async () => {
    setError('');
    try {
      const next = await apiFetch('/report/integrations/mattermost');
      setConfig(next);
      setDraft((current) => ({
        ...current,
        enabled: Boolean(next.enabled),
        channel: next.channel || '',
        username: next.username || 'Cortex Report Agent',
        icon_url: next.icon_url || '',
        webhook_url: '',
      }));
    } catch (err) {
      setError(err.message);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const update = (patch) => setDraft((current) => ({ ...current, ...patch }));

  const save = async () => {
    setBusy('save');
    setMessage('');
    setError('');
    try {
      const payload = { ...draft };
      if (!payload.webhook_url) {
        delete payload.webhook_url;
      }
      const next = await apiFetch('/report/integrations/mattermost', { method: 'PUT', body: JSON.stringify(payload) });
      setConfig(next);
      update({ webhook_url: '' });
      setMessage('Mattermost integration saved. New report-agent reports will be posted when delivery is enabled.');
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy('');
    }
  };

  const sendTest = async () => {
    setBusy('test');
    setMessage('');
    setError('');
    try {
      const result = await apiFetch('/report/integrations/mattermost/test', { method: 'POST', body: JSON.stringify({}) });
      setMessage(result.sent ? 'Mattermost test message sent.' : `Mattermost test skipped: ${result.skipped || 'disabled'}`);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy('');
    }
  };

  return (
    <div className="panel span-2">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Mattermost delivery</p>
          <h3>Send reports to a channel</h3>
        </div>
        <StatusChip status={config?.enabled ? 'resolved' : 'open'} />
      </div>
      <p>
        Paste a Mattermost incoming webhook URL. When report-agent generates a new incident report, it posts the report
        to Mattermost without blocking report storage.
      </p>
      <div className="secret-grid">
        <label className="toggle-row">
          <input type="checkbox" checked={draft.enabled} onChange={(event) => update({ enabled: event.target.checked })} />
          Enable Mattermost delivery
        </label>
        <label>
          Incoming webhook URL
          <span className="field-hint">
            {config?.webhook_url_configured ? `configured (${config.webhook_url_preview})` : 'not configured'}
          </span>
          <input
            type="password"
            value={draft.webhook_url}
            placeholder="https://mattermost.example.com/hooks/..."
            onChange={(event) => update({ webhook_url: event.target.value })}
          />
        </label>
        <label>
          Channel override
          <span className="field-hint">Optional channel name; leave blank for the webhook default channel.</span>
          <input value={draft.channel} placeholder="town-square or @username" onChange={(event) => update({ channel: event.target.value })} />
        </label>
        <label>
          Bot username
          <input value={draft.username} onChange={(event) => update({ username: event.target.value })} />
        </label>
        <label>
          Icon URL
          <input value={draft.icon_url} placeholder="https://example.com/icon.png" onChange={(event) => update({ icon_url: event.target.value })} />
        </label>
      </div>
      <div className="action-row wrap">
        <button type="button" disabled={Boolean(busy)} onClick={save}>{busy === 'save' ? 'Saving...' : 'Save Mattermost'}</button>
        <button type="button" className="ghost-button" disabled={Boolean(busy) || !config?.enabled} onClick={sendTest}>
          {busy === 'test' ? 'Sending...' : 'Send Mattermost Test'}
        </button>
      </div>
      {message ? <p className="success-text">{message}</p> : null}
      {error ? <p className="error-text">{error}</p> : null}
    </div>
  );
}


function PlatformIntegrationSettings() {
  const [observability, setObservability] = useState(null);
  const [repo, setRepo] = useState(null);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState('');
  const [testResult, setTestResult] = useState(null);

  const load = async () => {
    setError('');
    try {
      const [observabilityConfig, repoConfig] = await Promise.all([
        apiFetch('/observability/api/v1/config'),
        apiFetch('/repo/api/v1/config'),
      ]);
      setObservability(observabilityConfig);
      setRepo({ ...repoConfig, gitlab: { ...(repoConfig.gitlab || {}), token: '' } });
    } catch (err) {
      setError(err.message);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const updateObservability = (section, patch) => {
    setObservability((current) => ({ ...current, [section]: { ...(current?.[section] || {}), ...patch } }));
  };

  const updateGitLab = (patch) => {
    setRepo((current) => ({ ...current, gitlab: { ...(current?.gitlab || {}), ...patch } }));
  };

  const saveObservability = async () => {
    setBusy('save-observability');
    setMessage('');
    setError('');
    try {
      const next = await apiFetch('/observability/api/v1/config', { method: 'PUT', body: JSON.stringify(observability) });
      setObservability(next);
      setMessage('Prometheus and Elasticsearch settings saved. New agent tool calls use these values immediately.');
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy('');
    }
  };

  const saveRepo = async () => {
    setBusy('save-repo');
    setMessage('');
    setError('');
    try {
      const payload = { gitlab: { ...(repo?.gitlab || {}) } };
      if (!payload.gitlab.token) {
        delete payload.gitlab.token;
      }
      const next = await apiFetch('/repo/api/v1/config', { method: 'PUT', body: JSON.stringify(payload) });
      setRepo({ ...next, gitlab: { ...(next.gitlab || {}), token: '' } });
      setMessage('GitLab settings saved. Repo widgets and supervisor tools use the configured project now.');
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy('');
    }
  };

  const runTest = async (target) => {
    setBusy(`test-${target}`);
    setMessage('');
    setError('');
    try {
      const path = target === 'prometheus'
        ? '/observability/api/v1/test/prometheus'
        : target === 'elasticsearch'
          ? '/observability/api/v1/test/elasticsearch'
          : '/repo/api/v1/test/gitlab';
      const result = await apiFetch(path, { method: 'POST', body: JSON.stringify({}) });
      setTestResult({ target, result });
      setMessage(result.ok ? `${target} connection works.` : `${target} test returned a configuration warning.`);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy('');
    }
  };

  if (!observability || !repo) {
    return (
      <div className="panel span-2">
        <div className="panel-header">
          <div>
            <p className="eyebrow">Data integrations</p>
            <h3>Loading settings</h3>
          </div>
        </div>
        {error ? <p className="error-text">{error}</p> : <p>Reading agent configuration...</p>}
      </div>
    );
  }

  return (
    <div className="panel span-2">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Data integrations</p>
          <h3>Connect Prometheus, Elasticsearch, and GitLab</h3>
        </div>
        <button type="button" className="ghost-button" disabled={Boolean(busy)} onClick={load}>Reload</button>
      </div>
      <p>These settings are stored in the shared config volume and are used by observability-agent, repo-agent, the incident widgets, and the supervisor tools.</p>
      <div className="secret-grid">
        <label>
          Prometheus URL
          <span className="field-hint">Example: http://prometheus:9090 or http://10.0.0.5:9090</span>
          <input value={observability.prometheus?.url || ''} onChange={(event) => updateObservability('prometheus', { url: event.target.value })} />
        </label>
        <label>
          Elasticsearch URL
          <span className="field-hint">Example: http://elasticsearch:9200</span>
          <input value={observability.elasticsearch?.url || ''} onChange={(event) => updateObservability('elasticsearch', { url: event.target.value })} />
        </label>
        <label>
          Elasticsearch index
          <span className="field-hint">Use a wildcard if your logs roll by date.</span>
          <input value={observability.elasticsearch?.index || ''} onChange={(event) => updateObservability('elasticsearch', { index: event.target.value })} />
        </label>
      </div>
      <div className="action-row wrap">
        <button type="button" disabled={Boolean(busy)} onClick={saveObservability}>{busy === 'save-observability' ? 'Saving...' : 'Save Observability'}</button>
        <button type="button" className="ghost-button" disabled={Boolean(busy)} onClick={() => runTest('prometheus')}>{busy === 'test-prometheus' ? 'Testing...' : 'Test Prometheus'}</button>
        <button type="button" className="ghost-button" disabled={Boolean(busy)} onClick={() => runTest('elasticsearch')}>{busy === 'test-elasticsearch' ? 'Testing...' : 'Test Elasticsearch'}</button>
      </div>

      <div className="secret-grid integration-split">
        <label>
          GitLab URL
          <span className="field-hint">Self-managed or SaaS GitLab base URL.</span>
          <input value={repo.gitlab?.url || ''} onChange={(event) => updateGitLab({ url: event.target.value })} />
        </label>
        <label>
          GitLab project ID/path
          <span className="field-hint">Numeric project ID or namespace/project path.</span>
          <input value={repo.gitlab?.default_project || ''} placeholder="group/project or 123456" onChange={(event) => updateGitLab({ default_project: event.target.value })} />
        </label>
        <label>
          GitLab token
          <span className="field-hint">{repo.gitlab?.token_configured ? `configured (${repo.gitlab.token_preview})` : 'not configured'}; leave blank to keep existing.</span>
          <input type="password" value={repo.gitlab?.token || ''} placeholder="glpat-..." onChange={(event) => updateGitLab({ token: event.target.value })} />
        </label>
      </div>
      <div className="action-row wrap">
        <button type="button" disabled={Boolean(busy)} onClick={saveRepo}>{busy === 'save-repo' ? 'Saving...' : 'Save GitLab'}</button>
        <button type="button" className="ghost-button" disabled={Boolean(busy)} onClick={() => runTest('gitlab')}>{busy === 'test-gitlab' ? 'Testing...' : 'Test GitLab'}</button>
      </div>
      {message ? <p className="success-text">{message}</p> : null}
      {error ? <p className="error-text">{error}</p> : null}
      {testResult ? <JsonBlock title={`${testResult.target} test result`} data={testResult.result} /> : null}
    </div>
  );
}

function AlertmanagerIngestionMode({ pollConfig, onSelectMode }) {
  const [mode, setMode] = useState(window.localStorage.getItem('cortex-alertmanager-ingestion-mode') || 'both');

  const choose = async (nextMode) => {
    setMode(nextMode);
    window.localStorage.setItem('cortex-alertmanager-ingestion-mode', nextMode);
    await onSelectMode?.(nextMode);
  };

  const cards = [
    {
      id: 'push',
      title: 'Push webhook',
      badge: 'recommended when Cortex is reachable',
      copy: 'Alertmanager sends every firing/resolved alert directly to Cortex. This is fastest and includes resolved notifications.',
      steps: ['Copy the webhook URL', 'Paste it into Alertmanager receivers', 'Keep send_resolved: true'],
    },
    {
      id: 'pull',
      title: 'Pull API polling',
      badge: 'best when webhooks cannot reach Cortex',
      copy: 'Cortex reads Alertmanager active alerts every 10 seconds and starts the same History -> Supervisor -> Report flow for new alerts.',
      steps: ['Enter Alertmanager URL', 'Enable pull mode', 'Click Poll Now to test'],
    },
    {
      id: 'both',
      title: 'Both modes',
      badge: 'safe migration mode',
      copy: 'Use webhook and polling together while migrating. Cortex deduplicates by event key/idempotency so repeated active alerts are skipped.',
      steps: ['Configure webhook', 'Enable polling', 'Watch duplicates counter'],
    },
  ];

  return (
    <div className="panel integration-card span-2 ingestion-mode-card">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Alert ingestion mode</p>
          <h3>Choose how Cortex gets alerts</h3>
        </div>
        <span className="count-pill">{mode}</span>
      </div>
      <p>
        Cortex supports both push and pull. Push is event-driven from Alertmanager webhooks. Pull asks Alertmanager
        for active alerts every {pollConfig?.interval_seconds || 10}s and ingests new alerts automatically.
      </p>
      <div className="ingestion-mode-grid">
        {cards.map((card) => (
          <article key={card.id} className={mode === card.id ? 'ingestion-mode-option active' : 'ingestion-mode-option'}>
            <div className="panel-header compact">
              <div>
                <p className="eyebrow">{card.badge}</p>
                <h3>{card.title}</h3>
              </div>
              <input type="radio" checked={mode === card.id} onChange={() => choose(card.id)} aria-label={card.title} />
            </div>
            <p>{card.copy}</p>
            <ul>
              {card.steps.map((step) => <li key={step}>{step}</li>)}
            </ul>
            <button type="button" className={mode === card.id ? '' : 'ghost-button'} onClick={() => choose(card.id)}>
              {mode === card.id ? 'Selected' : `Use ${card.title}`}
            </button>
          </article>
        ))}
      </div>
    </div>
  );
}

function AlertmanagerConnection() {
  const stored = (() => {
    try {
      return JSON.parse(window.localStorage.getItem('sre-ai-alertmanager-endpoint') || '{}');
    } catch (_) {
      return {};
    }
  })();
  const [draft, setDraft] = useState(() => ({
    scheme: stored.scheme || window.location.protocol.replace(':', '') || 'http',
    host: stored.host || window.location.hostname || '<server-ip>',
    port: stored.port ?? (window.location.port || '8080'),
    secret: stored.secret || '',
  }));
  const [saved, setSaved] = useState(() => ({ ...draft }));
  const [message, setMessage] = useState(stored.host ? 'Saved endpoint loaded from this browser.' : '');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState('');

  const update = (patch) => setDraft((current) => ({ ...current, ...patch }));
  const endpoint = (values) => `${values.scheme}://${values.host}${values.port ? `:${values.port}` : ''}`;
  const webhookUrl = `${endpoint(saved)}/api/alertmanager/webhook`;
  const draftWebhookUrl = `${endpoint(draft)}/api/alertmanager/webhook`;
  const hasUnsavedChanges = JSON.stringify(draft) !== JSON.stringify(saved);
  const composeReceiver = `receivers:
  - name: sre-ai
    webhook_configs:
      - url: '${webhookUrl}'
        send_resolved: true${saved.secret ? `\n        http_config:\n          authorization:\n            type: Bearer\n            credentials: '${saved.secret}'` : ''}`;
  const curlCommand = `curl -X POST '${webhookUrl}' \\
  -H 'Content-Type: application/json'${saved.secret ? ` \\\n  -H 'Authorization: Bearer ${saved.secret}'` : ''} \\
  -d '{
    "receiver": "sre-ai",
    "status": "firing",
    "alerts": [
      {
        "status": "firing",
        "labels": {
          "alertname": "SREAITestAlert",
          "severity": "critical",
          "service": "checkout",
          "instance": "demo-1"
        },
        "annotations": {
          "summary": "Synthetic Alertmanager alert",
          "description": "This test should ingest an alert and trigger supervisor analysis/report generation."
        },
        "startsAt": "${new Date().toISOString()}",
        "generatorURL": "manual-ui"
      }
    ],
    "groupLabels": {"alertname": "SREAITestAlert"},
    "commonLabels": {"severity": "critical"},
    "commonAnnotations": {"summary": "Synthetic Alertmanager alert"}
  }'`;

  const saveEndpoint = () => {
    setError('');
    if (!draft.host || draft.host === '<server-ip>') {
      setError('Enter the server IP or DNS name that Alertmanager can reach.');
      return;
    }
    const next = { ...draft, port: String(draft.port || '').trim() };
    window.localStorage.setItem('sre-ai-alertmanager-endpoint', JSON.stringify(next));
    setSaved(next);
    setDraft(next);
    setMessage('Alertmanager endpoint saved. YAML and curl examples now use the submitted IP/port.');
  };

  const copyText = async (text, label) => {
    setError('');
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        const textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.setAttribute('readonly', '');
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
      }
      setMessage(`${label} copied.`);
    } catch (err) {
      setError(`Copy failed: ${err.message}`);
    }
  };

  const sendTest = async () => {
    setBusy('test');
    setMessage('');
    setError('');
    try {
      const payload = {
        receiver: 'sre-ai',
        status: 'firing',
        alerts: [
          {
            status: 'firing',
            labels: { alertname: 'SREAITestAlert', severity: 'critical', service: 'checkout', instance: 'ui-test' },
            annotations: {
              summary: 'Synthetic Alertmanager alert',
              description: 'UI test webhook should start History - Supervisor - Report automatically.',
            },
            startsAt: new Date().toISOString(),
            generatorURL: 'sre-ai-ui',
          },
        ],
        groupLabels: { alertname: 'SREAITestAlert' },
        commonLabels: { severity: 'critical' },
        commonAnnotations: { summary: 'Synthetic Alertmanager alert' },
      };
      const result = await fetch('/api/alertmanager/webhook', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(saved.secret ? { Authorization: `Bearer ${saved.secret}` } : {}) },
        body: JSON.stringify(payload),
      });
      if (!result.ok) {
        throw new Error(await result.text());
      }
      setMessage('Test alert accepted. History ingested it and queued the full workflow.');
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy('');
    }
  };

  return (
    <>
      <div className="panel integration-card span-2 alertmanager-card">
        <div className="panel-header">
          <div>
            <p className="eyebrow">Alertmanager</p>
            <h3>Public webhook endpoint</h3>
          </div>
          <StatusChip status={hasUnsavedChanges ? 'open' : 'resolved'} />
        </div>
        <p>Set the IP/DNS and port that your Alertmanager server can reach, then submit the change. The generated URL, YAML, and curl test are rebuilt from the saved endpoint.</p>
        <div className="integration-form-grid">
          <label>
            Scheme
            <select value={draft.scheme} onChange={(event) => update({ scheme: event.target.value })}>
              <option value="http">http</option>
              <option value="https">https</option>
            </select>
          </label>
          <label>
            Server IP / DNS
            <input value={draft.host} onChange={(event) => update({ host: event.target.value.trim() })} placeholder="192.0.2.10 or sre.example.com" />
          </label>
          <label>
            UI/API port
            <input value={draft.port} onChange={(event) => update({ port: event.target.value.trim() })} placeholder="8080, 80, or blank behind HTTPS" />
          </label>
          <label>
            Optional bearer token
            <input type="password" value={draft.secret} onChange={(event) => update({ secret: event.target.value })} placeholder="Only if you protect the webhook" />
          </label>
        </div>
        <div className="endpoint-preview">
          <span>{hasUnsavedChanges ? 'Draft URL' : 'Saved URL'}</span>
          <code>{hasUnsavedChanges ? draftWebhookUrl : webhookUrl}</code>
        </div>
        <div className="action-row wrap">
          <button type="button" onClick={saveEndpoint}>{hasUnsavedChanges ? 'Submit Endpoint Changes' : 'Endpoint Saved'}</button>
          <button type="button" className="ghost-button" onClick={() => copyText(webhookUrl, 'Webhook URL')}>Copy saved URL</button>
          <button type="button" className="ghost-button" disabled={Boolean(busy)} onClick={sendTest}>{busy === 'test' ? 'Sending...' : 'Send Test Alert'}</button>
          <Link className="ghost-button" to="/incidents">Open incidents</Link>
        </div>
        {message ? <p className="success-text">{message}</p> : null}
        {error ? <p className="error-text">{error}</p> : null}
      </div>

      <div className="panel integration-card">
        <div className="panel-header">
          <div>
            <p className="eyebrow">Alertmanager YAML</p>
            <h3>Receiver snippet</h3>
          </div>
          <button type="button" className="ghost-button" onClick={() => copyText(composeReceiver, 'Receiver YAML')}>Copy YAML</button>
        </div>
        <p>Route firing and resolved notifications to `sre-ai`. Keep `send_resolved: true` so Cortex closes incidents when Alertmanager resolves them.</p>
        <pre>{composeReceiver}</pre>
      </div>

      <div className="panel integration-card">
        <div className="panel-header">
          <div>
            <p className="eyebrow">Manual check</p>
            <h3>curl test</h3>
          </div>
          <button type="button" className="ghost-button" onClick={() => copyText(curlCommand, 'curl command')}>Copy curl</button>
        </div>
        <pre>{curlCommand}</pre>
      </div>
    </>
  );
}

function AlertmanagerPollingSettings({ config, setConfig }) {
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState('');
  const [pollResult, setPollResult] = useState(null);

  const load = async () => {
    setError('');
    try {
      const next = await apiFetch('/history/alertmanager/poll/config');
      setConfig(next);
    } catch (err) {
      setError(err.message);
    }
  };

  useEffect(() => {
    load();
    const timer = window.setInterval(() => {
      apiFetch('/history/alertmanager/poll/status')
        .then((status) => setConfig((current) => ({ ...(current || {}), status })))
        .catch(() => {});
    }, 5000);
    return () => window.clearInterval(timer);
  }, []);

  const update = (patch) => setConfig((current) => ({ ...(current || {}), ...patch }));

  const save = async () => {
    setBusy('save');
    setMessage('');
    setError('');
    try {
      const payload = {
        enabled: Boolean(config.enabled),
        url: config.url,
        interval_seconds: Number(config.interval_seconds || 10),
        timeout_seconds: Number(config.timeout_seconds || 10),
        verify_tls: Boolean(config.verify_tls),
        proxy_url: config.proxy_url || '',
      };
      const next = await apiFetch('/history/alertmanager/poll/config', { method: 'PUT', body: JSON.stringify(payload) });
      setConfig(next);
      setMessage('Alertmanager API polling saved. History-agent will check active alerts on this interval.');
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy('');
    }
  };

  const runNow = async () => {
    setBusy('run');
    setMessage('');
    setError('');
    try {
      const result = await apiFetch('/history/alertmanager/poll/run', { method: 'POST', body: JSON.stringify({}) });
      setPollResult(result);
      setConfig((current) => ({ ...(current || {}), status: result }));
      setMessage(result.last_error ? `Poll finished with error: ${result.last_error}` : `Poll finished. Seen ${result.last_seen_alerts}, ingested ${result.last_ingested}, duplicates ${result.duplicates}.`);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy('');
    }
  };

  if (!config) {
    return (
      <div className="panel integration-card span-2">
        <div className="panel-header">
          <div>
            <p className="eyebrow">Alertmanager API polling</p>
            <h3>Loading poller config</h3>
          </div>
        </div>
        {error ? <p className="error-text">{error}</p> : <p>Reading history-agent poller settings...</p>}
      </div>
    );
  }

  const status = config.status || {};

  return (
    <div className="panel integration-card span-2 alertmanager-poll-card">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Alertmanager API polling</p>
          <h3>Pull active alerts every {config.interval_seconds || 10}s</h3>
        </div>
        <StatusChip status={config.enabled ? (status.last_error ? 'failed' : 'resolved') : 'open'} />
      </div>
      <p>
        Enable this when Alertmanager cannot send webhooks to Cortex. History-agent calls
        <code> /api/v2/alerts</code>, ingests only new active alerts by event key, and then queues the normal
        Supervisor - Report workflow.
      </p>
      <div className="secret-grid">
        <label className="toggle-row">
          <input type="checkbox" checked={Boolean(config.enabled)} onChange={(event) => update({ enabled: event.target.checked })} />
          Enable pull mode
        </label>
        <label>
          Alertmanager URL
          <span className="field-hint">Example: https://alert.dr-msh.snpb.app or http://alertmanager:9093</span>
          <input value={config.url || ''} onChange={(event) => update({ url: event.target.value.trim() })} />
        </label>
        <label>
          Poll interval seconds
          <input type="number" min="5" max="300" value={config.interval_seconds || 10} onChange={(event) => update({ interval_seconds: event.target.value })} />
        </label>
        <label>
          Timeout seconds
          <input type="number" min="1" max="60" value={config.timeout_seconds || 10} onChange={(event) => update({ timeout_seconds: event.target.value })} />
        </label>
        <label>
          Proxy URL
          <span className="field-hint">Optional. Example: http://185.255.89.232:5070</span>
          <input value={config.proxy_url || ''} onChange={(event) => update({ proxy_url: event.target.value.trim() })} />
        </label>
        <label className="toggle-row">
          <input type="checkbox" checked={Boolean(config.verify_tls)} onChange={(event) => update({ verify_tls: event.target.checked })} />
          Verify HTTPS certificate
        </label>
      </div>
      <div className="action-row wrap">
        <button type="button" disabled={Boolean(busy)} onClick={save}>{busy === 'save' ? 'Saving...' : 'Save Polling'}</button>
        <button type="button" className="ghost-button" disabled={Boolean(busy)} onClick={runNow}>{busy === 'run' ? 'Polling...' : 'Poll Now'}</button>
        <button type="button" className="ghost-button" disabled={Boolean(busy)} onClick={load}>Reload</button>
      </div>
      <div className="commander-strip">
        <div><span>Poller</span><strong>{status.running ? 'running' : 'stopped'}</strong></div>
        <div><span>Last seen</span><strong>{status.last_seen_alerts ?? 0}</strong></div>
        <div><span>Ingested</span><strong>{status.last_ingested ?? 0}</strong></div>
        <div><span>Duplicates</span><strong>{status.duplicates ?? 0}</strong></div>
      </div>
      {status.last_error ? <p className="error-text">{status.last_error}</p> : null}
      {message ? <p className="success-text">{message}</p> : null}
      {error ? <p className="error-text">{error}</p> : null}
      {pollResult ? <JsonBlock title="Latest poll result" data={pollResult} /> : null}
    </div>
  );
}

function IntegrationPage() {
  const [alertmanagerPollConfig, setAlertmanagerPollConfig] = useState(null);

  const chooseAlertmanagerMode = async (mode) => {
    if (!alertmanagerPollConfig) return;
    const shouldEnablePull = mode === 'pull' || mode === 'both';
    if (Boolean(alertmanagerPollConfig.enabled) === shouldEnablePull) return;
    const payload = {
      enabled: shouldEnablePull,
      url: alertmanagerPollConfig.url,
      interval_seconds: Number(alertmanagerPollConfig.interval_seconds || 10),
      timeout_seconds: Number(alertmanagerPollConfig.timeout_seconds || 10),
      verify_tls: Boolean(alertmanagerPollConfig.verify_tls),
      proxy_url: alertmanagerPollConfig.proxy_url || '',
    };
    const next = await apiFetch('/history/alertmanager/poll/config', { method: 'PUT', body: JSON.stringify(payload) });
    setAlertmanagerPollConfig(next);
  };

  return (
    <section className="page-grid integrations-page">
      <div className="hero-card span-2 integrations-hero">
        <div className="hero-copy">
          <p className="eyebrow">Integrations</p>
          <h3>Connect the whole incident loop</h3>
          <p>
            Configure ingress, chat delivery, observability data, and source-control context from one place. Saved settings are used by the agents immediately where backend config exists.
          </p>
        </div>
        <WorkflowRail trace={[
          { name: 'alertmanager.webhook', status: 'ok' },
          { name: 'observability.think', status: 'ok' },
          { name: 'repo.think', status: 'ok' },
          { name: 'mattermost.report', status: 'ok' },
        ]} />
      </div>

      <AlertmanagerIngestionMode pollConfig={alertmanagerPollConfig} onSelectMode={chooseAlertmanagerMode} />
      <AlertmanagerConnection />
      <AlertmanagerPollingSettings config={alertmanagerPollConfig} setConfig={setAlertmanagerPollConfig} />
      <MattermostIntegration />
      <PlatformIntegrationSettings />
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

  const updatePrompt = (agent, value) => {
    setDraft((current) => ({
      ...current,
      prompts: { ...(current.prompts || {}), [agent]: value },
    }));
  };

  const updateProviderSetting = (provider, key, value) => {
    setDraft((current) => ({
      ...current,
      provider_settings: {
        ...(current.provider_settings || {}),
        [provider]: {
          ...((current.provider_settings || {})[provider] || {}),
          [key]: value,
        },
      },
    }));
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
          <p className="eyebrow">Cortex Models</p>
          <h3>Live model routing per agent</h3>
          <p>Switch providers, models, and prompts without rebuilding containers. Supervisor remains the Cortex commander while tool agents report evidence back to it.</p>
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
              <textarea
                rows="9"
                value={(draft.prompts || {})[agent] || SYSTEM_PROMPTS[agent] || ''}
                onChange={(event) => updatePrompt(agent, event.target.value)}
                placeholder="Write the system prompt this agent sends to its model"
              />
              <span className="field-hint">Saved with the model route and used on the next LLM call.</span>
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
            <p className="eyebrow">Provider networking</p>
            <h3>Base URLs and proxies</h3>
          </div>
          <button type="button" className="ghost-button" onClick={save}>Save Provider Settings</button>
        </div>
        <p>
          Route LLM provider traffic through a proxy when the server cannot reach the provider directly. OpenRouter is
          prefilled with `http://185.255.89.232:5070`; clear the field to disable the proxy.
        </p>
        <div className="secret-grid">
          {Object.entries(draft.provider_settings || {}).map(([provider, settings]) => (
            <div key={provider} className="copy-card provider-settings-card">
              <div className="panel-header compact">
                <div>
                  <p className="eyebrow">{providerLabel(provider)}</p>
                  <h3>{settings.default_model || 'default model'}</h3>
                </div>
              </div>
              <label>
                API base URL
                <input
                  value={settings.base_url || ''}
                  onChange={(event) => updateProviderSetting(provider, 'base_url', event.target.value)}
                  placeholder="https://provider.example/v1"
                />
              </label>
              <label>
                HTTP/SOCKS proxy URL
                <input
                  value={settings.proxy_url || ''}
                  onChange={(event) => updateProviderSetting(provider, 'proxy_url', event.target.value)}
                  placeholder="Leave empty for direct provider access"
                />
              </label>
            </div>
          ))}
        </div>
      </div>

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
        <Route path="/how-it-works" element={<HowItWorksPage />} />
        <Route path="/workflow" element={<WorkflowTestPage />} />
        <Route path="/integrations" element={<IntegrationPage />} />
        <Route path="/incidents" element={<IncidentsPage />} />
        <Route path="/incidents/:incidentId" element={<IncidentDetailPage />} />
        <Route path="/agents" element={<AgentsPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Routes>
    </Shell>
  );
}
