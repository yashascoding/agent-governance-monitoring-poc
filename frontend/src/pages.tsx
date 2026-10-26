import { useCallback, useEffect, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import {
  Activity,
  ArrowRight,
  ArrowUpRight,
  Check,
  CheckCircle2,
  ChevronRight,
  ExternalLink,
  FileText,
  Filter,
  FlaskConical,
  LockKeyhole,
  Plus,
  RefreshCw,
  Search,
  ShieldAlert,
  ShieldCheck,
  WalletCards,
  X,
  XCircle,
} from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, messageFromError, type Alert, type Application, type EventRecord, type User } from "./api";
import { useSession } from "./session";

type Page<T> = { items: T[]; total: number; limit: number; offset: number };
type Execution = {
  id: string; agent_id: string; application_id?: string | null; status: string;
  started_at: string; completed_at?: string | null; duration_seconds?: string | null; timing_mode: string;
  events?: EventRecord[]; alerts?: Alert[];
};
type Dashboard = {
  total_executions: number; total_alerts: number; open_high_alerts: number;
  pending_approvals: number; policy_violations: number;
  recent_executions: Execution[]; recent_alerts: Alert[];
  recent_decisions: Array<{ id: string; application_id: string; decision: string; reason: string; decided_at: string }>;
};

function date(value?: string | null) {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? value : new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(parsed);
}
function money(amount: string | number) {
  return new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 2 }).format(Number(amount));
}
function Severity({ value }: { value: string }) {
  return <span className={`severity severity-${value.toLowerCase()}`}><i />{value}</span>;
}
function Status({ value }: { value: string }) {
  const cls = value.toLowerCase().replaceAll("_", "-");
  return <span className={`status-tag status-${cls}`}>{value.replaceAll("_", " ")}</span>;
}
function PageHeading({ eyebrow, title, description, action }: { eyebrow?: string; title: string; description?: string; action?: ReactNode }) {
  return <div className="page-heading"><div>{eyebrow && <div className="eyebrow">{eyebrow}</div>}<h1>{title}</h1>{description && <p>{description}</p>}</div>{action && <div className="heading-action">{action}</div>}</div>;
}
function Panel({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <section className={`panel ${className}`}>{children}</section>;
}
function PanelTitle({ title, subtitle, action }: { title: string; subtitle?: string; action?: React.ReactNode }) {
  return <div className="panel-title"><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>{action}</div>;
}
function Loading({ label = "Loading data" }: { label?: string }) {
  return <div className="loading-state"><span className="spinner" />{label}…</div>;
}
function Empty({ title, note, icon: Icon = FileText }: { title: string; note: string; icon?: typeof FileText }) {
  return <div className="empty-state"><div className="empty-icon"><Icon size={22} /></div><b>{title}</b><span>{note}</span></div>;
}
function ErrorState({ error, retry }: { error: string; retry?: () => void }) {
  return <div className="error-state"><ShieldAlert size={19} /><span>{error}</span>{retry && <button className="text-button" onClick={retry}>Try again</button>}</div>;
}
function StatCard({ label, value, note, icon: Icon, tone = "blue" }: { label: string; value: string | number; note: string; icon: typeof Activity; tone?: string }) {
  return <div className="stat-card"><div className={`stat-icon tone-${tone}`}><Icon size={18} /></div><div className="stat-label">{label}</div><div className="stat-value">{value}</div><div className="stat-note">{note}</div></div>;
}
function useFetch<T>(url: string, reload = 0) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try { const response = await api.get<T>(url); setData(response.data); }
    catch (cause) { setError(messageFromError(cause)); }
    finally { setLoading(false); }
  }, [url]);
  useEffect(() => { void load(); }, [load, reload]);
  return { data, error, loading, reload: load };
}
function ExecutionLink({ id, children }: { id: string; children?: React.ReactNode }) {
  return <Link className="mono-link" to={`/executions/${id}`}>{children ?? id.slice(0, 8)} <ArrowUpRight size={13} /></Link>;
}

export function LoginPage({ onLogin }: { onLogin: (user: User) => void }) {
  const [email, setEmail] = useState("approver@example.com");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true); setError("");
    try {
      const { data } = await api.post<{ access_token: string; user: User }>("/auth/login", { email, password });
      sessionStorage.setItem("access_token", data.access_token);
      onLogin(data.user);
      navigate("/", { replace: true });
    } catch (cause) { setError(messageFromError(cause)); }
    finally { setBusy(false); }
  };
  return <div className="login-screen">
    <div className="login-decoration"><div className="login-grid" /><div className="login-brand"><div className="brand-mark"><ShieldCheck size={21} /></div><div><strong>sentinel</strong><small>AGENT GOVERNANCE</small></div></div>
      <div className="login-copy"><div className="eyebrow">TRUST, WITH EVIDENCE</div><h1>Make every agent<br />decision <em>accountable.</em></h1><p>Independent policy monitoring for autonomous agents. Observe decisions, review evidence, and keep humans in control.</p>
        <div className="login-proof"><div><ShieldCheck size={17} /><span>Policy enforcement</span></div><div><Activity size={17} /><span>Live execution evidence</span></div><div><LockKeyhole size={17} /><span>Human approval controls</span></div></div>
      </div><div className="login-footnote">LOCAL DEMO ENVIRONMENT <span>·</span> NO REAL FINANCIAL TRANSACTIONS</div>
    </div>
    <div className="login-form-side"><form className="login-card" onSubmit={(event) => void submit(event)}>
      <div className="eyebrow">WELCOME BACK</div><h2>Sign in to Sentinel</h2><p className="login-subtitle">Use your governance workspace account.</p>
      {error && <ErrorState error={error} />}
      <label>Email address<input type="email" required autoComplete="username" value={email} onChange={(event) => setEmail(event.target.value)} /></label>
      <label>Password<input type="password" required autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} /></label>
      <button className="primary-button login-submit" disabled={busy}>{busy ? <><span className="spinner spinner-light" /> Signing in…</> : <>Sign in <ArrowRight size={16} /></>}</button>
      <div className="login-demo-note"><LockKeyhole size={15} /><span>Demo accounts are configured by the operator in the local <code>.env</code>.</span></div>
    </form><div className="login-copyright">Sentinel Governance Console · Secure local access</div></div>
  </div>;
}

