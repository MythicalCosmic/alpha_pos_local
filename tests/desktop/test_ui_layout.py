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
    assert 'legacy.notPhysicalCash' in source
    assert 'quality.tender_attribution_complete !== true' in source
    assert 'quality.unknown_sale_amount' in source
    assert 'quality.unknown_refund_amount' in source
    assert 'https://' not in source


def test_trusted_sales_layout_remains_safe_at_narrow_widths():
    css = (ROOT / 'desktop' / 'ui' / 'themes.css').read_text(encoding='utf-8')

    assert '.legacy-table-wrap { max-width: 100%; overflow: auto;' in css
    assert '.legacy-kpi-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }' in css
    assert '.legacy-tender-grid, .legacy-kpi-grid { grid-template-columns: minmax(0, 1fr); }' in css
