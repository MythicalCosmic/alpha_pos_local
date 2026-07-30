function legacyLocalDate(value) {
  const d = value ? new Date(value) : new Date();
  const z = (n) => String(n).padStart(2, "0");
  return d.getFullYear() + "-" + z(d.getMonth() + 1) + "-" + z(d.getDate());
}

function legacyBusinessDate(offsetDays = 0) {
  const d = new Date();
  if (d.getHours() < 3) d.setDate(d.getDate() - 1);
  d.setDate(d.getDate() + offsetDays);
  return legacyLocalDate(d);
}

function legacyMoney(value, lang) {
  if (value == null || value === "") return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return String(value);
  const locale = lang === "ru" ? "ru-RU" : (lang === "uz" ? "uz-UZ" : "en-US");
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }).format(n);
}

function legacyDateTime(value, lang) {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  const locale = lang === "ru" ? "ru-RU" : (lang === "uz" ? "uz-UZ" : "en-GB");
  return new Intl.DateTimeFormat(locale, {
    day: "2-digit", month: "2-digit", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  }).format(d);
}

function mvpNumber(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

function mvpCompactNumber(value) {
  const n = mvpNumber(value);
  if (Math.abs(n) >= 1000000) return (n / 1000000).toFixed(1) + "M";
  if (Math.abs(n) >= 1000) return Math.round(n / 1000) + "K";
  return String(Math.round(n));
}

function mvpExactAt(date, time) {
  return date && time ? date + "T" + time + ":00+05:00" : null;
}

const MVP_CHART_COLORS = [
  "#6366f1", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6",
  "#ec4899", "#14b8a6", "#f97316", "#06b6d4", "#84cc16",
];

const MVP_TENDER_COLORS = {
  cash: ["rgba(16,185,129,.60)", "#10b981"],
  card: ["rgba(59,130,246,.60)", "#3b82f6"],
  payme: ["rgba(139,92,246,.60)", "#8b5cf6"],
  unknown: ["rgba(244,63,94,.56)", "#f43f5e"],
};

function MvpSymbol({ children }) {
  return <span className="mvp-symbol" aria-hidden="true">{children}</span>;
}

function MvpChart({ kind, labels, datasets, emptyLabel }) {
  const canvas = React.useRef(null);
  const [unavailable, setUnavailable] = React.useState(false);
  const signature = JSON.stringify([kind, labels, datasets]);
  const allZero = !datasets.some((set) => (set.data || []).some((value) => mvpNumber(value) !== 0));
  const empty = !labels.length || (kind === "doughnut" && allZero);

  React.useEffect(() => {
    if (empty || !canvas.current) return undefined;
    if (typeof window.Chart !== "function") {
      setUnavailable(true);
      return undefined;
    }
    setUnavailable(false);
    const isDoughnut = kind === "doughnut";
    const isLine = kind === "line";
    const chart = new window.Chart(canvas.current, {
      type: kind,
      data: { labels, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: isDoughnut ? "65%" : undefined,
        interaction: isDoughnut ? undefined : { intersect: false, mode: "index" },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: "rgba(15, 23, 42, 0.97)",
            padding: 13,
            cornerRadius: 10,
            titleColor: "#fff",
            bodyColor: "#cbd5e1",
          },
        },
        scales: isDoughnut ? undefined : {
          y: {
            beginAtZero: true,
            grid: { color: "rgba(255, 255, 255, 0.04)" },
            border: { display: false },
            ticks: { color: "#7d8ba3", callback: (value) => mvpCompactNumber(value) },
          },
          x: {
            grid: { display: false },
            border: { display: false },
            ticks: { color: "#7d8ba3", maxRotation: isLine ? 38 : 0, autoSkip: true, maxTicksLimit: 9 },
          },
        },
        animation: { duration: 700 },
      },
    });
    return () => chart.destroy();
  }, [signature, empty]);

  if (empty || unavailable) {
    return (
      <div className="mvp-chart-empty">
        <MvpSymbol>monitoring</MvpSymbol>
        <span>{emptyLabel}</span>
      </div>
    );
  }
  return <canvas ref={canvas} role="img" aria-label={emptyLabel}></canvas>;
}