export function DashboardPage() {
  const { data, error, loading, reload } = useFetch<Dashboard>("/dashboard");
  return <>
    <PageHeading eyebrow="MONITORING OVERVIEW" title="Good morning" description="A live view of agent activity, human approvals, and governance health." action={<button className="secondary-button" onClick={() => void reload()}><RefreshCw size={15} /> Refresh</button>} />
    {error && <ErrorState error={error} retry={() => void reload()} />}
    {loading || !data ? <div className="stats-grid">{[1, 2, 3, 4, 5].map((n) => <div className="stat-skeleton" key={n} />)}</div> : <>
      <div className="stats-grid">
        <StatCard label="Agent executions" value={data.total_executions} note="Persisted workflow runs" icon={Activity} />
        <StatCard label="Governance alerts" value={data.total_alerts} note="All monitored findings" icon={ShieldAlert} tone="amber" />
        <StatCard label="Open high severity" value={data.open_high_alerts} note="Requires investigation" icon={AlertTriangleIcon} tone="red" />
        <StatCard label="Pending approvals" value={data.pending_approvals} note="Waiting for an approver" icon={WalletCards} tone="violet" />
        <StatCard label="Policy violations" value={data.policy_violations} note="Human approval policy" icon={ShieldCheck} tone="green" />
      </div>
      <div className="dashboard-grid">
        <Panel><PanelTitle title="Recent agent executions" subtitle="Latest persistent execution records" action={<Link className="panel-link" to="/agents">All agents <ArrowRight size={14} /></Link>} />
          {data.recent_executions.length === 0 ? <Empty title="No executions yet" note="Submit a loan application or run a controlled test scenario." icon={Activity} /> :
            <div className="table-wrap"><table><thead><tr><th>AGENT / RUN</th><th>STATUS</th><th>STARTED</th><th /></tr></thead><tbody>{data.recent_executions.map((run) => <tr key={run.id}><td><div className="agent-cell"><div className="table-icon"><Activity size={15} /></div><div><b>{run.agent_id}</b><small className="mono">{run.id.slice(0, 12)}</small></div></div></td><td><Status value={run.status} /></td><td>{date(run.started_at)}</td><td><ExecutionLink id={run.id} /></td></tr>)}</tbody></table></div>}
        </Panel>
        <Panel><PanelTitle title="Recent alerts" subtitle="Monitoring findings backed by event evidence" action={<Link className="panel-link" to="/alerts">View feed <ArrowRight size={14} /></Link>} />
          {data.recent_alerts.length === 0 ? <Empty title="No alerts to review" note="The governance engine is monitoring agent workflows." icon={ShieldCheck} /> :
            <div className="alert-list">{data.recent_alerts.map((alert) => <Link to={`/alerts/${alert.id}`} className="alert-row" key={alert.id}><Severity value={alert.severity} /><div className="alert-row-copy"><b>{alert.rule_name}</b><small>{alert.agent_id} · {date(alert.created_at)}</small></div><ChevronRight size={16} /></Link>)}</div>}
        </Panel>
      </div>
      <Panel className="decisions-panel"><PanelTitle title="Recent human decisions" subtitle="Approval decisions captured with an integrity signature" />
        {data.recent_decisions.length === 0 ? <Empty title="No decisions recorded" note="Eligible applications will appear in the approval queue." icon={ShieldCheck} /> :
          <div className="table-wrap"><table><thead><tr><th>APPLICATION</th><th>DECISION</th><th>REASON</th><th>RECORDED</th></tr></thead><tbody>{data.recent_decisions.map((decision) => <tr key={decision.id}><td><Link className="mono-link" to={`/applications/${decision.application_id}`}>{decision.application_id.slice(0, 12)} <ArrowUpRight size={13} /></Link></td><td><Status value={decision.decision} /></td><td className="truncate">{decision.reason}</td><td>{date(decision.decided_at)}</td></tr>)}</tbody></table></div>}
      </Panel>
    </>}
  </>;
}
const AlertTriangleIcon = ShieldAlert;

