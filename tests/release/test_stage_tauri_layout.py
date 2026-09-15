"""Bridge release layout: the folder the 1.0.x updater installs."""
import json

import pytest

from tools import stage_tauri_layout as stl


@pytest.fixture
def inputs(tmp_path):
    shell = tmp_path / 'build' / 'AlphaPOS.exe'
    shell.parent.mkdir()
    shell.write_bytes(b'MZ-shell')
    backend = tmp_path / 'dist' / 'AlphaPOSBackend'
    (backend / '_internal' / 'pgsql' / 'bin').mkdir(parents=True)
    (backend / 'AlphaPOSBackend.exe').write_bytes(b'MZ-backend')
    (backend / '_internal' / 'pgsql' / 'bin' / 'pg_ctl.exe').write_bytes(b'MZ-pg')
    guard = tmp_path / 'build' / 'alphapos-update-guard.exe'
    guard.write_bytes(b'MZ-guard')
    return {'shell': shell, 'backend': backend, 'guard': guard, 'out': tmp_path / 'dist' / 'tauri-layout'}


def test_layout_matches_the_installed_tauri_structure(inputs):
    manifest = stl.stage(version='1.1.0', **inputs)

    assert manifest['version'] == '1.1.0'
    assert sorted(manifest['files']) == [
        'AlphaPOS.exe',
        'backend/AlphaPOSBackend.exe',
        'backend/_internal/pgsql/bin/pg_ctl.exe',
        'bin/alphapos-update-guard.exe',
        'version.txt',
    ]
    out = inputs['out']
    assert (out / 'version.txt').read_text(encoding='utf-8') == '1.1.0\n'
    # The manifest sits beside the layout so tufup never archives it.
    written = json.loads((out.parent / 'tauri-layout-manifest.json').read_text(encoding='utf-8'))
    assert written == manifest
    assert not (out / 'tauri-layout-manifest.json').exists()


def test_manifest_hashes_detect_content_changes(inputs):
    first = stl.stage(version='1.1.0', **inputs)
    inputs['guard'].write_bytes(b'MZ-guard-changed')
    second = stl.stage(version='1.1.0', force=True, **inputs)
    changed = {k for k in first['files'] if first['files'][k] != second['files'][k]}
    assert changed == {'bin/alphapos-update-guard.exe'}


def test_refuses_to_overwrite_without_force(inputs):
    stl.stage(version='1.1.0', **inputs)
    with pytest.raises(SystemExit, match='--force'):
        stl.stage(version='1.1.0', **inputs)


@pytest.mark.parametrize('missing', ['shell', 'guard'])
def test_missing_inputs_are_rejected(inputs, missing):
    inputs[missing].unlink()
    with pytest.raises(SystemExit, match='not found'):
        stl.stage(version='1.1.0', **inputs)


def test_backend_without_exe_is_rejected(inputs):
    (inputs['backend'] / 'AlphaPOSBackend.exe').unlink()
    with pytest.raises(SystemExit, match='AlphaPOSBackend.exe'):
        stl.stage(version='1.1.0', **inputs)