function MvpKpi({ tone, title, icon, value, unit, footer, badge }) {
  return (
    <div className={"mvp-kpi-card " + tone}>
      <div className="mvp-kpi-head">
        <span className="mvp-kpi-title">{title}</span>
        <span className="mvp-kpi-icon"><MvpSymbol>{icon}</MvpSymbol></span>
      </div>
      <div className="mvp-kpi-value">{value}<span>{unit || ""}</span></div>
      <div className="mvp-kpi-foot">
        <span>{footer}</span>
        {badge ? <span className={"mvp-kpi-badge " + (badge.tone || "")}>{badge.text}</span> : null}
      </div>
    </div>
  );
}

function MvpStatus({ tone, icon, value, label }) {
  return (
    <div className={"mvp-status-card " + tone}>
      <span className="mvp-status-icon"><MvpSymbol>{icon}</MvpSymbol></span>
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  );
}

function MvpRows({ rows, empty, render }) {
  return (
    <div className="mvp-data-rows">
      {rows.length ? rows.map((row, index) => (
        <div className="mvp-data-row" key={row.id != null ? row.id : index}>
          {render(row, index)}
        </div>
      )) : <div className="mvp-empty">{empty}</div>}
    </div>
  );
}

function MvpLegend({ rows, total, money, valueKey }) {
  return (
    <div className="mvp-pie-legend">
      {rows.slice(0, 6).map((row, index) => {
        const value = Math.max(0, mvpNumber(row[valueKey]));
        const percentage = total > 0 ? Math.round(value / total * 1000) / 10 : 0;
        return (
          <div className="mvp-legend-item" key={row.id == null ? row.name : row.id}>
            <i style={{ background: MVP_CHART_COLORS[index % MVP_CHART_COLORS.length] }}></i>
            <span title={row.name}>{row.name}</span>
            <b>{valueKey === "revenue" ? money(value) : percentage + "%"}</b>
          </div>
        );
      })}
    </div>
  );
}

