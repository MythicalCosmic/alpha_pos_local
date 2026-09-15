# PyInstaller spec for the windowless Alpha POS backend started by the Tauri shell.
#   .venv/Scripts/pyinstaller AlphaPOSBackend.spec
# Produces dist/AlphaPOSBackend/AlphaPOSBackend.exe (one-folder). It is a console
# build so a crash writes its traceback to stdout/stderr (captured by the shell)
# instead of a modal dialog; the shell spawns it with CREATE_NO_WINDOW.
# The shell owns the native window and updates, so no GUI or updater stack ships.
#
# Django + the apps are pure Python, but their templates/migrations/static and
# several runtime-imported modules must be collected explicitly.
import os
import sys
from PyInstaller.utils.hooks import collect_submodules, collect_data_files, collect_dynamic_libs


def collect_runtime_submodules(package):
    """Never ship test suites discovered by broad plugin collection."""
    return collect_submodules(
        package,
        filter=lambda name: all(
            part not in {'test', 'tests'}
            and not part.startswith('test_')
            and not part.endswith('_test')
            for part in name.split('.')
        ),
    )


def collect_runtime_data(package, **kwargs):
    return [
        row for row in collect_data_files(package, **kwargs)
        if all(
            part.lower() not in {'test', 'tests'}
            and not part.lower().startswith('test_')
            and not part.lower().endswith('_test.py')
            for part in os.path.normpath(row[0]).split(os.sep)
        )
    ]

# The spec dir (project root) must be importable so `import alpha_pos.settings`
# works at build time, regardless of the CWD pyinstaller is invoked from.
# SPECPATH is injected by PyInstaller when it execs this spec.
sys.path.insert(0, SPECPATH)

from tools.msvc_runtime import resolve_msvc_runtime

_msvc_runtime = resolve_msvc_runtime()
release_binaries = [(str(_msvc_runtime), '.')]
print(f'AlphaPOSBackend.spec: verified MSVC runtime: {_msvc_runtime}')

# Configure + load Django at BUILD time so collect_submodules can import each
# app package (their __init__ chains touch settings/models). Without this,
# PyInstaller silently skips most app submodules and the exe ModuleNotFounds at
# runtime. Dummy secrets — build-time only.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
os.environ.setdefault('SECRET_KEY', 'build-time-secret')
os.environ.setdefault('DEBUG', 'True')
os.environ.setdefault('LICENSE_FERNET_KEY', '')
import django  # noqa: E402
django.setup()

# Local-edition apps come from the LIVE INSTALLED_APPS (base/stock/hr/discounts/
# notifications/fiscalization/cashbox/licensing from core + customers/waiters +
# core.realtime) — so this tracks the edition split automatically (no admins, no
# old 'alpha_pos' project package).
from django.conf import settings as _dj
APPS = [a for a in _dj.INSTALLED_APPS
        if not a.startswith('django.') and a not in ('corsheaders', 'channels')]

hiddenimports = []
for app in APPS:
    hiddenimports += collect_runtime_submodules(app)
# The edition's config package (settings/urls/asgi/wsgi), the shared settings base,
# and the desktop launcher package (incl. the lazily-imported pg_embedded).
for pkg in ('config', 'alpha_pos_core', 'desktop'):
    hiddenimports += collect_runtime_submodules(pkg)
# Django + libs imported by string/lazily (middleware paths, etc.). These need
# their SUBMODULES collected, not just the top package, or import_string() fails
# at runtime (e.g. whitenoise.middleware, corsheaders.middleware).
hiddenimports += collect_runtime_submodules('django')
# ASGI stack: uvicorn + channels replace waitress (so the frozen app serves HTTP
# *and* websockets). Collect their submodules + the async/ws deps uvicorn lazily
# imports, or the exe ModuleNotFounds at serve time.
for lib in ('uvicorn', 'channels', 'asgiref', 'websockets', 'h11', 'httptools',
            'python_multipart', 'whitenoise', 'corsheaders', 'cryptography',
            'dateutil', 'requests', 'anthropic'):
    try:
        hiddenimports += collect_runtime_submodules(lib)
    except Exception:
        print(f'AlphaPOSBackend.spec: {lib} not collectable — skipped')
