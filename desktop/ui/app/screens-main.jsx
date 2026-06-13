// Screens: Dashboard (server + heartbeat + license + fiscal + sign-in + updates)
// and License & Subscription. Wired to the live control-server bridge.

/* ================= DASHBOARD ================= */
function DashboardScreen() {
  const app = useApp();
  const { t, server, hb, lic, fiscal, updates, adminCreds } = app;
  const [showPwd, setShowPwd] = React.useState(false);

  const phase = server.phase;
  const statusTitle =
    phase === "on" ? t("dash.serverOn") :
    phase === "starting" ? t("dash.starting") :
    phase === "stopping" ? t("dash.stopping") : t("dash.serverOff");
  const statusSub = phase === "on" ? t("dash.serverOnSub") : phase === "off" ? t("dash.serverOffSub") : " ";

  return (
    <div className="page" data-screen-label="Dashboard">
      <header className="page-head">
        <h1 className="page-h">{t("dash.title")}</h1>
        <p className="page-sub">{t("dash.sub")}</p>
      </header>

      <div className="g12">
        {/* Server hero */}
        <Card style={{ gridColumn: "span 7", display: "flex", alignItems: "center" }} label="Server control">
          <div className="hero-wrap" style={{ width: "100%" }}>
            <button
              className={"power" + (phase === "on" ? " on" : "") + (phase === "starting" || phase === "stopping" ? " busy" : "")}
              onClick={server.toggle}
              disabled={phase === "starting" || phase === "stopping"}
              aria-label={phase === "on" ? "Stop server" : "Start server"}
            >
              <span className="power-ring"></span>
              <Icon name="power" size={34}></Icon>
            </button>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="hero-status">{statusTitle}</div>
              <div className="hero-sub">{statusSub}</div>
              <div style={{ marginTop: 14 }}>
                <EpRow l={t("dash.local")} v={"http://127.0.0.1:" + app.cfg.port}></EpRow>
                <EpRow l={t("dash.network")} v={"http://" + app.cfg.lanIp + ":" + app.cfg.port}></EpRow>
                <div className="ep-row">
                  <span className="ep-l">{t("dash.uptime")}</span>
                  <span className="ep-v">{phase === "on" ? server.uptimeStr : "—"}</span>
                </div>
              </div>
            </div>
          </div>
        </Card>

        {/* Heartbeat */}
        <Card
          title={t("dash.heartbeat")}
          style={{ gridColumn: "span 5" }}
          action={<Badge tone={hb.online ? "ok" : "muted"} pulse={hb.online}>{hb.online ? t("common.online") : t("common.offline")}</Badge>}
        >
          <div className="kv">
            <KRow l={t("dash.controlCenter")} v={app.cfg.controlHost} mono></KRow>
            <KRow l={t("dash.lastBeat")} v={hb.lastBeatStr} dim={!hb.hasBeat}></KRow>
            <KRow l={t("dash.pending")} v={hb.pending}></KRow>
            <KRow l={t("dash.lastError")} v={hb.lastError || t("common.none")} dim={!hb.lastError}></KRow>
          </div>
          <div style={{ marginTop: 14 }}>
            <Btn variant="ghost" size="sm" icon="refresh" onClick={hb.syncNow} disabled={!hb.canSync}>{t("dash.syncNow")}</Btn>
          </div>
        </Card>

        {/* License */}
        <Card
          title={t("dash.license")}
          style={{ gridColumn: "span 6" }}
          action={<Badge tone={lic.registered ? "ok" : "warn"}>{lic.registered ? t("common.active") : t("common.unregistered")}</Badge>}
        >
          {lic.registered ? (
            <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "4px 36px", alignItems: "end" }}>
              <div>
                <div className="kv-l" style={{ color: "var(--ink-3)", fontSize: 13 }}>{t("dash.balance")}</div>
                <div className="stat-big">{lic.balance}<span className="unit">UZS</span></div>
              </div>
              <div className="kv">
                <KRow l={t("dash.org")} v={lic.org}></KRow>
                <KRow l={t("dash.plan")} v={lic.plan}></KRow>
                <KRow l={t("dash.expires")} v={lic.expires} mono></KRow>
              </div>
              <div style={{ gridColumn: "1 / -1", marginTop: 14 }}>
                <div className="meter"><i style={{ width: lic.pct + "%" }}></i></div>
                <div style={{ display: "flex", justifyContent: "space-between", marginTop: 6, fontSize: 12, color: "var(--ink-3)" }}>
                  <span>{lic.daysLeft} {t("dash.daysLeft")}</span>
                  <button onClick={() => app.nav("license")} style={{ border: 0, background: "none", padding: 0, font: "inherit", fontSize: 12, fontWeight: 600, color: "var(--accent)", cursor: "pointer" }}>{t("common.manage")} →</button>
                </div>
              </div>
            </div>
          ) : (
            <div>
              <div className="kv">
                <KRow l={t("dash.org")} v="—" dim></KRow>
                <KRow l={t("dash.balance")} v="—" dim></KRow>
                <KRow l={t("dash.expires")} v="—" dim></KRow>
              </div>
              <div style={{ marginTop: 14 }}>
                <Btn variant="primary" size="sm" icon="arrow" onClick={() => app.nav("license")}>{t("dash.registerNow")}</Btn>
              </div>
            </div>
          )}
        </Card>

        {/* Fiscalization mini */}
        <Card title={t("dash.fiscal")} style={{ gridColumn: "span 3" }}>
          <div className="kv">
            <KRow l={t("dash.mode")} v={t("fis." + fiscal.mode)}></KRow>
            <KRow l={t("dash.provider")} v={fiscal.provider} mono></KRow>
            <KRow l={t("dash.confirmedFailed")} v={fiscal.confirmed + " / " + fiscal.failed} mono></KRow>
          </div>
          <div style={{ marginTop: 14 }}>
            <Btn variant="ghost" size="sm" onClick={() => app.nav("fiscal")}>{t("common.manage")}</Btn>
          </div>
        </Card>

        {/* POS sign-in (real admin credentials for this PC) */}
        <Card title={t("dash.signin")} style={{ gridColumn: "span 3" }}>
          <div className="kv">
            <KRow l={t("dash.adminEmail")} v={adminCreds.email || "—"} mono></KRow>
            <KRow l={t("dash.password")} v={adminCreds.password ? (showPwd ? adminCreds.password : "••••••••") : "—"} mono></KRow>
          </div>
          <div className="hstack" style={{ marginTop: 14 }}>
            <Btn variant="ghost" size="sm" icon="eye" onClick={() => setShowPwd(!showPwd)} disabled={!adminCreds.password}>{showPwd ? t("dash.hidePwd") : t("dash.showPwd")}</Btn>
            {adminCreds.password ? <CopyBtn text={adminCreds.password}></CopyBtn> : null}
          </div>
        </Card>

        {/* Self-update */}
        <Card
          title={t("upd.title")}
          style={{ gridColumn: "span 12" }}
          action={updates.pending ? <Badge tone="warn">{t("upd.pending")}</Badge> : <Badge tone="ok">v{updates.version}</Badge>}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
            <div className="kv" style={{ flex: 1, minWidth: 260 }}>
              <KRow l={t("upd.version")} v={"v" + updates.version} mono></KRow>
              <KRow l={t("upd.server")} v={updates.url || t("common.none")} mono dim={!updates.url}></KRow>
              <KRow l={t("upd.mode")} v={updates.frozen ? t("upd.installed") : t("upd.dev")}></KRow>
            </div>
            <Btn variant="ghost" icon="arrow" onClick={() => app.nav("updates")}>{t("common.manage")}</Btn>
          </div>
          {updates.pending && <p style={{ margin: "12px 0 0", color: "var(--warn)", fontSize: 13 }}>{t("upd.pendingMsg")}</p>}
        </Card>
      </div>
    </div>
  );
}

