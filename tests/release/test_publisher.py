"""Signed-release publisher tests."""

from __future__ import annotations

from types import SimpleNamespace

import tufup.repo

from tools import release


class _FakeRepository:
    def __init__(self, advertised_targets: dict[str, object]):
        self.roles = SimpleNamespace(
            targets=SimpleNamespace(
                signed=SimpleNamespace(targets=advertised_targets),
            )
        )
        self.calls: list[tuple[str, object]] = []

    def add_bundle(self, **kwargs):
        self.calls.append(("add_bundle", kwargs))

    def publish_changes(self, **kwargs):
        self.calls.append(("publish_changes", kwargs))


def _configure_paths(monkeypatch, tmp_path, version: str):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    keys = tmp_path / "keys"
    keys.mkdir()
    repo_dir = tmp_path / "repo"
    (repo_dir / "targets").mkdir(parents=True)

    monkeypatch.setattr(release, "KEYS_DIR", keys)
    monkeypatch.setattr(release, "REPO_DIR", repo_dir)
    monkeypatch.setattr(release, "__version__", version)
    return bundle, repo_dir


def test_publish_rejects_advertised_version_before_touching_archive(
    monkeypatch, tmp_path, capsys
):
    version = "9.9.9"
    bundle, repo_dir = _configure_paths(monkeypatch, tmp_path, version)
    target_name = f"{release.APP_NAME}-{version}.tar.gz"
    archive = repo_dir / "targets" / target_name
    archive.write_bytes(b"signed archive bytes")
    repository = _FakeRepository({target_name: object()})
    monkeypatch.setattr(
        tufup.repo.Repository,
        "from_config",
        classmethod(lambda cls: repository),
    )

    assert release.publish(bundle) == 1

    assert archive.read_bytes() == b"signed archive bytes"
    assert repository.calls == []
    output = capsys.readouterr().out
    assert "already advertised" in output
    assert "Bump desktop/version.py" in output


def test_publish_replaces_orphan_archive_then_publishes(monkeypatch, tmp_path):
    version = "9.9.9"
    bundle, repo_dir = _configure_paths(monkeypatch, tmp_path, version)
    target_name = f"{release.APP_NAME}-{version}.tar.gz"
    archive = repo_dir / "targets" / target_name
    archive.write_bytes(b"orphan from interrupted publish")
    repository = _FakeRepository({})
    monkeypatch.setattr(
        tufup.repo.Repository,
        "from_config",
        classmethod(lambda cls: repository),
    )

    assert release.publish(bundle) == 0

    assert not archive.exists()
    assert [name for name, _ in repository.calls] == [
        "add_bundle",
        "publish_changes",
    ]
    add_bundle_kwargs = repository.calls[0][1]
    assert add_bundle_kwargs == {
        "new_bundle_dir": str(bundle),
        "new_version": version,
        "skip_patch": True,
    }
    assert repository.calls[1][1] == {"private_key_dirs": [str(release.KEYS_DIR)]}
