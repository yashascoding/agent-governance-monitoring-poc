import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  Bell,
  ChevronDown,
  CircleHelp,
  Command,
  FlaskConical,
  LayoutDashboard,
  LogOut,
  Menu,
  ShieldCheck,
  WalletCards,
  X,
} from "lucide-react";
import { Link, Navigate, NavLink, Outlet, Route, Routes, useLocation } from "react-router-dom";
import { api, messageFromError, type User } from "./api";
import { SessionContext, useSession } from "./session";
import {
  AlertDetailPage,
  AlertsPage,
  AgentDetailPage,
  AgentsPage,
  ApplicationDetailPage,
  ApplicationsPage,
  ApprovalsPage,
  DashboardPage,
  ExecutionPage,
  ForbiddenPage,
  LoginPage,
  ScenariosPage,
} from "./pages";

const navigation = [
  { label: "Overview", to: "/", icon: LayoutDashboard, end: true },
  { label: "Live alerts", to: "/alerts", icon: Bell },
  { label: "Applications", to: "/applications", icon: WalletCards },
  { label: "Approval queue", to: "/approvals", icon: ShieldCheck, approverOnly: true },
  { label: "Agents & runs", to: "/agents", icon: Activity },
  { label: "Test scenarios", to: "/scenarios", icon: FlaskConical, approverOnly: true },
];

function Protected({ children }: { children: JSX.Element }) {
  const { user } = useSession();
  const location = useLocation();
  if (user === undefined) return <div className="full-loader"><span className="spinner" />Securing your session…</div>;
  return user ? children : <Navigate to="/login" replace state={{ from: location.pathname }} />;
}

function Shell() {
  const { user, logout } = useSession();
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  const current = useMemo(
    () =>
      navigation.find((item) =>
        item.end ? location.pathname === item.to : location.pathname.startsWith(item.to),
      )?.label ?? (location.pathname.startsWith("/alerts/") ? "Alert evidence" : "Execution detail"),
    [location.pathname],
  );
  return (
    <div className="app-shell">
      <aside className={`sidebar ${menuOpen ? "sidebar-open" : ""}`}>
        <Link to="/" className="brand" onClick={() => setMenuOpen(false)}>
          <div className="brand-mark"><ShieldCheck size={21} /></div>
          <div><strong>sentinel</strong><small>AGENT GOVERNANCE</small></div>
        </Link>
        <div className="workspace-pill"><span className="pulse-dot" /> LOCAL DEMO <ChevronDown size={13} /></div>
        <div className="nav-label">WORKSPACE</div>
        <nav className="side-nav">
          {navigation.filter((item) => !item.approverOnly || user?.role === "APPROVER").map(({ label, to, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end} onClick={() => setMenuOpen(false)} className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}>
              <Icon size={17} strokeWidth={1.8} /><span>{label}</span>
              {label === "Live alerts" && <span className="nav-live">LIVE</span>}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="environment-card"><div className="environment-icon"><Command size={15} /></div><div><b>Governance engine</b><small>Policy set · POL-MON-001</small></div><span className="status-dot" /></div>
          <button className="profile-button" onClick={() => void logout()}>
            <div className="avatar">{user?.email.slice(0, 1).toUpperCase()}</div>
            <div className="profile-copy"><b>{user?.email}</b><small>{user?.role === "APPROVER" ? "Approver" : "Viewer"} access</small></div>
            <LogOut size={16} />
          </button>
        </div>
      </aside>
      {menuOpen && <button className="mobile-scrim" aria-label="Close menu" onClick={() => setMenuOpen(false)} />}
      <main className="main-area">
        <header className="topbar">
          <button className="mobile-menu icon-button" aria-label="Open navigation" onClick={() => setMenuOpen(!menuOpen)}>{menuOpen ? <X size={20} /> : <Menu size={20} />}</button>
          <div className="breadcrumbs"><span>Workspace</span><span className="crumb-slash">/</span><b>{current}</b></div>
          <div className="topbar-right"><div className="live-indicator"><span className="pulse-dot" /> SYSTEM OPERATIONAL</div><Link className="help-link" to="/scenarios"><CircleHelp size={16} /> Demo guide</Link><div className="top-avatar">{user?.email.slice(0, 1).toUpperCase()}</div></div>
        </header>
        <div className="page-wrap"><Outlet /></div>
        <footer className="footer"><span>Sentinel Governance Console <i>·</i> Local demo environment</span><span>Policy engine active <span className="status-dot" /></span></footer>
      </main>
    </div>
  );
}

export default function App() {
  const [user, setUser] = useState<User | null | undefined>(undefined);
  const [toast, setToast] = useState<{ message: string; kind: "success" | "error" } | null>(null);
  useEffect(() => {
    const token = sessionStorage.getItem("access_token");
    if (!token) {
      setUser(null);
      return;
    }
    api.get<User>("/auth/me").then(({ data }) => setUser(data)).catch(() => {
      sessionStorage.removeItem("access_token");
      setUser(null);
    });
  }, []);
  const notify = useCallback((message: string, kind: "success" | "error" = "success") => {
    setToast({ message, kind });
    window.setTimeout(() => setToast(null), 4200);
  }, []);
  const logout = useCallback(async () => {
    sessionStorage.removeItem("access_token");
    setUser(null);
  }, []);
  const context = { user: user ?? null, logout, notify };
  const finishLogin = (next: User) => setUser(next);
  if (user === undefined && sessionStorage.getItem("access_token")) {
    return <div className="full-loader"><span className="spinner" />Securing your session…</div>;
  }
  return (
    <SessionContext.Provider value={context}>
      <Routes>
        <Route path="/login" element={user ? <Navigate to="/" replace /> : <LoginPage onLogin={finishLogin} />} />
        <Route element={<Protected><Shell /></Protected>}>
          <Route index element={<DashboardPage />} />
          <Route path="alerts" element={<AlertsPage />} />
          <Route path="alerts/:alertId" element={<AlertDetailPage />} />
          <Route path="applications" element={<ApplicationsPage />} />
          <Route path="applications/:applicationId" element={<ApplicationDetailPage />} />
          <Route path="approvals" element={user?.role === "APPROVER" ? <ApprovalsPage /> : <ForbiddenPage />} />
          <Route path="agents" element={<AgentsPage />} />
          <Route path="agents/:agentId" element={<AgentDetailPage />} />
          <Route path="executions/:executionId" element={<ExecutionPage />} />
          <Route path="scenarios" element={<ScenariosPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
      {toast && <div className={`toast toast-${toast.kind}`} role="status"><span className="toast-dot" />{toast.message}<button aria-label="Dismiss notification" onClick={() => setToast(null)}><X size={15} /></button></div>}
    </SessionContext.Provider>
  );
}

export { messageFromError };