export function AlertsPage() {
  const { notify } = useSession();
  const [severity, setSeverity] = useState("");
  const [rule, setRule] = useState("");
  const [agent, setAgent] = useState("");
  const [status, setStatus] = useState("");
  const [sort, setSort] = useState("newest");
  const [reloadKey, setReloadKey] = useState(0);
  const [connection, setConnection] = useState<"connecting" | "connected" | "disconnected">("connecting");
  const query = new URLSearchParams({ sort });
  if (severity) query.set("severity", severity);
  if (rule) query.set("rule_id", rule);
  if (agent) query.set("agent_id", agent);
  if (status) query.set("status", status);
  const { data, error, loading, reload } = useFetch<Page<Alert>>(`/alerts?${query}`, reloadKey);
  useEffect(() => {
    const token = sessionStorage.getItem("access_token");
    const controller = new AbortController();
    let reconnectTimer = 0;
    const connect = async () => {
      while (!controller.signal.aborted) {
        try {
          const response = await fetch("/api/alerts/stream", {
            headers: token ? { Authorization: `Bearer ${token}` } : {},
            signal: controller.signal,
          });
          if (!response.ok || !response.body) throw new Error("Live alert stream is unavailable");
          setConnection("connected");
          setReloadKey((key) => key + 1);
          const reader = response.body.getReader();
          const decoder = new TextDecoder();
          let pending = "";
          while (!controller.signal.aborted) {
            const { value, done } = await reader.read();
            if (done) break;
            pending += decoder.decode(value, { stream: true });
            const messages = pending.split("\n\n");
            pending = messages.pop() ?? "";
            for (const message of messages) {
              const dataLine = message.split("\n").find((line) => line.startsWith("data: "));
              if (dataLine) {
                try { const alert = JSON.parse(dataLine.slice(6)) as Alert; notify(`New ${alert.severity.toLowerCase()} alert · ${alert.rule_name}`, "error"); setReloadKey((key) => key + 1); }
                catch { /* Ignore malformed stream frames and keep the connection alive. */ }
              }
            }
          }
          if (!controller.signal.aborted) throw new Error("Alert stream disconnected");
        } catch {
          if (controller.signal.aborted) return;
          setConnection("disconnected");
          await new Promise<void>((resolve) => { reconnectTimer = window.setTimeout(resolve, 3000); });
          setConnection("connecting");
        }
      }
    };
    void connect();
    return () => { controller.abort(); window.clearTimeout(reconnectTimer); };
  }, [notify]);
  const refresh = () => { setReloadKey((key) => key + 1); };
  return <>
    <PageHeading eyebrow="GOVERNANCE MONITORING" title="Live alert feed" description="Findings are generated from persisted agent events and linked evidence." action={<div className={`stream-state stream-${connection}`}><span className="pulse-dot" />{connection === "connected" ? "LIVE STREAM CONNECTED" : connection === "connecting" ? "RECONNECTING…" : "STREAM DISCONNECTED"}</div>} />
    <Panel className="filter-panel"><div className="filter-heading"><Filter size={15} /><b>Filter findings</b></div><div className="filters">
      <label>Severity<select value={severity} onChange={(e) => setSeverity(e.target.value)}><option value="">All severities</option>{["CRITICAL", "HIGH", "MEDIUM", "LOW"].map((v) => <option key={v}>{v}</option>)}</select></label>
      <label>Rule<select value={rule} onChange={(e) => setRule(e.target.value)}><option value="">All rules</option>{["RULE-LOAN-001", "RULE-TASK-001", "RULE-DATA-001"].map((v) => <option key={v}>{v}</option>)}</select></label>
      <label>Agent<input placeholder="Filter agent…" value={agent} onChange={(e) => setAgent(e.target.value)} /></label>
      <label>Status<select value={status} onChange={(e) => setStatus(e.target.value)}><option value="">All statuses</option>{["OPEN", "ACKNOWLEDGED", "RESOLVED"].map((v) => <option key={v}>{v}</option>)}</select></label>
      <label>Sort<select value={sort} onChange={(e) => setSort(e.target.value)}><option value="newest">Newest first</option><option value="oldest">Oldest first</option><option value="severity">Severity</option></select></label>
      <button className="secondary-button filter-refresh" onClick={refresh} aria-label="Refresh alerts"><RefreshCw size={15} /></button>
    </div></Panel>
    <Panel><PanelTitle title="Governance findings" subtitle={data ? `${data.total} matching alert${data.total === 1 ? "" : "s"}` : "Persisted alerts with monitor evidence"} />
      {loading ? <Loading label="Loading alerts" /> : error ? <ErrorState error={error} retry={() => void reload()} /> : !data || data.items.length === 0 ? <Empty title="No matching alerts" note="Try changing the filters, or run one of the controlled governance scenarios." icon={ShieldCheck} /> :
        <div className="table-wrap"><table><thead><tr><th>SEVERITY / RULE</th><th>AGENT / EXECUTION</th><th>STATUS</th><th>DETECTED</th><th /></tr></thead><tbody>{data.items.map((item) => <tr key={item.id}>
          <td><div className="severity-cell"><Severity value={item.severity} /><small>{item.rule_id}</small></div></td><td><div><b>{item.agent_id}</b><small className="mono">{item.execution_id.slice(0, 14)}</small></div></td><td><Status value={item.status} /></td><td>{date(item.created_at)}</td><td><Link className="table-action" to={`/alerts/${item.id}`}>Inspect <ArrowRight size={14} /></Link></td>
        </tr>)}</tbody></table></div>}
    </Panel>
  </>;
}

