// Screen: Logs — the real application log (DATA_DIR/logs/app.log, or error.log)
// read through api.app_logs(). Filter by level, search, and auto-refresh, with
// errors/warnings colour-coded against the active theme's own tokens so it
// reads cleanly in Porcelain, Noir and Atelier alike.

// Bucket a raw level name onto the four display classes the UI colours by.
function logLevelClass(level) {
  const l = String(level || "").toUpperCase();
  if (l === "ERROR" || l === "CRITICAL") return "error";
  if (l === "WARNING") return "warning";
  if (l === "DEBUG") return "debug";
  return "info";
}

// "2026-06-12 14:32:01,123" -> "2026-06-12 14:32:01" (drop millis).
function logTs(ts) { return String(ts || "").replace(/[.,]\d+$/, ""); }

function LogsScreen() {
  const app = useApp();
  const { t } = app;
  const [source, setSource] = React.useState("app");   // app | error
  const [filter, setFilter] = React.useState("all");   // all | error | warning | info
  const [query, setQuery] = React.useState("");
  const [data, setData] = React.useState(null);        // null = first load
  const [loading, setLoading] = React.useState(false);
  const [auto, setAuto] = React.useState(false);

  const load = React.useCallback((src) => {
    setLoading(true);
    return api.app_logs(src, 800).then((r) => {
      if (r && r.ok) setData(r);
      else setData({ exists: false, entries: [], counts: { total: 0, error: 0, warning: 0, info: 0 }, error: r && r.error });
      setLoading(false);
    });
  }, []);

  React.useEffect(() => { load(source); }, [load, source]);

  // Optional live tail — poll every 5s while enabled.
  React.useEffect(() => {
    if (!auto) return;
    const id = setInterval(() => load(source), 5000);
    return () => clearInterval(id);
  }, [auto, source, load]);

  const counts = (data && data.counts) || { total: 0, error: 0, warning: 0, info: 0 };
  const entries = (data && data.entries) || [];

  // Newest first; then apply the level filter + free-text search.
  const q = query.trim().toLowerCase();
  const rows = entries
    .map((e, i) => ({ ...e, _i: i, cls: logLevelClass(e.level) }))
    .reverse()
    .filter((e) => {
      if (filter === "error" && e.cls !== "error") return false;
      if (filter === "warning" && e.cls !== "warning") return false;
      if (filter === "info" && (e.cls === "error" || e.cls === "warning")) return false;
      if (q && !((e.message || "").toLowerCase().includes(q) ||
                 (e.logger || "").toLowerCase().includes(q) ||
                 (e.level || "").toLowerCase().includes(q))) return false;
      return true;
    });

  const chips = [
    { k: "all", label: t("log.all"), n: counts.total, tone: "" },
    { k: "error", label: t("log.errors"), n: counts.error, tone: "error" },
    { k: "warning", label: t("log.warnings"), n: counts.warning, tone: "warning" },
    { k: "info", label: t("log.info"), n: counts.info, tone: "info" },
  ];

  return (
    <div className="page" data-screen-label="Logs">
      <header className="page-head" style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
        <div>
          <h1 className="page-h">{t("log.title")}</h1>
          <p className="page-sub">{t("log.sub")}</p>
        </div>
        <div className="hstack">
          <Seg
            value={source}
            onChange={setSource}
            options={[{ v: "app", l: t("log.srcApp") }, { v: "error", l: t("log.srcError") }]}
          ></Seg>
          <button className={"btn btn-ghost btn-sm" + (auto ? " on" : "")} onClick={() => setAuto((a) => !a)} aria-pressed={auto}>
            <span className={"dot" + (auto ? " pulse" : "")} style={{ background: auto ? "var(--ok)" : "var(--ink-3)" }}></span>
            {t("log.live")}
          </button>
          <Btn variant="ghost" size="sm" icon="refresh" onClick={() => load(source)} disabled={loading}>{loading ? t("common.running") : t("log.refresh")}</Btn>
        </div>
      </header>

      <Card>
        <div className="log-toolbar">
          <div className="log-chips">
            {chips.map((c) => (
              <button
                key={c.k}
                className={"log-chip" + (c.tone ? " " + c.tone : "") + (filter === c.k ? " on" : "")}
                onClick={() => setFilter(c.k)}
              >
                <span className="log-chip-dot"></span>
                {c.label}
                <span className="log-chip-n">{c.n}</span>
              </button>
            ))}
          </div>
          <div className="log-search">
            <Icon name="search" size={15}></Icon>
            <input className="inp" placeholder={t("log.searchPh")} value={query} onChange={(e) => setQuery(e.target.value)}></input>
            {query ? <button className="copy-btn" onClick={() => setQuery("")} aria-label="Clear" title="Clear"><Icon name="close" size={13}></Icon></button> : null}
          </div>
        </div>

        {data && data.exists === false ? (
          <div className="log-empty">{data.error ? data.error : t("log.noFile")}</div>
        ) : rows.length === 0 ? (
          <div className="log-empty">{entries.length ? t("log.noMatch") : t("log.empty")}</div>
        ) : (
          <div className="log-list">
            {rows.map((e) => (
              <div key={e._i} className={"log-row lvl-" + e.cls}>
                <span className="log-ts mono">{logTs(e.ts)}</span>
                <span className={"log-lvl " + e.cls}>{e.level}</span>
                <span className="log-body">
                  <span className="log-logger mono">{e.logger}</span>
                  <span className="log-text">{e.message}</span>
                </span>
              </div>
            ))}
          </div>
        )}

        <div className="log-foot">
          <span>{t("log.showing")} {rows.length}{rows.length !== entries.length ? " / " + entries.length : ""}</span>
          {data && data.path ? <span className="mono log-path" title={data.path}>{data.path}</span> : null}
        </div>
      </Card>
    </div>
  );
}
Object.assign(window, { LogsScreen });
