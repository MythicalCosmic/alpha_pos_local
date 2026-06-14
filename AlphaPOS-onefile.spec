# PyInstaller ONE-FILE spec for Alpha POS (the PORTABLE build).
#   <venv>/Scripts/pyinstaller AlphaPOS-onefile.spec
# Produces a SINGLE dist/AlphaPOS.exe with everything packed inside — copy it to
# any Windows 10/11 PC and double-click, no install. It self-extracts to a temp
# dir at launch and keeps real data under %LOCALAPPDATA%\AlphaPOS.
#
# NOTE: this mirrors AlphaPOS.spec (the onedir/Setup build) but emits one file.
# It bundles embedded Postgres too, so the portable is large (~hundreds of MB) and
# its FIRST launch is slow (it extracts everything to temp each run). The Setup
# installer (onedir) is the recommended deliverable; it also AUTO-UPDATES — the
# one-file portable does not.
import os
import sys
from PyInstaller.utils.hooks import collect_submodules, collect_data_files, collect_dynamic_libs

sys.path.insert(0, SPECPATH)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
os.environ.setdefault('SECRET_KEY', 'build-time-secret')
os.environ.setdefault('DEBUG', 'True')
os.environ.setdefault('LICENSE_FERNET_KEY', '')
import django  # noqa: E402
django.setup()

from django.conf import settings as _dj
APPS = [a for a in _dj.INSTALLED_APPS
        if not a.startswith('django.') and a not in ('corsheaders', 'channels')]

hiddenimports = []
for app in APPS:
    hiddenimports += collect_submodules(app)
for pkg in ('config', 'alpha_pos_core', 'desktop'):
    hiddenimports += collect_submodules(pkg)
hiddenimports += collect_submodules('django')
for lib in ('uvicorn', 'channels', 'asgiref', 'websockets', 'h11', 'httptools',
            'python_multipart', 'whitenoise', 'corsheaders', 'cryptography',
            'dateutil', 'requests', 'anthropic'):
    try:
        hiddenimports += collect_submodules(lib)
    except Exception:
        print(f'onefile: {lib} not collectable — skipped')
hiddenimports += collect_submodules('google.genai')
update_binaries = []
for _ulib in ('tufup', 'tuf', 'securesystemslib', 'bsdiff4', 'nacl'):
    try:
        hiddenimports += collect_submodules(_ulib)
    except Exception:
        print(f'onefile: {_ulib} not available — self-update omitted')
for _ulib in ('bsdiff4', 'nacl'):
    try:
        update_binaries += collect_dynamic_libs(_ulib)
    except Exception:
        pass
hiddenimports += collect_submodules('webview') + collect_submodules('clr_loader')
hiddenimports += ['clr', 'pythonnet']

datas = [
    ('desktop/ui', 'desktop/ui'),
    ('desktop/tos.txt', 'desktop'),
]
_tuf_root = os.path.join(SPECPATH, 'update_repo', 'metadata', 'root.json')
if os.path.exists(_tuf_root):
    datas += [(_tuf_root, 'tuf_root')]
datas += collect_data_files('webview')
for app in APPS:
    datas += collect_data_files(app, include_py_files=True)
for _pkg in ('core', 'alpha_pos_core'):
    datas += collect_data_files(_pkg, include_py_files=True)
# Embedded Postgres (repo or parent workspace).
_pg_candidates = [os.path.join(SPECPATH, '_pg', 'pgsql'),
                  os.path.join(SPECPATH, '..', '_pg', 'pgsql')]
_pgsql = next((c for c in _pg_candidates if os.path.isdir(c)), None)
# Skip subtrees the embedded server never runs (see AlphaPOS.spec): pgAdmin 4 is a
# huge web GUI we never launch, with paths deep enough to break Windows MAX_PATH.
_PG_SKIP = {'pgAdmin 4', 'StackBuilder', 'doc', 'include', 'symbols'}
if _pgsql:
    _pgroot = os.path.dirname(os.path.abspath(_pgsql))
    for _root, _dirs, _files in os.walk(_pgsql):
        _dirs[:] = [d for d in _dirs if d not in _PG_SKIP]  # prune before descending
        _rel = os.path.relpath(_root, _pgroot)
        for _fn in _files:
            datas.append((os.path.join(_root, _fn), _rel))
    print('onefile: bundling embedded Postgres (pgAdmin/docs pruned).')
else:
    print('onefile: _pg/pgsql not found — embedded Postgres NOT bundled.')

block_cipher = None

a = Analysis(
    [os.path.join(SPECPATH, 'desktop', 'app.py')],
    pathex=[SPECPATH],
    binaries=update_binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=['tkinter', 'PIL', 'PIL._imaging', 'PIL.Image'],
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ONE-FILE: pass binaries + datas straight into EXE (no COLLECT).
exe = EXE(
    pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
    name='AlphaPOS', debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, runtime_tmpdir=None,
    console=False, icon='desktop/AlphaPOS.ico',
)