export function AlertDetailPage() {
  const { alertId = "" } = useParams();
  const { user, notify } = useSession();
  const { data, error, loading, reload } = useFetch<Alert & { events: EventRecord[] }>(`/alerts/${alertId}`);
  const [busy, setBusy] = useState(false);
  const changeStatus = async (next: "ACKNOWLEDGED" | "RESOLVED") => {
    if (next === "RESOLVED" && !window.confirm("Resolve this governance alert? The status change will be recorded.")) return;
    setBusy(true);
    try { await api.patch(`/alerts/${alertId}`, { status: next }); notify(`Alert ${next.toLowerCase()}.`); await reload(); }
    catch (cause) { notify(messageFromError(cause), "error"); }
    finally { setBusy(false); }
  };
  if (loading) return <Loading label="Loading alert evidence" />;
  if (error || !data) return <><PageHeading title="Alert detail" /><ErrorState error={error || "Alert not found"} /></>;
  return <>
    <PageHeading eyebrow={`FINDING · ${data.rule_id}`} title={data.rule_name} description={data.description} action={<Severity value={data.severity} />} />
    <div className="detail-grid">
      <Panel className="detail-main"><PanelTitle title="Evidence events" subtitle={`${data.events.length} event records associated with this finding`} />
        {data.events.length === 0 ? <Empty title="No evidence events" note="The alert is missing linked event records." /> : <div className="timeline">{data.events.map((event) => <EventItem key={event.id} event={event} highlighted={event.event_type.includes("blocked") || event.event_type.includes("denied")} />)}</div>}
      </Panel>
      <div className="detail-rail">
        <Panel><PanelTitle title="Finding context" /><dl className="details-list"><dt>Severity</dt><dd><Severity value={data.severity} /></dd><dt>Status</dt><dd><Status value={data.status} /></dd><dt>Agent</dt><dd>{data.agent_id}</dd><dt>Detected</dt><dd>{date(data.created_at)}</dd><dt>Correlation ID</dt><dd className="mono">{data.correlation_id}</dd></dl>
          <div className="rail-divider" /><h3>Rule</h3><div className="rule-code">{data.rule_id}</div><p className="rail-note">{data.rule_name}</p><div className="rail-divider" /><h3>Evidence summary</h3><pre className="json-block">{JSON.stringify(data.evidence, null, 2)}</pre>
          {user?.role === "APPROVER" && data.status !== "RESOLVED" && <div className="action-stack">{data.status === "OPEN" && <button disabled={busy} className="secondary-button full-button" onClick={() => void changeStatus("ACKNOWLEDGED")}><Check size={15} /> Acknowledge</button>}<button disabled={busy} className="primary-button full-button" onClick={() => void changeStatus("RESOLVED")}><CheckCircle2 size={15} /> Resolve alert</button></div>}
        </Panel>
        <Panel><PanelTitle title="Related execution" /><p className="rail-note">Trace the full chronological execution and its surrounding events.</p><Link className="primary-button full-button" to={`/executions/${data.execution_id}`}>Open timeline <ArrowRight size={15} /></Link>{data.application_id && <Link className="secondary-button full-button rail-button" to={`/applications/${data.application_id}`}>Open application <ExternalLink size={14} /></Link>}</Panel>
      </div>
    </div>
  </>;
}

export function ApplicationsPage() {
  const { notify, user } = useSession();
  const [reloadKey, setReloadKey] = useState(0);
  const [search, setSearch] = useState("");
  const [name, setName] = useState("");
  const [amount, setAmount] = useState("");
  const [purpose, setPurpose] = useState("");
  const [busy, setBusy] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const query = new URLSearchParams();
  if (search) query.set("search", search);
  const { data, error, loading, reload } = useFetch<Page<Application>>(`/applications?${query}`, reloadKey);
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true);
    try {
      const { data: item } = await api.post<Application>("/applications", { applicant_name: name, amount: Number(amount), purpose });
      notify(item.status === "APPROVED" ? "Application processed and automatically approved." : "Application submitted to the human approval queue.");
      setName(""); setAmount(""); setPurpose(""); setShowForm(false); setReloadKey((key) => key + 1);
    } catch (cause) { notify(messageFromError(cause), "error"); }
    finally { setBusy(false); }
  };
  return <>
    <PageHeading eyebrow="LOAN WORKFLOWS" title="Applications" description="Submit and follow applications as the loan agent evaluates policy and approval requirements." action={user?.role === "APPROVER" ? <button className="primary-button" onClick={() => setShowForm(!showForm)}><Plus size={16} /> New application</button> : undefined} />
    {showForm && <Panel className="form-panel"><PanelTitle title="Submit a loan application" subtitle="Amounts below ₹1,000 may be auto-approved. ₹1,000 or more is routed to a human approver." action={<button className="icon-button" onClick={() => setShowForm(false)} aria-label="Close form"><X size={17} /></button>} />
      <form className="application-form" onSubmit={(event) => void submit(event)}><label>Applicant name<input value={name} onChange={(e) => setName(e.target.value)} minLength={2} maxLength={160} required placeholder="e.g. Alex Morgan" /></label><label>Loan amount (INR)<input type="number" value={amount} onChange={(e) => setAmount(e.target.value)} min="0.01" max="9999999999.99" step="0.01" required placeholder="e.g. 500" /></label><label className="form-wide">Purpose<textarea value={purpose} onChange={(e) => setPurpose(e.target.value)} minLength={3} maxLength={500} required placeholder="Briefly describe the loan purpose" /></label><div className="form-actions"><button type="button" className="secondary-button" onClick={() => setShowForm(false)}>Cancel</button><button className="primary-button" disabled={busy}>{busy ? "Submitting…" : "Submit application"} <ArrowRight size={15} /></button></div></form>
    </Panel>}
    <Panel><PanelTitle title="Loan applications" subtitle={data ? `${data.total} applications in the monitoring database` : "Applications and policy outcomes"} action={<div className="search-field"><Search size={15} /><input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search applicant" aria-label="Search applicant" /></div>} />
      {loading ? <Loading /> : error ? <ErrorState error={error} retry={() => void reload()} /> : !data?.items.length ? <Empty title="No applications yet" note="Create a synthetic loan request to see the real agent workflow here." icon={WalletCards} /> :
        <div className="table-wrap"><table><thead><tr><th>APPLICANT</th><th>AMOUNT</th><th>STATUS</th><th>SUBMITTED</th><th>EXECUTION</th><th /></tr></thead><tbody>{data.items.map((item) => <tr key={item.id}><td><Link className="applicant-link" to={`/applications/${item.id}`}>{item.applicant_name}</Link><small className="mono">{item.id.slice(0, 12)}</small></td><td className="amount-cell">{money(item.amount)}</td><td><Status value={item.status} /></td><td>{date(item.created_at)}</td><td><ExecutionLink id={item.execution_id} /></td><td><Link className="table-action" to={`/applications/${item.id}`}>Details <ArrowRight size={14} /></Link></td></tr>)}</tbody></table></div>}
    </Panel>
  </>;
}

