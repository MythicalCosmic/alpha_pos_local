"""Light source contracts for the desktop control panel (desktop/ui-src)."""
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / 'desktop' / 'ui-src' / 'src'


def _read(relative):
    return (SRC / relative).read_text(encoding='utf-8')


def test_sync_state_surfaces_durable_full_replay_and_pull_errors():
    source = _read('lib/sync.ts')

    assert 'full_pull_pending' in source
    assert 'full_pull_state' in source
    assert 'last_pull_error' in source
    assert "'sync.replayPending'" in source


def test_force_pull_saved_replay_is_reported_as_queued_not_failed():
    source = _read('pages/Tests.tsx')

    assert 'r && r.replay_requested && r.will_retry' in source
    queued = source.index("? t('tests.forcePullQueued')")
    raw_error = source.index(": (r && r.error) || t('tests.forcePullQueued')")
    assert queued < raw_error
    # Destructive replay is confirmed in-app, never with window.confirm.
    assert 'window.confirm' not in source
    assert '<ConfirmModal' in source


def test_raw_evidence_manage_action_opens_its_actual_configuration_page():
    source = _read('pages/dashboard/Observability.tsx')

    assert "navigate('local-audit')" in source


def test_minimum_window_collapses_to_icon_rail_without_horizontal_escape():
    base = _read('styles/base.css')
    components = _read('styles/components.css')

    assert '@media (max-width: 1099px)' in base
    assert '.main { grid-column: 2; overflow: auto;' in base
    assert '.page { max-width: 1120px;' in base
    assert 'repeat(auto-fit, minmax(280px, 1fr))' in components
    assert '.row { display: flex; align-items: center; gap: var(--s2); flex-wrap: wrap; }' in components
    assert '.kv-v { flex: 1 1 auto; min-width: 0;' in components


def test_styles_stay_light():
    css = ''.join(_read(f'styles/{name}') for name in ('tokens.css', 'base.css', 'components.css'))

    assert '@font-face' not in css
    assert 'backdrop-filter' not in css
    assert 'radial-gradient' not in css
    assert not re.search(r'filter:\s*blur', css)
    # The only infinite animation is the pending-request spinner.
    assert css.count('infinite') == 1
    assert 'prefers-reduced-motion' in css


def test_no_global_tick_or_remount_on_language_change():
    app = _read('app/App.tsx')
    audit = _read('pages/LocalAudit.tsx')

    assert 'setInterval' not in app
    assert 'key={route + ' not in app and 'key={page + lang}' not in app
    # ToggleRow is a module-level component, not redefined per render.
    assert audit.index('function ToggleRow(') < audit.index('export default function LocalAudit(')
