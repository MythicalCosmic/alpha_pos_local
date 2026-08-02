"""Build a signed update bundle and publish it to the local tufup repo.

Pairs with desktop/updater.py. End-to-end flow is documented in
desktop/UPDATES.md; this script is the "publish a new version" half.

Usage:
    # ONE TIME — create signing keys + initial metadata (keep keys offline!):
    python tools/release.py --init

    # EACH RELEASE — after bumping desktop/version.py and building the onedir
    # PyInstaller bundle into dist/AlphaPOS/ :
    python tools/release.py --publish --bundle dist/AlphaPOS

Then stage and hash-check the target on the server behind
ALPHA_POS_UPDATE_URL, promoting the target first and timestamp metadata last
(see desktop/UPDATES.md), and ship
update_repo/metadata/root.json inside the next installer as tuf_root/root.json
so clients can bootstrap trust.

NOTE: tufup's API differs slightly across versions. This targets tufup 0.10.
If you bump tufup, re-check Repository.add_bundle / publish_changes signatures.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make `desktop` importable when run from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from desktop.version import APP_NAME, __version__  # noqa: E402

REPO_DIR = Path("update_repo")          # generated metadata + targets (publish this)
KEYS_DIR = Path("update_keys")          # PRIVATE signing keys — NEVER commit/upload
KEY_NAMES = ("root", "targets", "snapshot", "timestamp")
EXPIRATION_DAYS = {
    "root": 365,
    "targets": 30,
    "snapshot": 30,
    "timestamp": 30,
}


def _repo():
    from tufup.repo import Repository

    return Repository(
        app_name=APP_NAME,
        repo_dir=REPO_DIR,
        keys_dir=KEYS_DIR,
        # Single key per role is fine for a one-operator vendor; raise the
        # thresholds + add offline root keys if you later want stronger custody.
        key_map={role: [role] for role in KEY_NAMES},
        encrypted_keys=[],  # set roles here to passphrase-encrypt their keys
        expiration_days=EXPIRATION_DAYS,
        thresholds={role: 1 for role in KEY_NAMES},
    )


def init():
    if KEYS_DIR.exists() and any(KEYS_DIR.iterdir()):
        print(f"refusing to overwrite existing keys in {KEYS_DIR}/")
        return 1
    repo = _repo()
    repo.initialize()
    print(
        f"Initialized tufup repo in {REPO_DIR}/ and keys in {KEYS_DIR}/.\n"
        f"- BACK UP {KEYS_DIR}/ offline; losing the root key means clients can\n"
        f"  never trust a new key set without a reinstall.\n"
        f"- Ship {REPO_DIR}/metadata/root.json inside the installer as\n"
        f"  tuf_root/root.json (see AlphaPOS.spec datas)."
    )
    return 0


def publish(bundle: Path):
    if not bundle.is_dir():
        print(f"bundle dir not found: {bundle} (build the PyInstaller onedir first)")
        return 1
    if not KEYS_DIR.exists():
        print(f"no keys in {KEYS_DIR}/ — run `--init` once first")
        return 1
    from tufup.repo import Repository
    # Load the existing repo (keys + roles) from .tufup-repo-config written by
    # --init. Constructing a bare Repository leaves self.roles=None, so
    # add_bundle's get_latest_archive() blows up — from_config() loads them.
    repo = Repository.from_config()

    target_name = f'{APP_NAME}-{__version__}.tar.gz'
    advertised_targets = repo.roles.targets.signed.targets
    if target_name in advertised_targets:
        print(
            f"refusing to republish {APP_NAME} {__version__}: {target_name} is "
            "already advertised by targets metadata. Bump desktop/version.py "
            "before publishing another build."
        )
        return 1

    # tufup's make_gztar_archive prompts interactively before overwriting an
    # existing same-version archive, and that input() EOFs in a non-interactive
    # publish (CI / background). An archive that is not advertised by targets
    # metadata is an orphan left by an interrupted pre-metadata publish, so it
    # is safe to replace. The duplicate guard above deliberately runs first:
    # recreating an already-advertised archive could make its bytes disagree
    # with the signed length/hash while tufup refuses the same version.
    stale = REPO_DIR / 'targets' / target_name
    if stale.exists():
        print(f"removing leftover archive: {stale}")
        stale.unlink()
    # Register the new bundle for the current version and re-sign the metadata.
    # skip_patch=True: tufup's default delta-patch step runs bsdiff, which builds a
    # suffix array over the PREVIOUS archive in RAM (~17x its size). For a 100MB+
    # app that's ~8GB and effectively never finishes, so we ship FULL bundles —
    # each till downloads the whole (~110MB) once per update. Fine over a normal
    # link, and it keeps publishing fast + low-memory.
    repo.add_bundle(new_bundle_dir=str(bundle), new_version=__version__, skip_patch=True)
    repo.publish_changes(private_key_dirs=[str(KEYS_DIR)])
    print(
        f"Published {APP_NAME} {__version__}.\n"
        f"Now stage and hash-check the target on the control-center host, then promote\n"
        f"target -> targets.json -> snapshot.json -> timestamp.json (timestamp last).\n"
        f"See desktop/UPDATES.md; never publish metadata before its target archive."
    )
    return 0


def main():
    ap = argparse.ArgumentParser(description="Publish an Alpha POS desktop update.")
    ap.add_argument("--init", action="store_true", help="one-time key + metadata init")
    ap.add_argument("--publish", action="store_true", help="publish the current version")
    ap.add_argument("--bundle", type=Path, default=Path("dist") / APP_NAME,
                    help="PyInstaller onedir output to package (default: dist/AlphaPOS)")
    args = ap.parse_args()

    if args.init:
        return init()
    if args.publish:
        return publish(args.bundle)
    ap.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