export function ApplicationDetailPage() {
  const { applicationId = "" } = useParams();
  const { data, error, loading, reload } = useFetch<Application & { events: EventRecord[] }>(`/applications/${applicationId}`);
  const { user, notify } = useSession();
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const makeDecision = async (decision: "APPROVE" | "REJECT") => {
    if (!reason.trim()) { notify("Enter a decision reason before continuing.", "error"); return; }
    if (!window.confirm(`${decision === "APPROVE" ? "Approve" : "Reject"} this application? This decision is recorded in the audit timeline.`)) return;
    setBusy(true);
    try {
      await api.post(`/applications/${applicationId}/decision`, { decision, reason });
      notify(`Application ${decision.toLowerCase()}d with a verified signature.`);
      setReason(""); await reload();
    } catch (cause) { notify(messageFromError(cause), "error"); }
    finally { setBusy(false); }
  };
  if (loading) return <Loading label="Loading application" />;
  if (error || !data) return <><PageHeading title="Application detail" /><ErrorState error={error || "Application not found"} /></>;
  return <>
    <PageHeading eyebrow="APPLICATION DETAIL" title={data.applicant_name} description={`Application ${data.id}`} action={<Status value={data.status} />} />
    <div className="summary-cards"><div className="summary-card"><span>LOAN AMOUNT</span><b>{money(data.amount)}</b></div><div className="summary-card"><span>POLICY ROUTE</span><b>{Number(data.amount) < 1000 ? "Automatic approval eligible" : "Human approval required"}</b></div><div className="summary-card"><span>SUBMITTED</span><b>{date(data.created_at)}</b></div></div>
    {data.status === "PENDING_APPROVAL" && user?.role === "APPROVER" && <Panel className="decision-panel"><PanelTitle title="Human decision required" subtitle="Your decision will be signed by the backend, verified before finalization, and added to the event timeline." />
      <label>Decision reason<textarea value={reason} onChange={(event) => setReason(event.target.value)} minLength={1} maxLength={2000} required placeholder="Explain the basis for your decision…" /></label>
      <div className="decision-actions"><button disabled={busy || !reason.trim()} className="danger-button" onClick={() => void makeDecision("REJECT")}><XCircle size={16} /> Reject application</button><button disabled={busy || !reason.trim()} className="primary-button" onClick={() => void makeDecision("APPROVE")}><CheckCircle2 size={16} /> Approve with signature</button></div>
    </Panel>}
    {data.status === "PENDING_APPROVAL" && user?.role !== "APPROVER" && <div className="info-callout"><LockKeyhole size={17} /> This application is awaiting an authorized approver. Viewer access cannot decide this application.</div>}
    {data.decision && <Panel className="signature-panel"><div className="signature-icon"><ShieldCheck size={19} /></div><div><b>Signed human decision · {data.decision.signature_verified ? "Verified" : "Verification failed"}</b><p>{data.decision.decision} by {data.decision.reason} · {date(data.decision.decided_at)}</p></div><Status value={data.decision.decision} /></Panel>}
    <div className="detail-grid application-detail-grid"><Panel><PanelTitle title="Agent execution timeline" subtitle={`${data.events.length} persisted events in chronological order`} action={<ExecutionLink id={data.execution_id}>Open full run</ExecutionLink>} />
      {data.events.length ? <div className="timeline">{data.events.map((event) => <EventItem key={event.id} event={event} highlighted={event.event_type.includes("blocked") || event.event_type.includes("denied")} />)}</div> : <Empty title="No recorded events" note="The application execution has no events." />}
    </Panel><div className="detail-rail"><Panel><PanelTitle title="Application details" /><dl className="details-list"><dt>Application ID</dt><dd className="mono">{data.id}</dd><dt>Purpose</dt><dd>{data.purpose}</dd><dt>Execution</dt><dd><ExecutionLink id={data.execution_id} /></dd><dt>Correlation</dt><dd className="mono">{data.id.slice(0, 18)}</dd></dl></Panel></div></div>
  </>;
}

