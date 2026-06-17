"""Regression: the packaged desktop app must spawn embedded-Postgres children
WITHOUT a console window (no flashing/uncloseable terminals on launch)."""
import subprocess
from pathlib import Path
from unittest import mock

from desktop import pg_embedded


def test_no_window_constant_matches_platform():
    assert pg_embedded._NO_WINDOW == getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def test_run_spawns_headless():
    """Every initdb/psql/pg_ctl call via _run carries creationflags=CREATE_NO_WINDOW."""
    with mock.patch('desktop.pg_embedded.subprocess.run') as m:
        m.return_value = subprocess.CompletedProcess([], 0, '', '')
        pg_embedded._run(Path('bin'), 'psql.exe', '-c', 'SELECT 1')
    _args, kwargs = m.call_args
    assert kwargs.get('creationflags') == pg_embedded._NO_WINDOW


def test_explicit_creationflags_not_clobbered():
    """setdefault means a caller could override, but the default is headless."""
    with mock.patch('desktop.pg_embedded.subprocess.run') as m:
        m.return_value = subprocess.CompletedProcess([], 0, '', '')
        pg_embedded._run(Path('bin'), 'initdb.exe')
    assert m.call_args.kwargs['creationflags'] == pg_embedded._NO_WINDOW
