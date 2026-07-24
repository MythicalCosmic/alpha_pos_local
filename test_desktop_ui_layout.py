"""Regression contracts for the native desktop panel's supported window."""
from pathlib import Path


ROOT = Path(__file__).resolve().parent


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