export function ApprovalsPage() {
  const { notify } = useSession();
  const [reloadKey, setReloadKey] = useState(0);
  const [selected, setSelected] = useState<Application | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const { data, error, loading, reload } = useFetch<Application[]>("/approvals", reloadKey);
  const decide = async (decision: "APPROVE" | "REJECT") => {
    if (!selected || !reason.trim()) return;
    if (!window.confirm(`${decision === "APPROVE" ? "Approve" : "Reject"} ${selected.applicant_name}'s application? This decision will be signed and audited.`)) return;
    setBusy(true);
    try {
      await api.post(`/applications/${selected.id}/decision`, { decision, reason });
      notify(`Application ${decision.toLowerCase()}d; signature verified and timeline updated.`);
      setSelected(null); setReason(""); setReloadKey((key) => key + 1);
    } catch (cause) { notify(messageFromError(cause), "error"); }
    finally { setBusy(false); }
  };
  return <>
    <PageHeading eyebrow="HUMAN-IN-THE-LOOP" title="Approval queue" description="Every loan at or above ₹1,000 stays pending until an authorized approver records a signed decision." action={<span className="queue-count"><ShieldCheck size={15} /> {data?.length ?? 0} awaiting review</span>} />
    {error && <ErrorState error={error} retry={() => void reload()} />}
    {loading ? <Loading label="Loading approval requests" /> : !data?.length ? <Panel><Empty title="Queue is clear" note="New applications requiring human approval will appear here." icon={ShieldCheck} /></Panel> :
      <div className="approval-layout"><Panel><PanelTitle title="Pending applications" subtitle="Select an item to review its request and decision context" />
        <div className="queue-list">{data.map((item) => <button className={`queue-item ${selected?.id === item.id ? "queue-selected" : ""}`} key={item.id} onClick={() => { setSelected(item); setReason(""); }}><div className="queue-avatar">{item.applicant_name.slice(0, 1).toUpperCase()}</div><div className="queue-copy"><b>{item.applicant_name}</b><span>{money(item.amount)} · {date(item.created_at)}</span></div><ChevronRight size={17} /></button>)}</div>
      </Panel>{selected && <Panel className="review-panel"><PanelTitle title="Review request" subtitle={selected.applicant_name} action={<Link className="icon-link" to={`/applications/${selected.id}`} aria-label="View application details"><ExternalLink size={16} /></Link>} />
        <div className="review-amount">{money(selected.amount)}<small>REQUESTED AMOUNT</small></div><div className="review-purpose">{selected.purpose}</div><div className="review-meta"><span>POLICY</span><b>Human approval required</b><span>EXECUTION</span><ExecutionLink id={selected.execution_id} /></div>
        <label>Decision reason<textarea value={reason} onChange={(e) => setReason(e.target.value)} required minLength={1} maxLength={2000} placeholder="Add a reason for the decision…" /></label>
        <div className="decision-actions"><button className="danger-button" disabled={busy || !reason.trim()} onClick={() => void decide("REJECT")}><XCircle size={15} /> Reject</button><button className="primary-button" disabled={busy || !reason.trim()} onClick={() => void decide("APPROVE")}><CheckCircle2 size={15} /> Approve</button></div>
        <div className="signed-note"><LockKeyhole size={14} /> Decision is cryptographically signed and independently verified.</div>
      </Panel>}</div>}
  </>;
}

export function AgentsPage() {
  const { data, error, loading, reload } = useFetch<Array<{ id: string; execution_count: number; last_execution: string | null; status: string }>>("/agents");
  const [runs, setRuns] = useState<Execution[]>([]);
  useEffect(() => { api.get<Page<Execution>>("/executions?limit=100").then(({ data: page }) => setRuns(page.items)).catch(() => setRuns([])); }, []);
  return <>
    <PageHeading eyebrow="AGENT INVENTORY" title="Agents & executions" description="Browse monitored agent identities and the persisted runs associated with each one." action={<button className="secondary-button" onClick={() => void reload()}><RefreshCw size={15} /> Refresh</button>} />
    {error && <ErrorState error={error} retry={() => void reload()} />}
    <div className="agent-grid">{loading ? <Loading /> : data?.map((agent) => <Link className="agent-card" to={`/agents/${encodeURIComponent(agent.id)}`} key={agent.id}><div className="agent-card-icon"><Activity size={20} /></div><div className="agent-card-main"><div className="agent-card-title"><h2>{agent.id}</h2><Status value={agent.status} /></div><p>{agent.id.includes("loan") ? "Loan policy evaluation and human approval workflow." : "Controlled governance demonstration fixture."}</p><div className="agent-card-meta"><span><b>{agent.execution_count}</b> executions</span><span>Last run · {date(agent.last_execution)}</span></div></div><ArrowUpRight size={17} /></Link>)}</div>
    <Panel className="agent-runs"><PanelTitle title="Recent executions" subtitle={`${runs.length} latest runs across monitored agents`} />
      {runs.length === 0 ? <Empty title="No runs recorded" note="Run a scenario or create an application to populate timelines." icon={Activity} /> : <div className="table-wrap"><table><thead><tr><th>AGENT</th><th>EXECUTION</th><th>STATUS</th><th>STARTED</th><th>DURATION</th><th /></tr></thead><tbody>{runs.map((run) => <tr key={run.id}><td><b>{run.agent_id}</b></td><td className="mono">{run.id.slice(0, 13)}</td><td><Status value={run.status} /></td><td>{date(run.started_at)}</td><td>{run.duration_seconds ? `${run.duration_seconds}s` : "—"} {run.timing_mode === "simulated" && <span className="simulated-tag">SIMULATED</span>}</td><td><ExecutionLink id={run.id} /></td></tr>)}</tbody></table></div>}
    </Panel>
  </>;
}

