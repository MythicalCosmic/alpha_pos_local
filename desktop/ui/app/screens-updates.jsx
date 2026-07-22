// Screen: signed update status, manual check/install, and a focused progress
// window. This stays framework-free React so it can be included in the final
// precompiled UI bundle (no runtime Babel dependency).

function fmtWhen(iso, t) {
  if (!iso) return t("upd.never");
  try { return new Date(iso).toLocaleString(); } catch (e) { return iso; }
}

function fmtBytes(value) {
  const n = Number(value || 0);
  if (!n) return "";
  if (n < 1024 * 1024) return Math.max(1, Math.round(n / 1024)) + " KB";
  return (n / (1024 * 1024)).toFixed(n >= 100 * 1024 * 1024 ? 0 : 1) + " MB";
}

function UpdateProgressWindow({ update, onDismiss, onRetry, t }) {
  const phase = update.phase || "checking";
  const active = !!update.active;
  const failed = phase === "error";
  const complete = phase === "complete";
  const checking = phase === "checking";
  const pct = Math.max(0, Math.min(100, Number(update.progress || 0)));
  const bytes = update.bytesTotal
    ? (fmtBytes(update.bytesDownloaded) + " / " + fmtBytes(update.bytesTotal))
    : "";
  const title = failed ? t("upd.modalFailed")
    : complete ? t("upd.modalCurrent")
    : phase === "restarting" ? t("upd.modalRestarting")
    : t("upd.modalTitle");
  const message = update.message || (checking ? t("upd.modalChecking") : t("upd.modalPreparing"));

  return (
    <div className="update-modal-backdrop" role="presentation">
      <section className={"update-modal" + (failed ? " failed" : "")} role="dialog" aria-modal="true" aria-live="polite" aria-label={title}>
        <div className="update-modal-glow"></div>
        <div className="update-modal-brand">
          <span className="update-modal-mark"><img src="AlphaPOS.png" alt="" /></span>
          <span><b>ALPHA POS</b><small>{t("upd.secureUpdate")}</small></span>
        </div>

        <div className="update-modal-body">
          <div className={"update-orbit" + (failed || complete ? " still" : "")} aria-hidden="true">
            <i></i><i></i><i></i>
            <span className={!failed && !complete ? "has-logo" : ""}>
              {failed ? "!" : complete ? "✓" : <img src="AlphaPOS.png" alt="" />}
            </span>
          </div>
          <h2>{title}</h2>
          <p>{message}</p>

          <div className={"update-progress-track" + (checking ? " indeterminate" : "")}>
            <i style={checking ? null : { width: pct + "%" }}></i>
          </div>
          <div className="update-progress-meta">
            <span>{bytes || (update.targetVersion ? ("v" + update.targetVersion) : t("upd.signedVerified"))}</span>
            <b>{checking ? "" : (pct + "%")}</b>
          </div>
        </div>

        {!active ? (
          <div className="update-modal-actions">
            {failed && update.retryable ? <Btn variant="primary" icon="refresh" onClick={onRetry}>{t("upd.tryAgain")}</Btn> : null}
            <Btn variant="ghost" onClick={onDismiss}>{t("common.close")}</Btn>
          </div>
        ) : (
          <p className="update-modal-note">{t("upd.keepOpen")}</p>
        )}
      </section>
    </div>
  );
}