/* ================= LICENSE & SUBSCRIPTION ================= */
// Shown only when the control center can't be reached, so the screen still
// communicates what's on offer. Prices are deliberately omitted (rendered as
// "—") — they're authoritative only from the control center, so we never show a
// fabricated figure offline. Real plans replace this the moment
// api.license_plans() returns.
const FALLBACK_PLANS = [
  { id: "starter", name: "Starter", descKey: "lic.p1d", price: null, currency: "UZS", period: "mo" },
  { id: "standard", name: "Standard", descKey: "lic.p2d", price: null, currency: "UZS", period: "mo" },
  { id: "pro", name: "Pro", descKey: "lic.p3d", price: null, currency: "UZS", period: "mo" },
];

// The control center publishes plans verbatim; tolerate the common shapes
// ({plans:[…]}, {results:[…]}, a bare array) and field names so a new field on
// their side never needs a desktop rebuild.
function normalizePlans(data) {
  if (!data) return [];
  const arr = Array.isArray(data) ? data
    : Array.isArray(data.plans) ? data.plans
    : Array.isArray(data.results) ? data.results
    : Array.isArray(data.data) ? data.data : [];
  return arr.map((p, i) => {
    const id = p.id != null ? p.id : (p.plan_id != null ? p.plan_id : (p.code || p.slug || p.name || String(i)));
    const name = p.name || p.title || p.label || p.display_name || String(id);
    const price = [p.price, p.price_uzs, p.monthly_price, p.amount].find((x) => x != null);
    const desc = p.description || p.desc || p.summary || (Array.isArray(p.features) ? p.features.join(" · ") : "");
    return { id: String(id), name: String(name), price, currency: p.currency || "UZS",
             period: p.period || p.interval || p.billing_period || "mo", desc };
  });
}

