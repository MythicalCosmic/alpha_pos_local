"""The panel's typed bridge map must match the Python Api and the e2e mocks."""
import re
from pathlib import Path

from desktop.bridge import Api


ROOT = Path(__file__).resolve().parents[2]
UI_SRC = ROOT / 'desktop' / 'ui-src'


def _object_keys(source, start_marker):
    start = source.index(start_marker)
    end = source.index('\n};', start)
    body = source[start:end]
    return re.findall(r'^  ([a-z_][a-z0-9_]*):', body, flags=re.MULTILINE)


def _ui_methods():
    source = (UI_SRC / 'src' / 'bridge' / 'methods.ts').read_text(encoding='utf-8')
    keys = _object_keys(source.replace('} as const;', '};'), 'export const METHODS = {')
    assert keys, 'no methods parsed from methods.ts'
    return keys


def test_every_ui_method_is_a_public_bridge_api_callable():
    missing = [
        name for name in _ui_methods()
        if name.startswith('_') or not callable(getattr(Api, name, None))
    ]
    assert missing == []


def test_every_ui_method_has_a_mock_fixture():
    fixtures_source = (
        UI_SRC / 'e2e' / 'fixtures' / 'bridge-fixtures.ts'
    ).read_text(encoding='utf-8')
    fixtures = set(_object_keys(
        fixtures_source, 'export const FIXTURES: Record<string, Fixture> = {',
    ))
    methods = _ui_methods()
    assert [name for name in methods if name not in fixtures] == []
    # Fixtures must not drift towards methods the panel no longer calls.
    assert sorted(fixtures - set(methods)) == []


def test_ui_methods_are_unique():
    methods = _ui_methods()
    assert len(methods) == len(set(methods))