function UpdatesScreen() {
  const app = useApp();
  const { t, updates: u } = app;
  const [busy, setBusy] = React.useState(false);
  const [showProgress, setShowProgress] = React.useState(false);

  const buildMode = !u.frozen ? t("upd.dev") : (u.enabled ? t("upd.installed") : t("upd.disabledMode"));
  const newAvail = !!(u.available && u.available !== u.version);

  React.useEffect(() => {
    if (u.active) setShowProgress(true);
  }, [u.active]);

  React.useEffect(() => {
    // Poll only while work is moving.  Complete/error state is immutable until
    // the user retries or closes the modal; keeping a 350 ms timer alive there
    // wasted local API/JSON work for every minute the dialog stayed open.
    if (!showProgress || !u.active) return undefined;
    const poll = window.setInterval(() => u.refresh(), 350);
    return () => window.clearInterval(poll);
  }, [showProgress, u.active, u.refresh]);

  const doCheck = async () => {
    setBusy(true);
    try { await u.checkOnly(); } finally { setBusy(false); }
  };
  const doInstall = async () => {
    setBusy(true);
    try {
      const result = await u.install();
      if (result && (result.started || result.busy)) setShowProgress(true);
    } finally {
      setBusy(false);
    }
  };
  const retry = async () => {
    setShowProgress(false);
    await doInstall();
  };

  return (
    <div className="page" data-screen-label="Updates">
      <header className="page-head">
        <h1 className="page-h">{t("nav.updates")}</h1>
        <p className="page-sub">{t("upd.sub")}</p>
      </header>

      <div className="stack">
        <Card
          title={t("upd.current")}
          action={
            u.active ? <Badge tone="warn">{t("upd.installing")}</Badge> :
            u.pending ? <Badge tone="warn">{t("upd.pending")}</Badge> :
            newAvail ? <Badge tone="warn">{t("upd.newAvailable")}</Badge> :
            <Badge tone="ok">{t("upd.upToDate")}</Badge>
          }
        >
          <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "4px 40px", alignItems: "end" }}>
            <div>
              <div className="kv-l" style={{ fontSize: 13, color: "var(--ink-3)" }}>{t("upd.version")}</div>
              <div className="stat-big">v{u.version}</div>
            </div>
            <div className="kv">
              <KRow l={t("upd.mode")} v={buildMode}></KRow>
              <KRow l={t("upd.server")} v={u.url || t("common.none")} mono dim={!u.url}></KRow>
              <KRow l={t("upd.availableV")} v={u.available ? ("v" + u.available) : t("upd.upToDate")} mono={!!u.available}></KRow>
            </div>
          </div>

          <div className="kv" style={{ marginTop: 16 }}>
            <KRow l={t("upd.lastChecked")} v={fmtWhen(u.lastCheckAt, t)} dim={!u.lastCheckAt}></KRow>
            <KRow
              l={t("upd.lastUpdated")}
              v={u.lastUpdateAt ? (fmtWhen(u.lastUpdateAt, t) + (u.lastUpdateVersion ? "  ·  v" + u.lastUpdateVersion : "")) : t("upd.never")}
              dim={!u.lastUpdateAt}
            ></KRow>
          </div>

          {u.lastCheckError ? <p style={{ margin: "10px 0 0", color: "var(--warn)", fontSize: 12.5 }}>{u.lastCheckError}</p> : null}
          {u.pending ? <p style={{ margin: "10px 0 0", color: "var(--warn)", fontSize: 13 }}>{t("upd.pendingMsg")}</p> : null}

          <div className="hstack" style={{ marginTop: 18 }}>
            <Btn variant="ghost" icon="refresh" onClick={doCheck} disabled={busy || u.active}>{busy ? t("upd.checking") : t("upd.checkNow")}</Btn>
            <Btn variant="primary" icon="download" onClick={doInstall} disabled={busy || u.active || !newAvail}>{u.active ? t("upd.installing") : t("upd.installNow")}</Btn>
          </div>
          <p style={{ margin: "12px 0 0", color: "var(--ink-3)", fontSize: 12.5 }}>{t("upd.auto")}</p>
        </Card>

        <Card title={t("upd.history")}>
          {(!u.history || u.history.length === 0) ? (
            <p style={{ color: "var(--ink-3)", fontSize: 13, margin: "2px 0" }}>{t("upd.noHistory")}</p>
          ) : (
            <div className="kv">
              {u.history.slice().reverse().map((h, i) => (
                <KRow key={i} l={fmtWhen(h.at, t)} v={"v" + h.version} mono></KRow>
              ))}
            </div>
          )}
        </Card>
      </div>

      {showProgress ? (
        <UpdateProgressWindow
          update={u}
          t={t}
          onRetry={retry}
          onDismiss={() => setShowProgress(false)}
        />
      ) : null}
    </div>
  );
}
Object.assign(window, { UpdatesScreen });