function fmtPrice(v) {
  if (v == null || v === "") return null;
  const n = typeof v === "number" ? v : Number(String(v).replace(/[^\d.]/g, ""));
  if (!isFinite(n) || n <= 0) return String(v);
  return String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, " ");
}

function LicenseScreen() {
  const app = useApp();
  const { t, lic, hb } = app;
  const [plans, setPlans] = React.useState(null);   // null = still loading
  const [plansFallback, setPlansFallback] = React.useState(false);
  const [sel, setSel] = React.useState(null);
  const [email, setEmail] = React.useState("");
  const [busy, setBusy] = React.useState(false);

  // Match the currently-licensed plan (a name string from the control center)
  // against the loaded catalogue so it can be pre-selected / badged. Compare the
  // FULL trimmed name — splitting on the first word broke multi-word plans like
  // "Standard Plan" (never equal to the untruncated catalogue name).
  const curName = lic.registered ? String(lic.plan || "").trim().toLowerCase() : "";
  const current = (plans || []).find((p) => p.name.toLowerCase() === curName || p.id.toLowerCase() === curName);

  React.useEffect(() => {
    let live = true;
    api.license_plans().then((r) => {
      if (!live) return;
      const got = (r && r.ok) ? normalizePlans(r.data) : [];
      if (got.length) { setPlans(got); setPlansFallback(false); }
      else { setPlans(FALLBACK_PLANS.map((p) => ({ ...p, desc: "" })) ); setPlansFallback(true); }
    });
    return () => { live = false; };
  }, []);

  // Pre-select the active plan once the catalogue is in.
  React.useEffect(() => { if (current) setSel(current.id); }, [current && current.id]);

  const apply = async () => {
    if (!sel || busy) return;
    setBusy(true);
    try {
      if (lic.registered) {
        const r = await api.license_plan_change(sel, "");
        app.toast(r && r.ok ? t("lic.planRequested") : ((r && r.data && r.data.message) || (r && r.error) || t("lic.needsUrl")));
        app.refreshAll();
      } else {
        await app.activateLicense({ email: email, plan: sel });
      }
    } finally { setBusy(false); }
  };

  const planDesc = (p) => p.descKey ? t(p.descKey) : (p.desc || "");
  const applyDisabled = busy || !sel || (lic.registered ? (current && sel === current.id) : !email);

  return (
    <div className="page" data-screen-label="License & Subscription">
      <header className="page-head">
        <h1 className="page-h">{t("lic.title")}</h1>
        <p className="page-sub">{t("lic.sub")}</p>
      </header>

      <div className="stack">
        <Card
          title={t("lic.current")}
          action={<Badge tone={lic.registered ? "ok" : "warn"}>{lic.registered ? t("common.active") : t("common.unregistered")}</Badge>}
        >
          {lic.registered ? (
            <div>
              <div style={{ display: "grid", gridTemplateColumns: "1.2fr 1fr 1.2fr", gap: 36, alignItems: "start" }}>
                <div>
                  <div className="kv-l" style={{ fontSize: 13, color: "var(--ink-3)" }}>{t("dash.org")}</div>
                  <div className="stat-big" style={{ fontSize: 26 }}>{lic.org}</div>
                  <div style={{ color: "var(--ink-3)", fontSize: 13, marginTop: 4 }}>{lic.plan}</div>
                </div>
                <div>
                  <div className="kv-l" style={{ fontSize: 13, color: "var(--ink-3)" }}>{t("dash.balance")}</div>
                  <div className="stat-big" style={{ fontSize: 26 }}>{lic.balance}<span className="unit">UZS</span></div>
                </div>
                <div className="kv">
                  <KRow l={t("dash.expires")} v={lic.expires} mono></KRow>
                  <KRow l={t("lic.heartbeat")} v={hb.hasBeat ? hb.lastBeatStr : "—"} mono={hb.hasBeat} dim={!hb.hasBeat}></KRow>
                </div>
              </div>
              <div style={{ marginTop: 20 }}>
                <div className="meter"><i style={{ width: lic.pct + "%" }}></i></div>
                <div style={{ display: "flex", justifyContent: "space-between", marginTop: 6, fontSize: 12, color: "var(--ink-3)" }}>
                  <span>{lic.daysLeft} {t("dash.daysLeft")}</span>
                  <span className="mono">{lic.expires}</span>
                </div>
              </div>
              {lic.warn && lic.lastMessage ? (
                <div style={{ display: "flex", alignItems: "center", gap: 7, margin: "14px 0 0", color: "var(--warn)", fontSize: 12.5 }}>
                  <Icon name="warn" size={14}></Icon><span style={{ textWrap: "pretty" }}>{lic.lastMessage}</span>
                </div>
              ) : null}
              <div className="hstack" style={{ marginTop: 18 }}>
                <Btn variant="ghost" size="sm" icon="refresh" onClick={hb.syncNow} disabled={!hb.canSync}>{t("lic.syncNow")}</Btn>
                <ConfirmBtn variant="danger" icon="trash" label={t("lic.deactivate")} onConfirm={app.deactivateLicense}></ConfirmBtn>
              </div>
            </div>
          ) : (
            <div className="g2" style={{ alignItems: "end" }}>
              <Field l={t("lic.email")} hint={t("lic.needsUrl")}>
                <input className="inp" placeholder="you@business.uz" value={email} onChange={(e) => setEmail(e.target.value)}></input>
              </Field>
              <div className="kv">
                <KRow l={t("dash.org")} v="—" dim></KRow>
                <KRow l={t("dash.balance")} v="—" dim></KRow>
              </div>
            </div>
          )}
        </Card>

        <Card
          title={t("lic.plansT")}
          action={plansFallback ? <Badge tone="muted">{t("lic.plansOffline")}</Badge> : null}
        >
          <p style={{ margin: "0 0 14px", color: "var(--ink-3)", fontSize: 13 }}>{t("lic.plansHint")}</p>
          {plans === null ? (
            <p style={{ color: "var(--ink-3)", fontSize: 13, margin: "2px 0" }}>{t("lic.plansLoading")}</p>
          ) : (
            <div className="plan-grid">
              {plans.map((p) => {
                const isCur = current && p.id === current.id;
                const price = fmtPrice(p.price);
                return (
                  <button key={p.id} className={"plan" + (sel === p.id ? " sel" : "")} onClick={() => setSel(p.id)}>
                    {isCur && <span className="pl-badge"><Badge tone="ok">{t("lic.currentPlan")}</Badge></span>}
                    <div className="pl-name">{p.name}</div>
                    <div className="pl-desc">{planDesc(p)}</div>
                    <div className="pl-price">
                      {price ? <React.Fragment>{price} {p.currency} <span className="mo">{"/ " + (p.period || t("lic.mo").replace(/^\/\s*/, ""))}</span></React.Fragment> : <span style={{ color: "var(--ink-3)", fontWeight: 400 }}>—</span>}
                    </div>
                  </button>
                );
              })}
            </div>
          )}
          <div style={{ marginTop: 18 }}>
            <Btn variant="primary" icon="arrow" disabled={applyDisabled} onClick={apply}>
              {busy ? t("common.running") : (lic.registered ? t("lic.switch") : t("lic.registerBtn"))}
            </Btn>
          </div>
        </Card>
      </div>
    </div>
  );
}
Object.assign(window, { DashboardScreen, LicenseScreen });