export function AgentDetailPage() {
  const { agentId = "" } = useParams();
  const decoded = decodeURIComponent(agentId);
  const { data, error, loading } = useFetch<Page<Execution>>(`/executions?agent_id=${encodeURIComponent(decoded)}`);
  return <>
    <PageHeading eyebrow="AGENT PROFILE" title={decoded} description="Execution history and event timelines for this monitored agent." />
    {loading ? <Loading /> : error ? <ErrorState error={error} /> : !data?.items.length ? <Panel><Empty title="No executions for this agent" note="No runs have been persisted for this identity yet." icon={Activity} /></Panel> :
      <Panel><PanelTitle title="Execution history" subtitle={`${data.total} recorded runs`} /><div className="table-wrap"><table><thead><tr><th>EXECUTION ID</th><th>STATUS</th><th>STARTED</th><th>DURATION</th><th /></tr></thead><tbody>{data.items.map((run) => <tr key={run.id}><td className="mono">{run.id}</td><td><Status value={run.status} /></td><td>{date(run.started_at)}</td><td>{run.duration_seconds ?? "—"} {run.timing_mode === "simulated" && <span className="simulated-tag">SIMULATED</span>}</td><td><ExecutionLink id={run.id}>Inspect timeline</ExecutionLink></td></tr>)}</tbody></table></div></Panel>}
  </>;
}

export function ExecutionPage() {
  const { executionId = "" } = useParams();
  const { data, error, loading } = useFetch<Execution>(`/executions/${executionId}`);
  if (loading) return <Loading label="Loading execution timeline" />;
  if (error || !data) return <><PageHeading title="Execution timeline" /><ErrorState error={error || "Execution not found"} /></>;
  const violationEventIds = new Set(data.alerts?.flatMap((alert) => alert.evidence_event_ids) ?? []);
  return <>
    <PageHeading eyebrow={`EXECUTION · ${data.id.slice(0, 12)}`} title="Agent execution timeline" description={`${data.agent_id} · started ${date(data.started_at)}${data.timing_mode === "simulated" ? " · simulated timing" : ""}`} action={<Status value={data.status} />} />
    <div className="execution-summary"><div><span>EXECUTION ID</span><b className="mono">{data.id}</b></div><div><span>AGENT</span><b>{data.agent_id}</b></div><div><span>APPLICATION</span>{data.application_id ? <Link className="mono-link" to={`/applications/${data.application_id}`}>{data.application_id.slice(0, 14)} <ArrowUpRight size={13} /></Link> : <b>Scenario fixture</b>}</div><div><span>DURATION</span><b>{data.duration_seconds ? `${data.duration_seconds}s` : "—"} {data.timing_mode === "simulated" && <small className="simulated-tag">SIMULATED</small>}</b></div></div>
    {data.alerts?.length ? <div className="violation-banner"><ShieldAlert size={18} /><div><b>{data.alerts.length} governance finding{data.alerts.length === 1 ? "" : "s"} linked to this execution</b><span>Violations are highlighted in context; normal events remain visible below.</span></div>{data.alerts.map((alert) => <Link key={alert.id} to={`/alerts/${alert.id}`} className="banner-link">{alert.rule_id} <ArrowUpRight size={13} /></Link>)}</div> : null}
    <Panel><PanelTitle title="Chronological events" subtitle={`${data.events?.length ?? 0} persisted events · ordered by UTC timestamp`} />
      {!data.events?.length ? <Empty title="No events recorded" note="This execution has an empty event history." icon={FileText} /> : <div className="timeline">{data.events.map((event) => <EventItem key={event.id} event={event} highlighted={violationEventIds.has(event.id) || event.event_type.includes("blocked") || event.event_type.includes("denied")} />)}</div>}
    </Panel>
  </>;
}

function EventItem({ event, highlighted }: { event: EventRecord; highlighted: boolean }) {
  const [expanded, setExpanded] = useState(false);
  return <div className={`timeline-item ${highlighted ? "timeline-violation" : ""}`}><div className="timeline-track"><div className="timeline-marker">{highlighted ? <ShieldAlert size={14} /> : <span />}</div></div><div className="event-card"><div className="event-top"><div><span className="event-type">{event.event_type}</span>{highlighted && <span className="violation-chip">POLICY EVIDENCE</span>}</div><time>{date(event.timestamp)}</time></div><p>{event.action.replaceAll("_", " ")}</p><div className="event-footer"><span>EVENT <code>{event.id.slice(0, 12)}</code></span>{event.decision && <Status value={event.decision} />}<button className="text-button" onClick={() => setExpanded(!expanded)}>{expanded ? "Hide payload" : "Inspect payload"} <ChevronRight className={expanded ? "rotate-icon" : ""} size={14} /></button></div>{expanded && <pre className="json-block event-payload">{JSON.stringify(event.payload, null, 2)}</pre>}</div></div>;
}

