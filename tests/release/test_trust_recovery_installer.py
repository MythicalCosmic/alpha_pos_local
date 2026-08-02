from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_trust_recovery_installer_is_explicit_and_narrowly_scoped():
    installer = (ROOT / "installer" / "AlphaPOS.iss").read_text(encoding="utf-8")

    assert "#ifdef TrustRecovery" in installer
    assert "AlphaPOS-{#AppVersion}-Trust-Recovery-Setup" in installer
    assert "AppMutex=Global\\AlphaPOS_SingleInstance_v1" in installer
    assert "{localappdata}\\AlphaPOS\\update" in installer
    assert "update-pre-root-rotation-{#AppVersion}" in installer
    assert "update_pending.flag" in installer
    assert "RenameFile(UpdateDir, BackupDir)" in installer
    recovery = installer.split("#ifdef TrustRecovery", 2)[-1].split(
        "#endif", 1
    )[0]
    assert "pgdata" not in recovery
    assert ".env" not in recovery
    assert "DataDir" not in recovery


def test_build_requires_an_explicit_recovery_switch():
    build = (ROOT / "build_installer.ps1").read_text(encoding="utf-8")

    assert "[switch]$TrustRecovery" in build
    assert "'/DTrustRecovery=1'" in build
    assert "TrustRecovery and PrivateSupportConfig cannot be combined" in build
    assert '"AlphaPOS-$version-Trust-Recovery-Setup.exe"' in build
    assert '"$deliv\\AlphaPOS-Trust-Recovery-Setup.exe"' in build
