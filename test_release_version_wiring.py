"""Regression checks for the desktop release's single version source."""
import re
from pathlib import Path

from desktop.version import __version__


ROOT = Path(__file__).resolve().parent


def test_desktop_version_is_inno_compatible():
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__)


def test_build_passes_version_to_inno_and_collects_its_output():
    script = (ROOT / "build_installer.ps1").read_text(encoding="utf-8")
    assert "from desktop.version import __version__" in script
    assert '"/DAppVersion=$version"' in script
    assert '"installer\\Output\\AlphaPOS-$version-Setup.exe"' in script
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