# Gemini SDK is lazy-imported in base/services/llm.py — collect it explicitly.
hiddenimports += collect_runtime_submodules('google.genai')
datas = [
    # Served for the browser fallback while WebView2 is being installed.
    ('desktop/ui', 'desktop/ui'),
    ('desktop/tos.txt', 'desktop'),
]
# Ship each app's migrations + templates + static.
for app in APPS:
    datas += collect_runtime_data(app, include_py_files=True)

# Collect the shared settings package and the non-app ``core`` services
# (shift orchestration and realtime). PyInstaller's module graph can miss
# editable packages, so include their Python sources explicitly.
for _pkg in ('core', 'alpha_pos_core'):
    datas += collect_runtime_data(_pkg, include_py_files=True)
    hiddenimports += collect_runtime_submodules(_pkg)

# Embedded Postgres: bundle the portable binaries so desktop/pg_embedded.py can run
# a private DB (install needs no separate Postgres). Looks for _pg/pgsql in the repo
# or the parent workspace. LARGE (~hundreds of MB); the build still succeeds without
# it (the app then expects an external/dev Postgres).
_pg_candidates = [os.environ.get('ALPHA_POS_PGSQL_DIR'),
                  os.path.join(SPECPATH, '_pg', 'pgsql'),
                  os.path.join(SPECPATH, '..', '_pg', 'pgsql'),
                  os.path.join(SPECPATH, '..', '..', '_pg', 'pgsql')]
_pg_candidates = [c for c in _pg_candidates if c]
_pgsql = next((c for c in _pg_candidates if os.path.isdir(c)), None)
# Skip subtrees the embedded server never runs. pgAdmin 4 alone is hundreds of MB
# of a web GUI we never launch, and its very deep template paths blow past Windows'
# 260-char MAX_PATH during Inno Setup compression -> "cannot find the path / Setup.exe
# MISSING". pg_embedded.py only calls bin/lib/share (initdb, pg_ctl, postgres, psql).
_PG_SKIP = {'pgAdmin 4', 'StackBuilder', 'doc', 'include', 'symbols'}
if _pgsql:
    _pgroot = os.path.dirname(os.path.abspath(_pgsql))
    _pg_count = 0
    for _root, _dirs, _files in os.walk(_pgsql):
        _dirs[:] = [d for d in _dirs if d not in _PG_SKIP]  # prune before descending
        _rel = os.path.relpath(_root, _pgroot)  # -> pgsql/bin, pgsql/lib, ...
        for _fn in _files:
            datas.append((os.path.join(_root, _fn), _rel))
            _pg_count += 1
    print(f'AlphaPOSBackend.spec: bundling embedded Postgres ({_pg_count} files, '
          f'pgAdmin/docs pruned).')
else:
    print('AlphaPOSBackend.spec: _pg/pgsql not found — embedded Postgres NOT bundled. '
          'Place a portable Postgres at _pg/pgsql/ to ship a self-contained DB.')

block_cipher = None

a = Analysis(
    [os.path.join(SPECPATH, 'desktop', 'backend_main.py')],
    pathex=[SPECPATH],
    binaries=release_binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[
        os.path.join(SPECPATH, 'desktop', 'private_release_bootstrap.py'),
    ],
    # tkinter: unused GUI toolkit. PIL/Pillow: only used at BUILD time to make
    # the icon (make_icon.py) — nothing in the app imports it at runtime (no
    # ImageField / qrcode), so it's dead weight (~11 MB) in the shipped bundle.
    excludes=['tkinter', 'PIL', 'PIL._imaging', 'PIL.Image', 'webview', 'clr', 'clr_loader', 'pythonnet', 'tufup', 'bsdiff4'],
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name='AlphaPOSBackend',
    console=True, icon='desktop/AlphaPOS.ico',
)
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, name='AlphaPOSBackend')
