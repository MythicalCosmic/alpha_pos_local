// App shell: titlebar, sidebar, routing, theme/language, and the live wiring to
// the control-server bridge (window.api). Replaces the design prototype's
// simulated state with real calls to desktop/bridge.py.

const DIRECTIONS = ["Porcelain", "Noir", "Atelier"];
const ACCENTS = ["#1e6b4c", "#27486e", "#8a4a2c", "#5b4a7a"];

// Live cloud-sync pill labels (self-contained, trilingual — no i18n.js surgery).
const SYNC_L = {
  en: { live: "Sync live", off: "Sync off", down: "Not connected", busy: "Syncing…", pending: "queued", replayPending: "Full cloud replay pending", closePending: "Shift close pending", closeConflict: "Shift close conflict" },
  uz: { live: "Sinx faol", off: "Sinx o‘chiq", down: "Ulanmagan", busy: "Sinxlash…", pending: "navbatda", replayPending: "Bulutni to‘liq qayta olish kutilmoqda", closePending: "Smena yopilishi kutilmoqda", closeConflict: "Smena yopilishida ziddiyat" },
  ru: { live: "Синхр. активна", off: "Синхр. выкл", down: "Нет связи", busy: "Синхр…", pending: "в очереди", replayPending: "Ожидается полная загрузка из облака", closePending: "Закрытие смены ожидается", closeConflict: "Конфликт закрытия смены" },
};

const NAV = [
  { id: "dashboard", icon: "dashboard", l: "nav.dashboard", screen: () => <DashboardScreen /> },
  { id: "legacySales", icon: "receipt", l: "nav.legacySales", screen: () => <LegacySalesScreen /> },
  { id: "license", icon: "license", l: "nav.license", screen: () => <LicenseScreen /> },
  { id: "localAudit", icon: "send", l: "nav.localAudit", screen: () => <LocalTelegramAuditScreen /> },
  // Telegram notifications are now configured + edited on the SERVER (admin
  // panel) — the bot runs server-side, so this per-till page was removed.
  { id: "config", icon: "sliders", l: "nav.config", screen: () => <ConfigScreen /> },
  { id: "tests", icon: "flask", l: "nav.tests", screen: () => <TestsScreen /> },
  { id: "fiscal", icon: "receipt", l: "nav.fiscal", screen: () => <FiscalScreen /> },
  { id: "logs", icon: "logs", l: "nav.logs", screen: () => <LogsScreen /> },
  { id: "updates", icon: "download", l: "nav.updates", screen: () => <UpdatesScreen /> },
];

function fmtClock(d) {
  if (!d) return "—";
  const z = (n) => String(n).padStart(2, "0");
  return z(d.getHours()) + ":" + z(d.getMinutes()) + ":" + z(d.getSeconds());
}
function fmtUptime(s) {
  const z = (n) => String(n).padStart(2, "0");
  return z(Math.floor(s / 3600)) + ":" + z(Math.floor((s % 3600) / 60)) + ":" + z(s % 60);
}
function daysBetween(iso) {
  if (!iso) return null;
  const then = new Date(iso).getTime();
  if (isNaN(then)) return null;
  return Math.max(0, Math.round((then - Date.now()) / 86400000));
}

