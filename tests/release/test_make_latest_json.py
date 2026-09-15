"""Tauri updater manifest (latest.json) generation."""
import json
from datetime import datetime, timezone

import pytest

from tools import make_latest_json as mlj

BASE = 'https://control.78.111.91.113.nip.io/updates/installers/'


def test_manifest_matches_the_tauri_updater_format():
    manifest = mlj.build_manifest(
        version='1.1.1',
        signature='c2lnbmF0dXJl\n',
        base_url=BASE,
        notes='Faster startup',
        pub_date=datetime(2026, 9, 16, 3, 30, 12, 999, tzinfo=timezone.utc),
    )
    assert manifest == {
        'version': '1.1.1',
        'notes': 'Faster startup',
        'pub_date': '2026-09-16T03:30:12Z',
        'platforms': {
            'windows-x86_64': {
                'signature': 'c2lnbmF0dXJl',
                'url': BASE + 'AlphaPOS_1.1.1_x64-setup.exe',
            },
        },
    }


@pytest.mark.parametrize('kwargs, message', [
    ({'version': '1.1'}, 'x.y.z'),
    ({'signature': '  '}, 'signature is empty'),
    ({'base_url': 'http://insecure.example/'}, 'https'),
])
def test_invalid_inputs_are_rejected(kwargs, message):
    params = {'version': '1.1.1', 'signature': 'sig', 'base_url': BASE, **kwargs}
    with pytest.raises(SystemExit, match=message):
        mlj.build_manifest(**params)


def test_base_url_without_trailing_slash(tmp_path):
    manifest = mlj.build_manifest(version='1.1.1', signature='sig', base_url=BASE.rstrip('/'))
    assert manifest['platforms']['windows-x86_64']['url'] == BASE + 'AlphaPOS_1.1.1_x64-setup.exe'


def test_cli_reads_the_installer_signature(tmp_path):
    installer = tmp_path / 'Alpha POS_1.1.1_x64-setup.exe'
    installer.write_bytes(b'MZ')
    (tmp_path / 'Alpha POS_1.1.1_x64-setup.exe.sig').write_text('real-signature\n', encoding='utf-8')
    out = tmp_path / 'out' / 'latest.json'

    assert mlj.main(['--installer', str(installer), '--base-url', BASE, '--version', '1.1.1', '--out', str(out)]) == 0
    written = json.loads(out.read_text(encoding='utf-8'))
    assert written['platforms']['windows-x86_64']['signature'] == 'real-signature'


def test_cli_refuses_a_mismatched_installer_version(tmp_path):
    installer = tmp_path / 'Alpha POS_1.1.0_x64-setup.exe'
    installer.write_bytes(b'MZ')
    (tmp_path / 'Alpha POS_1.1.0_x64-setup.exe.sig').write_text('sig', encoding='utf-8')
    with pytest.raises(SystemExit, match='does not carry version 1.1.1'):
        mlj.main(['--installer', str(installer), '--base-url', BASE, '--version', '1.1.1', '--out', str(tmp_path / 'l.json')])