const scenarioDefinitions = [
  { id: "normal_auto_approval", title: "Normal automatic approval", short: "A ₹500 request uses the permitted automatic path.", expected: "Loan is automatically approved; no bypass alert." },
  { id: "human_approval", title: "Human-in-the-loop request", short: "A ₹2,000 request is routed to the approver queue.", expected: "Request stays pending until a signed approver decision." },
  { id: "approval_bypass", title: "Human approval bypass attempt", short: "An isolated test fixture attempts to bypass approval for ₹2,000.", expected: "The enforcement boundary blocks it and a HIGH alert is emitted." },
  { id: "abnormal_duration", title: "Abnormal execution duration", short: "A simulated 10-second task is checked against a 300-second baseline.", expected: "Timing is labeled simulated; configured duration rule raises an alert." },
  { id: "unauthorized_resource_access", title: "Unauthorized resource access", short: "A test agent requests a resource outside its permitted allowlist.", expected: "Backend resource boundary denies the request and creates an alert." },
] as const;
type ScenarioId = typeof scenarioDefinitions[number]["id"];
type ScenarioResult = { scenario: string; expected: string; actual: string; passed: boolean; execution_id: string; application_id?: string | null; evidence: string[]; evidence_events: Array<{ id: string; event_type: string; timestamp: string }>; recorded_at: string; alert_ids: string[] };

export function ScenariosPage() {
  const { user, notify } = useSession();
  const [busy, setBusy] = useState<ScenarioId | "">("");
  const [results, setResults] = useState<ScenarioResult[]>([]);
  const run = async (scenario: ScenarioId) => {
    if (user?.role !== "APPROVER") { notify("Approver access is required to run test scenarios.", "error"); return; }
    setBusy(scenario);
    try {
      const { data } = await api.post<ScenarioResult>("/scenarios", { scenario });
      setResults((current) => [data, ...current]);
      notify(data.passed ? "Scenario completed with the expected result." : "Scenario completed but did not meet its expected result.", data.passed ? "success" : "error");
    } catch (cause) { notify(messageFromError(cause), "error"); }
    finally { setBusy(""); }
  };
  return <>
    <PageHeading eyebrow="CONTROLLED VALIDATION" title="Governance test scenarios" description="Run isolated backend workflows and verify the monitor, event evidence, and policy enforcement end to end." />
    {user?.role !== "APPROVER" && <div className="info-callout"><LockKeyhole size={16} /> Scenario execution is restricted to approvers. These controls are enforced by the API.</div>}
    <div className="scenario-grid">{scenarioDefinitions.map((scenario, index) => {
      const result = results.find((item) => item.scenario === scenario.id);
      return <Panel className="scenario-card" key={scenario.id}><div className="scenario-index">0{index + 1}<FlaskConical size={15} /></div><h2>{scenario.title}</h2><p>{scenario.short}</p><div className="scenario-expect"><span>EXPECTED RESULT</span><b>{scenario.expected}</b></div>
        {result && <div className={`scenario-result ${result.passed ? "result-pass" : "result-fail"}`}><div className="scenario-result-head">{result.passed ? <CheckCircle2 size={17} /> : <XCircle size={17} />}<b>{result.passed ? "PASS" : "FAIL"}</b><span>{date(result.recorded_at)}</span></div><p>{result.actual}</p><div className="scenario-evidence"><b>Evidence</b><span>{result.evidence_events.map((event) => `${event.event_type} · ${event.id.slice(0, 8)}`).join(" → ")}</span></div>{result.alert_ids.length > 0 && <div className="scenario-links"><b>Related alerts</b>{result.alert_ids.map((id) => <Link key={id} to={`/alerts/${id}`}>{id.slice(0, 12)} <ArrowUpRight size={13} /></Link>)}</div>}<div className="scenario-links"><b>Execution</b><Link to={`/executions/${result.execution_id}`}>{result.execution_id.slice(0, 14)} <ArrowUpRight size={13} /></Link>{result.application_id && <Link to={`/applications/${result.application_id}`}>Application details <ArrowUpRight size={13} /></Link>}</div></div>}
        <button disabled={!!busy || user?.role !== "APPROVER"} title={user?.role !== "APPROVER" ? "Approver access required" : undefined} className="secondary-button scenario-run" onClick={() => void run(scenario.id)}>{busy === scenario.id ? <><span className="spinner" /> Running…</> : <>Run scenario <ArrowRight size={15} /></>}</button>
      </Panel>;
    })}</div>
    <Panel className="scenario-note"><div className="note-icon"><LockKeyhole size={16} /></div><div><b>Controlled test fixtures only</b><p>Deliberate policy bypasses and resource requests are isolated demonstrations. They cannot finalize an unauthorized loan or read protected data. Simulated duration measurements are marked explicitly and are not production observations.</p></div></Panel>
  </>;
}

export function ForbiddenPage() {
  return <div className="forbidden-state"><div><LockKeyhole size={22} /></div><span className="eyebrow">ACCESS CONTROL</span><h1>Approver access required</h1><p>Your viewer account can inspect dashboards, alerts, applications, evidence, and timelines, but cannot perform approvals or privileged test actions.</p><Link to="/" className="primary-button">Return to overview <ArrowRight size={15} /></Link></div>;
}
