"""Regression checks for the desktop release's single version source."""
import re
from pathlib import Path

from desktop.version import __version__


ROOT = Path(__file__).resolve().parents[2]


def test_desktop_version_is_inno_compatible():
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__)


def test_build_passes_version_to_inno_and_collects_its_output():
    script = (ROOT / "build_installer.ps1").read_text(encoding="utf-8")
    assert "from desktop.version import __version__" in script
    assert '"/DAppVersion=$version"' in script
    assert '"AlphaPOS-$version-Setup.exe"' in script
    assert '"AlphaPOS-$version-Private-Setup.exe"' in script
    assert '"installer\\Output\\$installerName"' in script
    assert "'..\\..\\.venv'" in script
    assert 'ALPHA_POS_PGSQL_DIR' in script
    assert 'ALPHA_POS_TUF_ROOT' in script


def test_both_specs_accept_resolved_release_inputs():
    for filename in ('AlphaPOS.spec', 'AlphaPOS-onefile.spec'):
        spec = (ROOT / filename).read_text(encoding='utf-8')
        assert "os.environ.get('ALPHA_POS_PGSQL_DIR')" in spec
        assert "os.environ.get('ALPHA_POS_TUF_ROOT')" in spec


def test_inno_script_accepts_build_override_with_safe_fallback():
    script = (ROOT / "installer" / "AlphaPOS.iss").read_text(encoding="utf-8")
    assert "#ifndef AppVersion" in script
    assert f'#define AppVersion "{__version__}"' in script
    assert "#endif" in script


def test_tauri_shell_versions_match_the_single_source():
    from tools import sync_version

    assert sync_version.main(['--check']) == 0


def test_sync_version_rewrites_drifted_shell_manifests(tmp_path):
    import json
    from tools import sync_version

    version_file = tmp_path / 'version.py'
    version_file.write_text('__version__ = "2.3.4"\n', encoding='utf-8')
    cargo = tmp_path / 'Cargo.toml'
    cargo.write_text(
        '[workspace]\nmembers = ["a"]\n\n[workspace.package]\nversion = "1.1.0"\nedition = "2021"\n\n'
        '[profile.release]\nopt-level = "s"\n',
        encoding='utf-8',
    )
    tauri = tmp_path / 'tauri.conf.json'
    tauri.write_text('{\n  "productName": "Alpha POS",\n  "version": "1.1.0",\n  "bundle": {"version": "keep"}\n}\n', encoding='utf-8')
    version_txt = tmp_path / 'version.txt'
    paths = {'version_file': version_file, 'cargo_toml': cargo, 'tauri_conf': tauri, 'version_txt': version_txt}

    assert sync_version.main(['--check'], **paths) == 1
    assert sync_version.main([], **paths) == 0
    assert sync_version.main(['--check'], **paths) == 0
    assert 'version = "2.3.4"' in cargo.read_text(encoding='utf-8')
    assert 'opt-level = "s"' in cargo.read_text(encoding='utf-8')
    config = json.loads(tauri.read_text(encoding='utf-8'))
    assert config['version'] == '2.3.4' and config['bundle']['version'] == 'keep'
    assert version_txt.read_text(encoding='utf-8') == '2.3.4\n'

