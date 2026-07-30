// Temporary familiar sales dashboard.  It is read-only and all figures come
// from desktop/local_sales_report.py over the current POS database.

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

function LegacyMetric({ tone, label, value, unit, detail }) {
  return (
    <div className={"legacy-kpi " + (tone || "")}>
      <div className="legacy-kpi-label">{label}</div>
      <div className="legacy-kpi-value">
        {value}<span>{unit || ""}</span>
      </div>
      <div className="legacy-kpi-detail">{detail || "\u00a0"}</div>
    </div>
  );
}

function LegacyTable({ columns, rows, empty }) {
  return (
    <div className="legacy-table-wrap">
      <table className="legacy-table">
        <thead>
          <tr>{columns.map((col) => <th key={col.key}>{col.label}</th>)}</tr>
        </thead>
        <tbody>
          {rows.length ? rows.map((row, index) => (
            <tr key={row.id != null ? row.id : index}>
              {columns.map((col) => (
                <td key={col.key} className={col.align === "right" ? "num" : ""}>
                  {col.render ? col.render(row) : (row[col.key] == null || row[col.key] === "" ? "—" : row[col.key])}
                </td>
              ))}
            </tr>
          )) : (
            <tr><td className="legacy-empty" colSpan={columns.length}>{empty}</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function LegacySalesScreen() {
  const app = useApp();
  const { t, lang } = app;
  const [fromDate, setFromDate] = React.useState(legacyBusinessDate());
  const [toDate, setToDate] = React.useState(legacyBusinessDate());
  const [report, setReport] = React.useState(null);
  const [enabled, setEnabled] = React.useState(true);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");

  const money = React.useCallback(
    (value) => legacyMoney(value, lang),
    [lang],
  );
  const load = React.useCallback((start, end) => {
    setLoading(true);
    setError("");
    return api.legacy_sales_report(start, end, null, null).then((result) => {
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
    });
  }, [t]);

  React.useEffect(() => { load(fromDate, toDate); }, []);

  const chooseRange = (days) => {
    const end = legacyBusinessDate();
    const start = legacyBusinessDate(-(days - 1));
    setFromDate(start);
    setToDate(end);
    load(start, end);
  };
  const applyRange = () => load(fromDate, toDate);

  if (!enabled) {
    return (
      <div className="page">
        <header className="page-head">
          <h1 className="page-h">{t("legacy.title")}</h1>
          <p className="page-sub">{t("legacy.disabled")}</p>
        </header>
      </div>
    );
  }

  const summary = (report && report.summary) || {};
  const payments = (report && report.payment_breakdown) || {};
  const drawers = (report && report.active_drawers) || {};
  const quality = (report && report.data_quality) || {};
  const range = (report && report.range) || {};
  const tenderIncomplete = quality.tender_attribution_complete !== true;
  const cashiers = (report && report.cashiers) || [];
  const products = (report && report.top_products) || [];
  const categories = (report && report.categories) || [];
  const expenses = (report && report.expenses) || [];
  const recent = (report && report.recent_paid_orders) || [];

  const cashierColumns = [
    { key: "cashier_name", label: t("legacy.cashier") },
    { key: "paid_orders", label: t("legacy.paid"), align: "right" },
    { key: "net_revenue", label: t("legacy.netSales"), align: "right", render: (row) => money(row.net_revenue) },
    { key: "cash", label: t("legacy.cash"), align: "right", render: (row) => money((row.payment_breakdown || {}).cash) },
    { key: "card", label: t("legacy.card"), align: "right", render: (row) => money((row.payment_breakdown || {}).card) },
    { key: "payme", label: t("legacy.payme"), align: "right", render: (row) => money((row.payment_breakdown || {}).payme) },
    { key: "refund_amount", label: t("legacy.refunds"), align: "right", render: (row) => money(row.refund_amount) },
  ];
  const productColumns = [
    { key: "name", label: t("legacy.product") },
    { key: "quantity", label: t("legacy.units"), align: "right" },
    { key: "revenue", label: t("legacy.netSales"), align: "right", render: (row) => money(row.revenue) },
    { key: "refund_amount", label: t("legacy.refunds"), align: "right", render: (row) => money(row.refund_amount) },
  ];
  const categoryColumns = [
    { key: "name", label: t("legacy.category") },
    { key: "quantity", label: t("legacy.units"), align: "right" },
    { key: "revenue", label: t("legacy.netSales"), align: "right", render: (row) => money(row.revenue) },
  ];
  const recentColumns = [
    { key: "order_number", label: t("legacy.order") },
    { key: "cashier_name", label: t("legacy.cashier") },
    { key: "payment_method", label: t("legacy.method") },
    { key: "amount", label: t("legacy.amount"), align: "right", render: (row) => money(row.amount) },
    { key: "paid_at", label: t("legacy.paidAt"), render: (row) => legacyDateTime(row.paid_at, lang) },
  ];
  const expenseColumns = [
    { key: "category", label: t("legacy.category") },
    { key: "cashier_name", label: t("legacy.cashier") },
    { key: "comment", label: t("legacy.comment") },
    { key: "amount", label: t("legacy.amount"), align: "right", render: (row) => money(row.amount) },
    { key: "created_at", label: t("legacy.time"), render: (row) => legacyDateTime(row.created_at, lang) },
  ];

  return (
    <div className="page legacy-page" data-screen-label="Trusted sales">
      <header className="legacy-hero">
        <div>
          <div className="legacy-eyebrow">{t("legacy.temporary")}</div>
          <h1>{t("legacy.title")}</h1>
          <p>{t("legacy.sub")}</p>
        </div>
        <Badge tone="ok">{t("legacy.readOnly")}</Badge>
      </header>

      <div className="legacy-filter">
        <div className="legacy-presets">
          <Btn variant="ghost" size="sm" onClick={() => chooseRange(1)}>{t("legacy.today")}</Btn>
          <Btn variant="ghost" size="sm" onClick={() => {
            const day = legacyBusinessDate(-1);
            setFromDate(day); setToDate(day); load(day, day);
          }}>{t("legacy.yesterday")}</Btn>
          <Btn variant="ghost" size="sm" onClick={() => chooseRange(7)}>{t("legacy.sevenDays")}</Btn>
        </div>
        <Field l={t("legacy.from")}>
          <input className="inp" type="date" value={fromDate} onChange={(event) => setFromDate(event.target.value)} />
        </Field>
        <Field l={t("legacy.to")}>
          <input className="inp" type="date" value={toDate} onChange={(event) => setToDate(event.target.value)} />
        </Field>
        <Btn variant="primary" icon="refresh" onClick={applyRange} disabled={loading}>
          {loading ? t("common.running") : t("legacy.apply")}
        </Btn>
      </div>

      {error ? <div className="legacy-alert danger"><Icon name="warn"></Icon><span>{error}</span></div> : null}
      {tenderIncomplete ? (
        <div className="legacy-alert danger">
          <Icon name="warn"></Icon>
          <span>
            {t("legacy.unknownTender")}: {t("legacy.unknownSales")} {money(quality.unknown_sale_amount)} UZS · {t("legacy.unknownRefunds")} {money(quality.unknown_refund_amount)} UZS
          </span>
        </div>
      ) : null}

      {loading && !report ? (
        <Card><div className="legacy-empty"><span className="spinner"></span> {t("common.running")}</div></Card>
      ) : report ? (
        <div className="stack">
          <div className="legacy-period">
            <Icon name="receipt" size={18}></Icon>
            <div>
              <strong>{range.from} → {range.to}</strong>
              <span>{legacyDateTime(range.start_at, lang)} — {legacyDateTime(range.end_at, lang)}</span>
            </div>
            <Badge tone="muted">{range.mode === "business" ? "07:00 → 03:00" : t("legacy.exact")}</Badge>
          </div>

          <section className={"legacy-drawer-proof " + (drawers.complete ? "complete" : "incomplete")}>
            <div className="legacy-proof-head">
              <div>
                <div className="legacy-eyebrow">{t("legacy.physicalProof")}</div>
                <h2>{t("legacy.drawerNow")}</h2>
                <p>{t("legacy.drawerHint")}</p>
              </div>
              <div className="legacy-proof-total">
                <span>{(drawers.shifts || []).length ? (drawers.complete ? t("legacy.expected") : t("legacy.incomplete")) : t("legacy.noActiveShifts")}</span>
                <strong>{drawers.complete ? money(drawers.expected_cash_total) : "—"}{drawers.complete ? <small> UZS</small> : null}</strong>
              </div>
            </div>
            <div className="legacy-drawer-grid">
              {(drawers.shifts || []).length ? drawers.shifts.map((shift) => (
                <div className="legacy-drawer-card" key={shift.shift_id}>
                  <div className="legacy-drawer-name">
                    <strong>{shift.cashier || "—"}</strong>
                    <Badge tone={shift.cash_evidence_complete ? "ok" : "danger"}>
                      {shift.cash_evidence_complete ? t("legacy.complete") : t("legacy.incomplete")}
                    </Badge>
                  </div>
                  <div className="legacy-drawer-money">
                    {shift.expected_cash == null ? "—" : money(shift.expected_cash)}
                    <span>UZS</span>
                  </div>
                  <div className="legacy-drawer-meta">{t("legacy.started")}: {legacyDateTime(shift.started_at, lang)}</div>
                  <div className="legacy-drawer-meta">{t("legacy.source")}: {shift.expected_cash_source || "—"}</div>
                </div>
              )) : <div className="legacy-empty">{drawers.available === false ? (drawers.error || t("legacy.drawerUnavailable")) : t("legacy.noActiveShifts")}</div>}
            </div>
          </section>

          <div className="legacy-kpi-grid">
            <LegacyMetric tone="emerald" label={t("legacy.netSales")} value={money(summary.net_revenue)} unit="UZS" detail={t("legacy.gross") + ": " + money(summary.gross_revenue) + " · " + t("legacy.refunds") + ": " + money(summary.refund_amount)} />
            <LegacyMetric tone="blue" label={t("legacy.ordersOpened")} value={summary.orders || 0} detail={t("legacy.paid") + ": " + (summary.paid_orders || 0) + " · " + t("legacy.cancelled") + ": " + (summary.cancelled_orders || 0)} />
            <LegacyMetric tone="violet" label={t("legacy.averagePaid")} value={money(summary.average_paid_order)} unit="UZS" detail={t("legacy.units") + ": " + (summary.units_sold || 0)} />
            <LegacyMetric tone="amber" label={t("legacy.drawerExpenses")} value={money(summary.cashbox_expenses)} unit="UZS" detail={t("legacy.selectedRange")} />
          </div>

          <Card
            title={t("legacy.tenders")}
            action={<Badge tone="warn">{t("legacy.notPhysicalCash")}</Badge>}
          >
            <p className="legacy-card-note">{t("legacy.tenderHint")}</p>
            <div className="legacy-tender-grid">
              <LegacyMetric tone="emerald" label={t("legacy.cashAllSources")} value={money(payments.cash)} unit="UZS" />
              <LegacyMetric tone="blue" label={t("legacy.card")} value={money(payments.card)} unit="UZS" detail={"UZCARD " + money((payments.card_detail || {}).UZCARD) + " · HUMO " + money((payments.card_detail || {}).HUMO) + " · CARD " + money((payments.card_detail || {}).CARD)} />
              <LegacyMetric tone="violet" label={t("legacy.payme")} value={money(payments.payme)} unit="UZS" />
            </div>
          </Card>

          <Card title={t("legacy.cashiers")}>
            <p className="legacy-card-note">{t("legacy.cashierHint")}</p>
            <LegacyTable columns={cashierColumns} rows={cashiers} empty={t("legacy.noData")} />
          </Card>

          <div className="g2 legacy-two">
            <Card title={t("legacy.topProducts")}>
              <LegacyTable columns={productColumns} rows={products} empty={t("legacy.noData")} />
            </Card>
            <Card title={t("legacy.categories")}>
              <LegacyTable columns={categoryColumns} rows={categories} empty={t("legacy.noData")} />
            </Card>
          </div>

          <Card title={t("legacy.recentPayments")}>
            <LegacyTable columns={recentColumns} rows={recent} empty={t("legacy.noData")} />
          </Card>

          <Card title={t("legacy.expenses")}>
            <LegacyTable columns={expenseColumns} rows={expenses} empty={t("legacy.noExpenses")} />
          </Card>
        </div>
      ) : null}
    </div>
  );
}