function App() {
  /* ---------- look (persisted via the bridge) ---------- */
  const [dir, setDirRaw] = React.useState("porcelain");
  const [accent, setAccentRaw] = React.useState(ACCENTS[0]);
  const [lang, setLangRaw] = React.useState("en");
  const prefsLoaded = React.useRef(false);

  React.useEffect(() => {
    api.get_ui_prefs().then((r) => {
      const p = (r && r.prefs) || {};
      if (p.dir) setDirRaw(p.dir);
      if (p.accent) setAccentRaw(p.accent);
      if (p.lang) setLangRaw(p.lang);
      prefsLoaded.current = true;
    });
  }, []);
  const persist = (patch) => { if (prefsLoaded.current) api.set_ui_prefs(patch); };
  const setDir = (v) => { const d = v.toLowerCase(); setDirRaw(d); persist({ dir: d }); };
  const setAccent = (v) => { setAccentRaw(v); persist({ accent: v }); };
  const setLang = (v) => { const l = v.toLowerCase(); setLangRaw(l); persist({ lang: l }); };

  const t = React.useCallback((k) => window.tr(lang, k), [lang]);
  const sl = SYNC_L[lang] || SYNC_L.en;

  React.useEffect(() => { document.documentElement.setAttribute("data-dir", dir); }, [dir]);
  React.useEffect(() => {
    if (dir === "porcelain" && accent) document.documentElement.style.setProperty("--accent", accent);
    else document.documentElement.style.removeProperty("--accent");
  }, [dir, accent]);

  /* ---------- navigation + clock ---------- */
  const [page, setPage] = React.useState("dashboard");
  const [tick, setTick] = React.useState(0);
  React.useEffect(() => {
    const id = setInterval(() => setTick((x) => x + 1), 1000);
    return () => clearInterval(id);
  }, []);

  /* ---------- toasts ---------- */
  const [toasts, setToasts] = React.useState([]);
  const toast = (msg) => {
    const id = Math.random().toString(36).slice(2);
    setToasts((ts) => [...ts, { id, msg }]);
    setTimeout(() => setToasts((ts) => ts.filter((x) => x.id !== id)), 2600);
  };

  /* ---------- live backend state ---------- */
  const [srv, setSrv] = React.useState({ running: false, port: 8000, lan_ip: "127.0.0.1" });
  const [phase, setPhase] = React.useState("off"); // off | starting | on | stopping
  const [lic, setLic] = React.useState(null);
  const [fiscal, setFiscal] = React.useState({ mode: "off", provider: "mock", confirmed: 0, failed: 0 });
  const [creds, setCreds] = React.useState({ email: "", password: "" });
  const [upd, setUpd] = React.useState({ version: "1.0.0", update_url: "", pending: false, frozen: false });
  const [sync, setSync] = React.useState({ enabled: false, pending_count: 0 });
  const [syncBusy, setSyncBusy] = React.useState(false);
  const [tunnel, setTunnel] = React.useState({ enabled: false, ready: false, state: "off" });
  const [orderAudit, setOrderAudit] = React.useState({
    enabled: true, auto_send: true, delivery_state: "pending",
    order_count: 0, record_count: 0, bytes: 0, auto_pending_bytes: 0,
  });
  const [observabilityBusy, setObservabilityBusy] = React.useState("");
  const onSinceRef = React.useRef(null);

  const refreshServer = React.useCallback(() => {
    return api.server_status().then((r) => {
      if (!r || r.ok === false) return;
      setSrv(r);
      setPhase((ph) => (ph === "starting" || ph === "stopping") ? ph : (r.running ? "on" : "off"));
      if (r.running && onSinceRef.current == null) onSinceRef.current = Date.now();
      if (!r.running) onSinceRef.current = null;
    });
  }, []);
  const refreshLicense = React.useCallback(() => api.license_status().then((r) => { if (r && r.license) setLic(r.license); }), []);
  const refreshFiscal = React.useCallback(() => api.fiscal_status().then((r) => { if (r && r.fiscal) setFiscal((f) => ({ ...f, ...r.fiscal })); }), []);
  const refreshCreds = React.useCallback(() => api.admin_credentials().then((r) => { if (r && r.ok) setCreds({ email: r.email, password: r.password }); }), []);
  const refreshUpdates = React.useCallback(() => api.update_status().then((r) => { if (r && r.ok) setUpd(r); }), []);
  const refreshSync = React.useCallback(() => api.sync_status().then((r) => { if (r && r.ok && r.sync) setSync(r.sync); }), []);
  const refreshObservability = React.useCallback(() => Promise.all([
    api.support_tunnel_status(), api.order_audit_status(),
  ]).then(([tunnelResult, auditResult]) => {
    if (tunnelResult && tunnelResult.ok) setTunnel(tunnelResult);
    else if (tunnelResult && tunnelResult.error) setTunnel((old) => ({ ...old, ready: false, state: "error", last_error: tunnelResult.error }));
    if (auditResult && auditResult.ok) setOrderAudit(auditResult);
    else if (auditResult && auditResult.error) setOrderAudit((old) => ({ ...old, delivery_state: "error", last_error: auditResult.error }));
  }), []);
  const refreshAll = React.useCallback(() => {
    refreshServer(); refreshLicense(); refreshFiscal(); refreshCreds(); refreshUpdates(); refreshSync(); refreshObservability();
  }, [refreshServer, refreshLicense, refreshFiscal, refreshCreds, refreshUpdates, refreshSync, refreshObservability]);

  React.useEffect(() => { refreshAll(); }, [refreshAll]);
  // Poll the server status often (drives the power button); the rest slowly.
  React.useEffect(() => {
    if (tick > 0 && tick % 4 === 0) refreshServer();
    if (tick > 0 && tick % 5 === 0) refreshSync();   // ~5s for a "live" sync pill
    if (tick > 0 && tick % 5 === 0) refreshObservability();
    if (tick > 0 && tick % 20 === 0) { refreshLicense(); refreshUpdates(); }
  }, [tick, refreshServer, refreshLicense, refreshUpdates, refreshSync, refreshObservability]);

  /* ---------- server control ---------- */
  const toggleServer = async () => {
    if (phase === "on") {
      setPhase("stopping");
      await api.stop_server();
      onSinceRef.current = null;
      setPhase("off"); refreshServer();
    } else if (phase === "off") {
      setPhase("starting");
      const setup = await api.run_setup();
      if (!setup || !setup.ok) {
        setPhase("off");
        toast((setup && setup.error) || "Setup failed");
        refreshAll();
        return;
      }
      const r = await api.start_server();
      if (r && r.running) { onSinceRef.current = Date.now(); setPhase("on"); toast(t("dash.serverOn")); }
      else { setPhase("off"); toast((r && r.error) || "Start failed"); }
      refreshAll();
    }
  };

  // Manual cloud sync (the "try again" when the live pill shows not-connected).
  const cloudSyncNow = async () => {
    if (syncBusy) return;
    setSyncBusy(true);
    const r = await api.cloud_sync_now();
    setSyncBusy(false);
    refreshSync();
    toast((r && r.ok) ? sl.live + " ✓" : (sl.down + (r && r.error ? ": " + r.error : "")));
  };

  const toggleTunnel = async (on) => {
    if (observabilityBusy) return;
    setObservabilityBusy("tunnel");
    setTunnel((old) => ({ ...old, enabled: on, ready: false, state: on ? "connecting" : "off" }));
    const r = await api.set_support_tunnel_enabled(on);
    setObservabilityBusy("");
    if (r && r.ok) {
      setTunnel(r);
      toast(on ? t("obs.tunnelEnabled") : t("obs.tunnelDisabled"));
    } else {
      setTunnel((old) => ({ ...old, enabled: !on, ready: false, state: "error", last_error: (r && r.error) || "Failed" }));
      toast((r && r.error) || "Failed");
    }
    refreshObservability();
  };

  const toggleAuditCollection = async (on) => {
    if (observabilityBusy) return;
    setObservabilityBusy("audit");
    setOrderAudit((old) => ({ ...old, enabled: on }));
    const r = await api.set_order_audit_enabled(on);
    setObservabilityBusy("");
    if (r && r.ok) {
      setOrderAudit(r);
      toast(on ? t("audit.enabledToast") : t("audit.disabledToast"));
    } else {
      setOrderAudit((old) => ({ ...old, enabled: !on, delivery_state: "error", last_error: (r && r.error) || "Failed" }));
      toast((r && r.error) || "Failed");
    }
  };

  const toggleAuditSend = async (on) => {
    if (observabilityBusy) return;
    setObservabilityBusy("telegram");
    setOrderAudit((old) => ({ ...old, auto_send: on }));
    const r = await api.set_order_audit_auto_send(on);
    setObservabilityBusy("");
    if (r && r.ok) {
      setOrderAudit(r);
      toast(on ? t("audit.autoEnabledToast") : t("audit.autoDisabledToast"));
    } else {
      setOrderAudit((old) => ({ ...old, auto_send: !on, delivery_state: "error", last_error: (r && r.error) || "Failed" }));
      toast((r && r.error) || "Failed");
    }
  };

  const sendAuditNow = async () => {
    if (observabilityBusy) return;
    setObservabilityBusy("send");
    const r = await api.send_order_audit_now();
    setObservabilityBusy("");
    await refreshObservability();
    if (r && (r.ok || r.partial)) toast(r.partial ? t("audit.sentPartial") : t("audit.sent"));
    else toast((r && r.failed && r.failed[0] && r.failed[0].error) || (r && r.error) || t("audit.sendFailed"));
  };

  const uptime = onSinceRef.current ? Math.floor((Date.now() - onSinceRef.current) / 1000) : 0;

  /* ---------- license derived ---------- */
  const registered = !!(lic && lic.status === "ACTIVE");
  const daysLeft = lic ? (lic.days_remaining != null ? lic.days_remaining : daysBetween(lic.expires_at)) : null;
  const pct = daysLeft != null ? Math.max(0, Math.min(100, Math.round((daysLeft / 365) * 100))) : 0;

  const activateLicense = async (over) => {
    const r = await api.license_register(over.email || (lic && lic.email) || "", over.plan || null);
    if (r && r.ok) toast(t("lic.registered")); else toast((r && (r.data && r.data.message)) || t("lic.needsUrl"));
    refreshLicense();
  };
  const deactivateLicense = async () => {
    await api.license_deactivate();
    toast(t("lic.deactivated"));
    refreshLicense();
  };
  const heartbeatNow = async () => {
    const r = await api.license_heartbeat_now();
    toast(r && r.ok ? t("common.justNow") + " · " + t("lic.heartbeat") + " ✓" : t("dash.lastError"));
    refreshLicense();
  };

  /* ---------- fiscal ---------- */
  const setFisMode = async (m) => { setFiscal((f) => ({ ...f, mode: m })); await api.fiscal_set_mode(m); refreshFiscal(); };
  const bumpConfirmed = () => { api.fiscal_test().then(() => refreshFiscal()); };

  const lastBeat = lic && lic.last_heartbeat_at ? new Date(lic.last_heartbeat_at) : null;

  // Control-center host shown on the dashboard, parsed from the real
  // LICENSE_CONTROL_CENTER_URL the bridge reports (no more guessing off the
  // update URL).
  const ccUrl = (lic && lic.control_center_url) || "";
  const controlHost = ccUrl ? ccUrl.replace(/^https?:\/\//, "").replace(/\/.*$/, "") : "—";
  const lastMessage = (lic && lic.last_message) ? lic.last_message : "";
  // The heartbeat card is about the CONTROL CENTER, not the local POS server.
  // Health = a registered, control-center-ACTIVE license; an actual error is
  // only a SUSPENDED/EXPIRED status (last_message then carries the reason).
  // last_message on a healthy beat is just an informational note, so it must
  // NOT surface under the red "Last error" row.
  const licStatus = lic && lic.status;
  const hbWorker = ((srv.workers || {}).heartbeat || {});
  const hbIsError = licStatus === "SUSPENDED" || licStatus === "EXPIRED";
  const hbHealthy = registered && !!hbWorker.alive && !hbWorker.last_error;

  const ctx = {
    t, lang, toast, nav: setPage,
    cfg: { port: srv.port || 8000, lanIp: srv.lan_ip || "127.0.0.1", controlHost },
    server: {
      phase,
      toggle: toggleServer,
      uptimeStr: fmtUptime(uptime),
      error: ((srv.environment || {}).error
        || (srv.database || {}).error
        || (srv.database || {}).warning
        || srv.last_error || ""),
    },
    hb: {
      online: hbHealthy,
      hasBeat: !!lastBeat,
      canSync: registered,            // a manual heartbeat doesn't need the local server
      status: licStatus,
      pending: sync.pending_count || 0,
      alive: !!hbWorker.alive,
      nextIn: hbWorker.next_run_in_s,
      lastBeatStr: lastBeat ? fmtClock(lastBeat) : "—",
      lastError: hbWorker.last_error || (hbIsError ? lastMessage : ""),
      warn: !!(lic && lic.warn),
      syncNow: heartbeatNow,
    },
    lic: {
      registered,
      org: (lic && lic.org_name) || "—",
      plan: (lic && lic.plan) || (registered ? "Licensed" : "—"),
      expires: (lic && lic.expires_at) ? lic.expires_at.slice(0, 10) : "—",
      daysLeft: daysLeft != null ? daysLeft : "—",
      pct,
      balance: (lic && lic.balance != null) ? lic.balance : "—",
      status: lic && lic.status,
      lastMessage,
      warn: !!(lic && lic.warn),
    },
    fiscal: { mode: fiscal.mode, setMode: setFisMode, provider: fiscal.provider || "mock", confirmed: fiscal.confirmed || 0, failed: fiscal.failed || 0, bumpConfirmed },
    adminCreds: creds,
    observability: {
      tunnel, orderAudit, shiftClose: sync.shift_close || {}, busy: observabilityBusy,
      toggleTunnel, toggleAuditCollection, toggleAuditSend, sendAuditNow,
      refresh: refreshObservability,
    },
    updates: {
      version: upd.version, url: upd.update_url, pending: upd.pending, frozen: upd.frozen,
      enabled: upd.enabled, reason: upd.reason,
      active: !!upd.active, phase: upd.phase || "idle", progress: Number(upd.progress || 0),
      message: upd.message || "", bytesDownloaded: Number(upd.bytes_downloaded || 0),
      bytesTotal: Number(upd.bytes_total || 0), targetVersion: upd.target_version,
      retryable: !!upd.retryable,
      lastCheckAt: upd.last_check_at, lastCheckOk: upd.last_check_ok, lastCheckError: upd.last_check_error,
      lastUpdateAt: upd.last_update_at, lastUpdateVersion: upd.last_update_version,
      available: upd.available, history: upd.history || [],
      checkOnly: async () => {
        const r = await api.check_updates_only();
        await refreshUpdates();
        if (r && r.error) toast(r.error);
        else if (r && r.busy) toast(t("upd.checking"));
        else if (r && r.available && r.available !== upd.version) toast(t("upd.newAvailable"));
        else if (r && r.enabled !== false) toast(t("upd.upToDate"));
        return r;
      },
      install: async () => { const r = await api.check_updates_now(); await refreshUpdates(); return r; },
      refresh: refreshUpdates,
    },
    activateLicense, deactivateLicense, refreshAll,
  };

  const active = NAV.find((n) => n.id === page) || NAV[0];

  return (
    <AppCtx.Provider value={ctx}>
      <div className="apb">
        {/* Brand strip only — the native OS window already provides the
            minimize / maximize / close controls, so we don't draw our own. */}
        <div className="titlebar">
          <div className="tb-app"><img className="tb-logo" src="AlphaPOS.png" alt="" />Alpha POS Backend</div>
          <div className="tb-spacer"></div>
          <ObservabilityPills
            tunnel={tunnel} audit={orderAudit} t={t}
            onOpen={() => setPage("dashboard")}
          ></ObservabilityPills>
          <SyncPill sync={sync} busy={syncBusy} onSync={cloudSyncNow} sl={sl}></SyncPill>
        </div>

        <div className="frame">
          <aside className="sidebar">
            <div className="wordmark">
              <img className="wm-logo" src="AlphaPOS.png" alt="Alpha POS" />
              <div className="wm-copy">
                <div className="wm-name">Alpha POS</div>
                <div className="wm-sub">Backend</div>
              </div>
            </div>
            <nav className="nav">
              {NAV.map((n) => (
                <button key={n.id} className={"nav-item" + (n.id === page ? " active" : "")} onClick={() => setPage(n.id)}>
                  <Icon name={n.icon}></Icon>{t(n.l)}
                </button>
              ))}
            </nav>
            <div className="side-foot">
              <div className="side-server">
                <span className="dot" style={{ color: phase === "on" ? "var(--ok)" : "var(--ink-3)", background: "currentColor" }}></span>
                <span style={{ flex: 1 }}>{phase === "on" ? t("common.online") : t("common.offline")}</span>
                {phase === "on" && <span className="mono" style={{ fontSize: 11.5, color: "var(--ink-3)" }}>:{srv.port}</span>}
              </div>
              <div className="lang-seg">
                {["EN", "UZ", "RU"].map((L) => (
                  <button key={L} className={lang === L.toLowerCase() ? "active" : ""} onClick={() => setLang(L)}>{L}</button>
                ))}
              </div>
              <ThemeSwitch dir={dir} setDir={setDir} accent={accent} setAccent={setAccent} t={t}></ThemeSwitch>
              <div className="side-ver">v{upd.version} · single-PC install</div>
            </div>
          </aside>

          <main className="main">
            <React.Fragment key={page + lang}>{active.screen()}</React.Fragment>
          </main>
        </div>

        <div className="toast-wrap">
          {toasts.map((x) => (<div key={x.id} className="toast"><span className="dot"></span>{x.msg}</div>))}
        </div>
      </div>
    </AppCtx.Provider>
  );
}

/* Compact theme switcher in the sidebar foot (replaces the prototype's floating
   tweaks panel). Direction + (for Porcelain) accent. */
function ThemeSwitch({ dir, setDir, accent, setAccent, t }) {
  return (
    <div className="theme-switch">
      <div className="ts-seg">
        {DIRECTIONS.map((d) => (
          <button key={d} className={dir === d.toLowerCase() ? "active" : ""} title={d} onClick={() => setDir(d)}>{d[0]}</button>
        ))}
      </div>
      {dir === "porcelain" && (
        <div className="ts-accents">
          {ACCENTS.map((c) => (
            <button key={c} className={"ts-acc" + (accent === c ? " on" : "")} style={{ background: c }} onClick={() => setAccent(c)} aria-label={"Accent " + c}></button>
          ))}
        </div>
      )}
    </div>
  );
}

/* Live cloud-sync indicator in the titlebar. Green dot = sync enabled + online;
   red = enabled but not reaching the cloud (click to retry); grey = sync off.
   Clicking always runs a manual push+pull (cloud_sync_now). */
function SyncPill({ sync, busy, onSync, sl }) {
  const enabled = !!sync.enabled;
  const online = enabled && !!sync.is_online;
  const close = sync.shift_close || {};
  const closeState = String(close.state || "").toUpperCase();
  const closeConflict = closeState === "CONFLICT" || Number(close.conflict_count || 0) > 0;
  const closePending = !closeConflict && (closeState === "PENDING" || Number(close.pending_count || 0) > 0);
  const replayPending = !!sync.full_pull_pending || String(sync.full_pull_state || "").toLowerCase() === "pending";
  const color = closeConflict ? "#d23b3b" : ((closePending || replayPending) ? "var(--warn)" : (!enabled ? "var(--ink-3)" : (online ? "var(--ok)" : "#d23b3b")));
  const label = busy ? sl.busy : (closeConflict ? sl.closeConflict : (closePending ? sl.closePending : (replayPending ? sl.replayPending : (!enabled ? sl.off : (online ? sl.live : sl.down)))));
  const pending = sync.pending_count || 0;
  const title = [
    label,
    close.message || "",
    replayPending ? sl.replayPending : "",
    pending ? (pending + " " + sl.pending) : "",
    sync.last_pull_error || "",
    sync.last_error || "",
  ].filter((value, index, all) => value && all.indexOf(value) === index).join("   ·   ");
  return (
    <button title={title} onClick={onSync} disabled={busy}
      style={{
        display: "inline-flex", alignItems: "center", gap: 7,
        background: "transparent", border: "1px solid rgba(127,127,127,.28)",
        borderRadius: 999, padding: "4px 11px", marginRight: 4,
        cursor: busy ? "default" : "pointer", font: "inherit", fontSize: 12,
        color: "var(--ink-2, inherit)", opacity: busy ? 0.7 : 1,
      }}>
      <span style={{ width: 8, height: 8, borderRadius: "50%", background: color, transition: "background .3s" }}></span>
      <Icon name="refresh"></Icon>
      <span>{label}</span>
      {pending ? <span className="mono" style={{ opacity: 0.65 }}>· {pending}</span> : null}
    </button>
  );
}

function ObservabilityPills({ tunnel, audit, t, onOpen }) {
  const tunnelTone = tunnel.ready ? "var(--ok)" : (tunnel.enabled ? "var(--warn)" : "var(--ink-3)");
  const auditError = audit.delivery_state === "error" || audit.delivery_state === "configuration_required";
  const auditActive = audit.enabled !== false && audit.auto_send !== false;
  const auditTone = auditError ? "#d23b3b" : (auditActive ? "var(--ok)" : "var(--ink-3)");
  const pill = (key, color, label, title) => (
    <button key={key} title={title} onClick={onOpen}
      style={{
        display: "inline-flex", alignItems: "center", gap: 6,
        background: "transparent", border: "1px solid rgba(127,127,127,.28)",
        borderRadius: 999, padding: "4px 9px", cursor: "pointer",
        font: "inherit", fontSize: 11.5, color: "var(--ink-2, inherit)",
      }}>
      <span style={{ width: 8, height: 8, borderRadius: "50%", background: color }}></span>
      <span>{label}</span>
    </button>
  );
  return (
    <div style={{ display: "inline-flex", gap: 6, marginRight: 8 }}>
      {pill("tunnel", tunnelTone, tunnel.ready ? t("obs.dbReadyShort") : (tunnel.enabled ? t("obs.dbWaitingShort") : t("obs.dbOffShort")), tunnel.last_error || tunnel.last_probe_error || t("obs.tunnelHint"))}
      {pill("audit", auditTone, auditActive ? t("obs.telegramOnShort") : t("obs.telegramOffShort"), audit.last_auto_send_error || audit.last_error || t("obs.auditHint"))}
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App></App>);
