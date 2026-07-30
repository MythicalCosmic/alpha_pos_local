"""Regression contracts for the native desktop panel's supported window."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_dashboard_long_support_channels_use_a_contained_responsive_grid():
    source = (
        ROOT / 'desktop' / 'ui' / 'app' / 'screens-main.jsx'
    ).read_text(encoding='utf-8')
    css = (ROOT / 'desktop' / 'ui' / 'themes.css').read_text(encoding='utf-8')

    assert 'className="g12 dashboard-grid"' in source
    assert 'className="g2 obs-grid"' in source
    assert source.count('className="obs-panel"') == 2
    assert '.obs-grid { grid-template-columns: minmax(0, 1fr); }' in css
    assert '.obs-panel-head {' in css


def test_minimum_window_collapses_unsafe_grids_without_horizontal_escape():
    css = (ROOT / 'desktop' / 'ui' / 'themes.css').read_text(encoding='utf-8')

    assert '@media (max-width: 980px)' in css
    assert '.g12 > * { grid-column: 1 / -1 !important; }' in css
    assert '.g2 { grid-template-columns: minmax(0, 1fr); }' in css
    assert '.page { max-width: 1060px; min-width: 0;' in css
    assert '.kv-v { flex: 1 1 auto; min-width: 0;' in css


def test_raw_evidence_manage_action_opens_its_actual_configuration_page():
    source = (
        ROOT / 'desktop' / 'ui' / 'app' / 'screens-main.jsx'
    ).read_text(encoding='utf-8')

    assert (
        '<Btn size="sm" variant="ghost" '
        'onClick={() => app.nav("localAudit")}'
    ) in source


def test_sync_recovery_actions_wrap_in_the_supported_narrow_window():
    source = (
        ROOT / 'desktop' / 'ui' / 'app' / 'screens-ops.jsx'
    ).read_text(encoding='utf-8')

    assert 'gap: 12, flexWrap: "wrap"' in source


def test_sync_pill_surfaces_durable_full_replay_and_pull_errors():
    source = (
        ROOT / 'desktop' / 'ui' / 'app' / 'main.jsx'
    ).read_text(encoding='utf-8')

    assert source.count('replayPending:') == 3
    assert 'sync.full_pull_pending' in source
    assert 'sync.full_pull_state' in source
    assert 'sync.last_pull_error' in source


def test_force_pull_saved_replay_is_reported_as_queued_not_failed():
    source = (
        ROOT / 'desktop' / 'ui' / 'app' / 'screens-ops.jsx'
    ).read_text(encoding='utf-8')

    assert 'r && r.replay_requested && r.will_retry' in source
    queued = source.index('? t("tests.forcePullQueued")')
    raw_error = source.index(': (r && r.error) || t("tests.forcePullQueued")')
    assert queued < raw_error


def test_trusted_sales_screen_uses_shift_evidence_for_physical_cash():
    main = (
        ROOT / 'desktop' / 'ui' / 'app' / 'main.jsx'
    ).read_text(encoding='utf-8')
    source = (
        ROOT / 'desktop' / 'ui' / 'app' / 'screens-sales.jsx'
    ).read_text(encoding='utf-8')
    compiler = (
        ROOT / 'tools' / 'compile_desktop_ui.js'
    ).read_text(encoding='utf-8')

    assert 'id: "legacySales"' in main
    assert "'app/screens-sales.jsx'" in compiler
    assert 'shift.expected_cash == null' in source
    assert 'shift.cash_evidence_complete' in source
    assert 'drawers.expected_cash_total' in source
    assert 'payments.cash' in source
    assert 'legacy.netCashAllSources' in source
    assert 'legacy.tenderHint' in source
    assert 'quality.tender_attribution_complete !== true' in source
    assert 'quality.unknown_sale_amount' in source
    assert 'quality.unknown_refund_amount' in source
    assert 'payments.unknown' in source
    assert 'https://' not in source


def test_trusted_sales_labels_match_the_report_semantics():
    source = (
        ROOT / 'desktop' / 'ui' / 'app' / 'screens-sales.jsx'
    ).read_text(encoding='utf-8')
    i18n = (
        ROOT / 'desktop' / 'ui' / 'app' / 'i18n.js'
    ).read_text(encoding='utf-8')
    css = (ROOT / 'desktop' / 'ui' / 'themes.css').read_text(encoding='utf-8')

    assert 'const sequence = ++requestSequence.current;' in source
    assert 'setReport(null);' in source
    assert 'const bestCashier = cashierFilter ? null : (cashiers[0] || null);' in source
    assert 'if (tenderIncomplete || mvpNumber(unknownTenderValue) !== 0)' in source
    assert 'labels={tenderRows.map((row) => row.chartLabel)}' in source
    assert '{productTotal} {t("legacy.shownUnits")}' in source
    assert '<strong>{productTotal}</strong>' in source
    assert 'const positiveCategories = categories.filter' in source
    assert 'labels={positiveCategories.map((row) => row.name)}' in source
    assert 't("legacy.cashierHint")' in source
    assert 't("legacy.statusOpenFromPeriod")' in source
    assert i18n.count('"legacy.exactWindowHint"') == 3
    assert i18n.count('"legacy.statusOpenFromPeriod"') == 3
    assert i18n.count('"legacy.productTopTenHint"') == 3
    assert i18n.count('"legacy.categoryPositiveHint"') == 3
    assert '"legacy.week": "Last 7 operating days"' in i18n
    assert '"legacy.month": "Oxirgi 30 ish kuni"' in i18n
    assert '"legacy.year": "Последние 365 рабочих дней"' in i18n
    assert '"legacy.toTime": "Exact end time (exclusive)"' in i18n
    assert '[начало, окончание)' in i18n
    assert '.mvp-tender-card.unknown .mvp-tender-icon' in css


def test_trusted_sales_screen_keeps_the_smart_jowi_visual_contract():
    source = (
        ROOT / 'desktop' / 'ui' / 'app' / 'screens-sales.jsx'
    ).read_text(encoding='utf-8')
    css = (ROOT / 'desktop' / 'ui' / 'themes.css').read_text(encoding='utf-8')

    for marker in (
        'className="page mvp-dashboard"',
        'className="mvp-header"',
        'className="mvp-filter-bar"',
        'className="mvp-kpi-grid"',
        'className="mvp-status-row"',
        'className="mvp-chart-grid"',
        'className="mvp-tender-grid"',
        'className="mvp-three-grid"',
    ):
        assert marker in source
    assert source.count('kind="doughnut"') == 2
    assert 'kind="line"' in source
    assert source.count('kind="bar"') == 2
    assert 'mvpExactAt(fromDate, fromTime)' in source
    assert 'mvpExactAt(toDate, toTime)' in source
    assert 'const drawerComplete = drawers.complete === true;' in source
    assert 'drawerComplete ? money(drawers.expected_cash_total) : "—"' in source
    assert '--mvp-primary: #6366f1;' in css
    assert '--mvp-panel: rgba(30, 41, 64, .78);' in css


def test_trusted_sales_assets_are_offline_and_packaged():
    ui = ROOT / 'desktop' / 'ui'
    index = (ui / 'index.html').read_text(encoding='utf-8')
    css = (ui / 'themes.css').read_text(encoding='utf-8')
    vendor = ui / 'vendor' / 'smart-jowi'

    assert index.index('vendor/smart-jowi/chart.js') < index.index('app.bundle.js')
    assert 'PlusJakartaSans-Latin.woff2' in css
    assert 'Material-Symbols-Outlined.woff2' in css
    assert 'https://' not in index
    assert 'http://' not in index
    assert (vendor / 'chart.js').stat().st_size > 100_000
    assert '4.4.0' in (vendor / 'chart.js').read_text(encoding='utf-8')
    for filename in (
        'Material-Symbols-Outlined.woff2',
        'PlusJakartaSans-Latin.woff2',
        'PlusJakartaSans-LatinExt.woff2',
        'PlusJakartaSans-CyrillicExt.woff2',
    ):
        assert (vendor / filename).read_bytes().startswith(b'wOF2')
    assert 'SIL OPEN FONT LICENSE' in (
        vendor / 'PlusJakartaSans.OFL.txt'
    ).read_text(encoding='utf-8')
    for spec_name in ('AlphaPOS.spec', 'AlphaPOS-onefile.spec'):
        spec = (ROOT / spec_name).read_text(encoding='utf-8')
        assert "('desktop/ui', 'desktop/ui')" in spec


def test_trusted_sales_layout_remains_safe_at_narrow_widths():
    css = (ROOT / 'desktop' / 'ui' / 'themes.css').read_text(encoding='utf-8')

    assert '.mvp-kpi-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }' in css
    assert '.mvp-chart-grid { grid-template-columns: minmax(0, 1fr); }' in css
    assert '.mvp-kpi-grid, .mvp-tender-grid { grid-template-columns: minmax(0, 1fr); }' in css
    assert '.mvp-status-row { grid-template-columns: repeat(2, minmax(0, 1fr)); }' in css