function LegacySalesScreen() {
  const { t, lang } = useApp();
  const [fromDate, setFromDate] = React.useState(legacyBusinessDate());
  const [toDate, setToDate] = React.useState(legacyBusinessDate());
  const [fromTime, setFromTime] = React.useState("");
  const [toTime, setToTime] = React.useState("");
  const [preset, setPreset] = React.useState("today");
  const [cashierFilter, setCashierFilter] = React.useState("");
  const [report, setReport] = React.useState(null);
  const [enabled, setEnabled] = React.useState(true);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");
  const requestSequence = React.useRef(0);
  const money = React.useCallback((value) => legacyMoney(value, lang), [lang]);

  const load = React.useCallback((start, end, exactStart, exactEnd) => {
    const sequence = ++requestSequence.current;
    setLoading(true);
    setError("");
    setReport(null);
    return api.legacy_sales_report(start, end, exactStart || null, exactEnd || null).then((result) => {
      if (sequence !== requestSequence.current) return;
      if (!result || result.ok === false) {
        setError((result && result.error) || t("legacy.loadFailed"));
        setReport(null);
      } else if (result.enabled === false) {
        setEnabled(false);
        setReport(null);
      } else {
        setEnabled(true);
        setReport(result.report || null);
      }
      setLoading(false);
    }, () => {
      if (sequence !== requestSequence.current) return;
      setError(t("legacy.loadFailed"));
      setReport(null);
      setLoading(false);
    });
  }, [t]);

  React.useEffect(() => { load(fromDate, toDate, null, null); }, []);

  const chooseRange = (kind, days) => {
    let start;
    let end;
    if (kind === "yesterday") {
      start = legacyBusinessDate(-1);
      end = start;
    } else {
      end = legacyBusinessDate();
      start = legacyBusinessDate(-(days - 1));
    }
    setPreset(kind);
    setFromDate(start);
    setToDate(end);
    setFromTime("");
    setToTime("");
    load(start, end, null, null);
  };

  const applyRange = () => {
    if (!!fromTime !== !!toTime) {
      setError(t("legacy.exactPair"));
      return;
    }
    setPreset("custom");
    load(fromDate, toDate, mvpExactAt(fromDate, fromTime), mvpExactAt(toDate, toTime));
  };

  if (!enabled) {
    return (
      <div className="page mvp-dashboard mvp-disabled">
        <h1>{t("legacy.mvpTitle")}</h1>
        <p>{t("legacy.disabled")}</p>
      </div>
    );
  }

  const summary = (report && report.summary) || {};
  const payments = (report && report.payment_breakdown) || {};
  const drawers = (report && report.active_drawers) || {};
  const quality = (report && report.data_quality) || {};
  const range = (report && report.range) || {};
  const cashiers = (report && report.cashiers) || [];
  const products = (report && report.top_products) || [];
  const categories = (report && report.categories) || [];
  const expenses = (report && report.expenses) || [];
  const recent = (report && report.recent_paid_orders) || [];
  const daily = (report && report.daily) || [];
  const tenderIncomplete = report && quality.tender_attribution_complete !== true;
  const drawerComplete = drawers.complete === true;
  const periodText = range.from && range.to ? range.from + " → " + range.to : t("legacy.selectedRange");
  const visibleCashiers = cashierFilter ? cashiers.filter((row) => String(row.cashier_id) === cashierFilter) : cashiers;
  const bestCashier = cashierFilter ? null : (cashiers[0] || null);

  const productValues = products.map((row) => Math.max(0, mvpNumber(row.quantity)));
  const positiveCategories = categories.filter((row) => mvpNumber(row.revenue) > 0);
  const categoryValues = positiveCategories.map((row) => mvpNumber(row.revenue));
  const productTotal = productValues.reduce((total, value) => total + value, 0);
  const categoryTotal = categoryValues.reduce((total, value) => total + value, 0);
  const unknownTenderValue = payments.unknown == null
    ? quality.unknown_tender_amount
    : payments.unknown;
  const tenderRows = [
    {
      tone: "cash", icon: "payments", title: t("legacy.netCashAllSources"),
      chartLabel: t("legacy.netCash"), value: payments.cash, detail: "",
    },
    {
      tone: "card", icon: "credit_card", title: t("legacy.netCards"),
      chartLabel: t("legacy.netCards"), value: payments.card,
      detail: "UZCARD " + money((payments.card_detail || {}).UZCARD)
        + " · HUMO " + money((payments.card_detail || {}).HUMO)
        + " · CARD " + money((payments.card_detail || {}).CARD),
    },
    {
      tone: "payme", icon: "phone_iphone", title: t("legacy.netPayme"),
      chartLabel: t("legacy.netPayme"), value: payments.payme, detail: "",
    },
  ];
  if (tenderIncomplete || mvpNumber(unknownTenderValue) !== 0) {
    tenderRows.push({
      tone: "unknown", icon: "help", title: t("legacy.unknownNetTender"),
      chartLabel: t("legacy.unknownTenderShort"), value: unknownTenderValue,
      detail: t("legacy.unknownSales") + " " + money(quality.unknown_sale_amount)
        + " · " + t("legacy.unknownRefunds") + " " + money(quality.unknown_refund_amount),
    });
  }
  const tenderValues = tenderRows.map((row) => mvpNumber(row.value));
  const dailyLabels = daily.map((row) => String(row.date || "").slice(5));
  const bestDay = daily.reduce((best, row) => (
    !best || mvpNumber(row.net_revenue) > mvpNumber(best.net_revenue) ? row : best
  ), null);

  return (
    <div className="page mvp-dashboard" data-screen-label="Smart Jowi trusted sales">
      <header className="mvp-header">
        <div>
          <h1>{t("legacy.mvpTitle")}</h1>
          <div className="mvp-header-sub">
            <MvpSymbol>schedule</MvpSymbol>
            <span>{legacyDateTime((report && report.generated_at) || new Date(), lang)}</span>
            <span className="mvp-timezone">Asia/Tashkent (UTC+5)</span>
          </div>
        </div>
        <span className="mvp-readonly"><MvpSymbol>verified</MvpSymbol>{t("legacy.readOnly")}</span>
      </header>

      <div className="mvp-filter-bar">
        <div className="mvp-filter-group">
          {[
            ["today", "today", 1, "today"],
            ["yesterday", "event", 1, "yesterday"],
            ["week", "date_range", 7, "week"],
            ["month", "calendar_month", 30, "month"],
            ["year", "calendar_today", 365, "year"],
          ].map(([key, icon, days, label]) => (
            <button
              key={key}
              className={"mvp-filter-btn " + (preset === key ? "active" : "")}
              onClick={() => chooseRange(key, days)}
              disabled={loading}
            >
              <MvpSymbol>{icon}</MvpSymbol>{t("legacy." + label)}
            </button>
          ))}
        </div>
        <div className="mvp-filter-divider"></div>
        <div className="mvp-date-inputs">
          <label><span>{t("legacy.from")}</span><input type="date" value={fromDate} onChange={(event) => { setFromDate(event.target.value); setPreset("custom"); setReport(null); }} disabled={loading} /></label>
          <input aria-label={t("legacy.fromTime")} title={t("legacy.fromTime")} type="time" value={fromTime} onChange={(event) => { setFromTime(event.target.value); setPreset("custom"); setReport(null); }} disabled={loading} />
          <i>—</i>
          <label><span>{t("legacy.to")}</span><input type="date" value={toDate} onChange={(event) => { setToDate(event.target.value); setPreset("custom"); setReport(null); }} disabled={loading} /></label>
          <input aria-label={t("legacy.toTime")} title={t("legacy.toTime")} type="time" value={toTime} onChange={(event) => { setToTime(event.target.value); setPreset("custom"); setReport(null); }} disabled={loading} />
          <button className="mvp-apply" onClick={applyRange} disabled={loading}>
            <MvpSymbol>{loading ? "hourglass_top" : "refresh"}</MvpSymbol>{t("legacy.apply")}
          </button>
        </div>
      </div>
      <p className="mvp-filter-help">
        <MvpSymbol>info</MvpSymbol>
        <span>{t("legacy.exactWindowHint")}</span>
      </p>

      {error ? <div className="mvp-alert danger"><MvpSymbol>warning</MvpSymbol><span>{error}</span></div> : null}
      {tenderIncomplete ? (
        <div className="mvp-alert warning">
          <MvpSymbol>warning</MvpSymbol>
          <span>
            {t("legacy.unknownTender")}: {t("legacy.unknownSales")} {money(quality.unknown_sale_amount)} UZS · {t("legacy.unknownRefunds")} {money(quality.unknown_refund_amount)} UZS
          </span>
        </div>
      ) : null}

      <div className="mvp-period">
        <MvpSymbol>date_range</MvpSymbol>
        <div>
          <strong>{periodText}</strong>
          {range.start_at ? <span>{legacyDateTime(range.start_at, lang)} — {legacyDateTime(range.end_at, lang)}</span> : null}
        </div>
        <span className="mvp-period-mode">{range.mode === "business" ? "07:00 → 03:00" : t("legacy.exact")}</span>
      </div>

      {loading && !report ? <div className="mvp-loading"><span className="spinner"></span>{t("common.running")}</div> : null}

      {report ? (
        <div className="mvp-report">
          <section className={"mvp-drawer-proof " + (drawerComplete ? "complete" : "incomplete")}>
            <div className="mvp-drawer-head">
              <div>
                <span className="mvp-proof-label">{t("legacy.physicalProof")}</span>
                <h2>{t("legacy.drawerNow")}</h2>
                <p>{t("legacy.drawerHint")}</p>
              </div>
              <div className="mvp-drawer-total">
                <span>{(drawers.shifts || []).length ? (drawerComplete ? t("legacy.expected") : t("legacy.incomplete")) : t("legacy.noActiveShifts")}</span>
                <strong>{drawerComplete ? money(drawers.expected_cash_total) : "—"}{drawerComplete ? <small> UZS</small> : null}</strong>
              </div>
            </div>
            <div className="mvp-drawer-grid">
              {(drawers.shifts || []).length ? drawers.shifts.map((shift) => (
                <div className="mvp-drawer-card" key={shift.shift_id}>
                  <div className="mvp-drawer-name">
                    <strong>{shift.cashier || "—"}</strong>
                    <span className={"mvp-evidence-badge " + (shift.cash_evidence_complete ? "ok" : "bad")}>
                      {shift.cash_evidence_complete ? t("legacy.complete") : t("legacy.incomplete")}
                    </span>
                  </div>
                  <div className="mvp-drawer-money">{shift.expected_cash == null ? "—" : money(shift.expected_cash)}<span>UZS</span></div>
                  <div className="mvp-drawer-meta">{t("legacy.started")}: {legacyDateTime(shift.started_at, lang)}</div>
                  <div className="mvp-drawer-meta">{t("legacy.source")}: {shift.expected_cash_source || "—"}</div>
                </div>
              )) : (
                <div className="mvp-empty">
                  {drawers.available === false ? (drawers.error || t("legacy.drawerUnavailable")) : t("legacy.noActiveShifts")}
                </div>
              )}
            </div>
          </section>

          <div className="mvp-kpi-grid">
            <MvpKpi
              tone="emerald" title={t("legacy.netSales")} icon="payments"
              value={money(summary.net_revenue)} unit="UZS" footer={periodText}
              badge={{ tone: "ok", text: t("legacy.refunds") + " " + money(summary.refund_amount) }}
            />
            <MvpKpi
              tone="blue" title={t("legacy.ordersOpened")} icon="shopping_cart"
              value={summary.orders || 0} footer={t("legacy.paid") + ": " + (summary.paid_orders || 0)}
            />
            <MvpKpi
              tone="violet" title={t("legacy.averagePaid")} icon="trending_up"
              value={money(summary.average_paid_order)} unit="UZS" footer={t("legacy.units") + ": " + (summary.units_sold || 0)}
            />
            <MvpKpi
              tone="amber" title={t("legacy.cashRegister")} icon="account_balance_wallet"
              value={drawerComplete ? money(drawers.expected_cash_total) : "—"} unit={drawerComplete ? "UZS" : ""}
              footer={drawerComplete ? t("legacy.expected") : t("legacy.incomplete")}
              badge={{ tone: drawerComplete ? "ok" : "bad", text: t("legacy.physicalProof") }}
            />
          </div>

          <div className="mvp-status-row">
            <MvpStatus tone="blue" icon="receipt_long" value={summary.orders || 0} label={t("legacy.statusOpened")} />
            <MvpStatus tone="orange" icon="pending" value={summary.open_orders || 0} label={t("legacy.statusOpenFromPeriod")} />
            <MvpStatus tone="green" icon="check_circle" value={summary.paid_orders || 0} label={t("legacy.paid")} />
            <MvpStatus tone="amber" icon="undo" value={summary.refunded_orders || 0} label={t("legacy.statusRefunded")} />
            <MvpStatus tone="red" icon="cancel" value={summary.cancelled_orders || 0} label={t("legacy.cancelled")} />
          </div>

          <div className="mvp-chart-grid">
            <section className="mvp-chart-card">
              <div className="mvp-chart-head">
                <h3><MvpSymbol>pie_chart</MvpSymbol>{t("legacy.productDistribution")}</h3>
                <span className="mvp-chart-badge violet">{productTotal} {t("legacy.shownUnits")}</span>
              </div>
              <p className="mvp-card-note">{t("legacy.productTopTenHint")}</p>
              <div className="mvp-chart-container pie">
                <MvpChart
                  kind="doughnut"
                  labels={products.map((row) => row.name)}
                  datasets={[{
                    data: productValues,
                    backgroundColor: products.map((_, index) => MVP_CHART_COLORS[index % MVP_CHART_COLORS.length]),
                    borderColor: "rgba(0,0,0,.30)", borderWidth: 2, hoverOffset: 10,
                  }]}
                  emptyLabel={t("legacy.noData")}
                />
              </div>
              <MvpLegend rows={products} total={productTotal} money={money} valueKey="quantity" />
            </section>

            <section className="mvp-chart-card">
              <div className="mvp-chart-head">
                <h3><MvpSymbol>donut_small</MvpSymbol>{t("legacy.categoryDistribution")}</h3>
                <span className="mvp-chart-badge emerald">UZS</span>
              </div>
              <p className="mvp-card-note">{t("legacy.categoryPositiveHint")}</p>
              <div className="mvp-chart-container pie">
                <MvpChart
                  kind="doughnut"
                  labels={positiveCategories.map((row) => row.name)}
                  datasets={[{
                    data: categoryValues,
                    backgroundColor: positiveCategories.map((_, index) => MVP_CHART_COLORS[index % MVP_CHART_COLORS.length]),
                    borderColor: "rgba(0,0,0,.30)", borderWidth: 2, hoverOffset: 10,
                  }]}
                  emptyLabel={t("legacy.noData")}
                />
              </div>
              <MvpLegend rows={positiveCategories} total={categoryTotal} money={money} valueKey="revenue" />
            </section>
          </div>

          <section className="mvp-chart-card mvp-full">
            <div className="mvp-chart-head">
              <h3><MvpSymbol>account_balance_wallet</MvpSymbol>{t("legacy.tenderDistribution")}</h3>
              <span className={"mvp-chart-badge " + (tenderIncomplete ? "rose" : "amber")}>
                {tenderIncomplete ? t("legacy.incompleteAttribution") : t("legacy.netOfRefunds")}
              </span>
            </div>
            <p className="mvp-card-note">{t("legacy.tenderHint")}</p>
            <div className="mvp-tender-grid">
              {tenderRows.map((row) => (
                <div className={"mvp-tender-card " + row.tone} key={row.tone}>
                  <span className="mvp-tender-icon"><MvpSymbol>{row.icon}</MvpSymbol></span>
                  <strong>{money(row.value)}<small> UZS</small></strong>
                  <span>{row.title}</span>
                  {row.detail ? <em>{row.detail}</em> : null}
                </div>
              ))}
            </div>
            <div className="mvp-chart-container compact">
              <MvpChart
                kind="bar"
                labels={tenderRows.map((row) => row.chartLabel)}
                datasets={[{
                  data: tenderValues,
                  backgroundColor: tenderRows.map((row) => MVP_TENDER_COLORS[row.tone][0]),
                  borderColor: tenderRows.map((row) => MVP_TENDER_COLORS[row.tone][1]),
                  borderWidth: 2, borderRadius: 8,
                }]}
                emptyLabel={t("legacy.noData")}
              />
            </div>
          </section>

          <div className="mvp-chart-grid">
            <section className="mvp-chart-card">
              <div className="mvp-chart-head">
                <h3><MvpSymbol>show_chart</MvpSymbol>{t("legacy.dailyNet")}</h3>
                <span className="mvp-chart-badge emerald">UZS</span>
              </div>
              <div className="mvp-chart-container">
                <MvpChart
                  kind="line"
                  labels={dailyLabels}
                  datasets={[{
                    label: t("legacy.netSales"),
                    data: daily.map((row) => mvpNumber(row.net_revenue)),
                    borderColor: "#10b981", backgroundColor: "rgba(16,185,129,.12)",
                    borderWidth: 2, fill: true, tension: .38, pointRadius: 4,
                    pointBackgroundColor: "#10b981", pointBorderColor: "#fff", pointBorderWidth: 2,
                  }]}
                  emptyLabel={range.mode === "business" ? t("legacy.noData") : t("legacy.noDailyExact")}
                />
              </div>
            </section>

            <section className="mvp-chart-card">
              <div className="mvp-chart-head">
                <h3><MvpSymbol>analytics</MvpSymbol>{t("legacy.dailyFlow")}</h3>
                <span className="mvp-chart-badge blue">UZS</span>
              </div>
              {bestDay ? (
                <div className="mvp-peak">
                  <span><MvpSymbol>local_fire_department</MvpSymbol></span>
                  <div><small>{t("legacy.bestDay")}</small><strong>{bestDay.date}</strong><em>{money(bestDay.net_revenue)} UZS</em></div>
                </div>
              ) : null}
              <div className="mvp-chart-container compact">
                <MvpChart
                  kind="bar"
                  labels={dailyLabels}
                  datasets={[
                    {
                      label: t("legacy.gross"),
                      data: daily.map((row) => mvpNumber(row.gross_revenue)),
                      backgroundColor: "rgba(99,102,241,.55)", borderColor: "#818cf8",
                      borderWidth: 2, borderRadius: 6,
                    },
                    {
                      label: t("legacy.refunds"),
                      data: daily.map((row) => mvpNumber(row.refund_amount)),
                      backgroundColor: "rgba(245,158,11,.50)", borderColor: "#f59e0b",
                      borderWidth: 2, borderRadius: 6,
                    },
                  ]}
                  emptyLabel={range.mode === "business" ? t("legacy.noData") : t("legacy.noDailyExact")}
                />
              </div>
            </section>
          </div>

          <div className="mvp-three-grid">
            <section className="mvp-chart-card">
              <div className="mvp-cashier-head">
                <h3><MvpSymbol>badge</MvpSymbol>{t("legacy.cashiers")}</h3>
                <select value={cashierFilter} onChange={(event) => setCashierFilter(event.target.value)}>
                  <option value="">{t("legacy.allCashiers")}</option>
                  {cashiers.map((row) => <option value={String(row.cashier_id)} key={row.cashier_id}>{row.cashier_name}</option>)}
                </select>
              </div>
              <p className="mvp-card-note">{t("legacy.cashierHint")}</p>
              {bestCashier ? (
                <div className="mvp-best-cashier">
                  <span className="mvp-best-badge"><MvpSymbol>emoji_events</MvpSymbol>{t("legacy.topCashier")}</span>
                  <span className="mvp-avatar">{String(bestCashier.cashier_name || "?").slice(0, 1)}</span>
                  <div><strong>{bestCashier.cashier_name}</strong><small>{bestCashier.paid_orders || 0} {t("legacy.paid").toLowerCase()}</small></div>
                  <b>{money(bestCashier.net_revenue)}<small> UZS</small></b>
                </div>
              ) : null}
              <MvpRows
                rows={visibleCashiers.slice(0, 10)}
                empty={t("legacy.noData")}
                render={(row) => (
                  <React.Fragment>
                    <div><strong>{row.cashier_name}</strong><span>{row.paid_orders || 0} {t("legacy.paid").toLowerCase()} · {row.refunded_orders || 0} {t("legacy.statusRefunded").toLowerCase()}</span></div>
                    <b>{money(row.net_revenue)}</b>
                  </React.Fragment>
                )}
              />
            </section>

            <section className="mvp-chart-card">
              <div className="mvp-chart-head"><h3><MvpSymbol>inventory_2</MvpSymbol>{t("legacy.topProducts")}</h3></div>
              <div className="mvp-product-total">
                <span><MvpSymbol>shopping_basket</MvpSymbol></span>
                <div><strong>{productTotal}</strong><small>{t("legacy.shownPositiveUnits")}</small></div>
              </div>
              <MvpRows
                rows={products}
                empty={t("legacy.noData")}
                render={(row) => (
                  <React.Fragment>
                    <div><strong>{row.name}</strong><span>{row.quantity} {t("legacy.units").toLowerCase()} · {t("legacy.refunds")} {money(row.refund_amount)}</span></div>
                    <b>{money(row.revenue)}</b>
                  </React.Fragment>
                )}
              />
            </section>

            <section className="mvp-chart-card">
              <div className="mvp-chart-head"><h3><MvpSymbol>fact_check</MvpSymbol>{t("legacy.evidence")}</h3></div>
              <div className={"mvp-quality " + (quality.tender_attribution_complete === true ? "ok" : "bad")}>
                <span>{t("legacy.tenderQuality")}</span>
                <strong>{quality.tender_attribution_complete === true ? t("legacy.complete") : t("legacy.incomplete")}</strong>
              </div>
              <div className="mvp-evidence-list">
                <div><span>{t("legacy.gross")}</span><b>{money(summary.gross_revenue)} UZS</b></div>
                <div><span>{t("legacy.refunds")}</span><b>{money(summary.refund_amount)} UZS</b></div>
                <div><span>{t("legacy.drawerExpenses")}</span><b>{money(summary.cashbox_expenses)} UZS</b></div>
                <div><span>{t("legacy.unknownSales")}</span><b>{money(quality.unknown_sale_amount)} UZS</b></div>
              </div>
              <h4><MvpSymbol>receipt_long</MvpSymbol>{t("legacy.expenses")}</h4>
              <MvpRows
                rows={expenses.slice(0, 4)}
                empty={t("legacy.noExpenses")}
                render={(row) => (
                  <React.Fragment>
                    <div><strong>{row.category || t("legacy.expenses")}</strong><span>{row.cashier_name || "—"} · {legacyDateTime(row.created_at, lang)}</span></div>
                    <b className="amber">{money(row.amount)}</b>
                  </React.Fragment>
                )}
              />
            </section>
          </div>

          <div className="mvp-chart-grid">
            <section className="mvp-chart-card">
              <div className="mvp-chart-head"><h3><MvpSymbol>payments</MvpSymbol>{t("legacy.recentPayments")}</h3></div>
              <MvpRows
                rows={recent}
                empty={t("legacy.noData")}
                render={(row) => (
                  <React.Fragment>
                    <div><strong>#{row.order_number || row.id}</strong><span>{row.cashier_name || "—"} · {row.payment_method || "—"} · {legacyDateTime(row.paid_at, lang)}</span></div>
                    <b>{money(row.amount)}</b>
                  </React.Fragment>
                )}
              />
            </section>
            <section className="mvp-chart-card">
              <div className="mvp-chart-head"><h3><MvpSymbol>receipt_long</MvpSymbol>{t("legacy.expenses")}</h3></div>
              <MvpRows
                rows={expenses}
                empty={t("legacy.noExpenses")}
                render={(row) => (
                  <React.Fragment>
                    <div><strong>{row.category || t("legacy.expenses")}</strong><span>{row.comment || "—"} · {row.cashier_name || "—"} · {legacyDateTime(row.created_at, lang)}</span></div>
                    <b className="amber">{money(row.amount)}</b>
                  </React.Fragment>
                )}
              />
            </section>
          </div>
        </div>
      ) : null}
    </div>
  );
}
