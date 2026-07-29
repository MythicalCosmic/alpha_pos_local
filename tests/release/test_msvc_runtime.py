from __future__ import annotations

import hashlib
import struct
from pathlib import Path

import pytest

from tools import msvc_runtime


ROOT = Path(__file__).resolve().parents[2]


def _write_pe(
    path: Path,
    *,
    machine: int = 0x8664,
    optional_magic: int = 0x20B,
) -> str:
    payload = bytearray(256)
    payload[:2] = b"MZ"
    struct.pack_into("<I", payload, 0x3C, 0x80)
    payload[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<H", payload, 0x84, machine)
    struct.pack_into("<H", payload, 0x94, 0xF0)
    struct.pack_into("<H", payload, 0x98, optional_magic)
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def test_validates_exact_pe32_plus_amd64_runtime(tmp_path):
    runtime = tmp_path / msvc_runtime.DLL_NAME
    digest = _write_pe(runtime)

    assert (
        msvc_runtime.validate_msvc_runtime(
            runtime,
            expected_sha256=digest,
        )
        == runtime
    )


@pytest.mark.parametrize(
    ("machine", "optional_magic"),
    [
        (0x014C, 0x20B),
        (0x8664, 0x10B),
    ],
)
def test_rejects_wrong_runtime_architecture(
    tmp_path,
    machine,
    optional_magic,
):
    runtime = tmp_path / msvc_runtime.DLL_NAME
    digest = _write_pe(
        runtime,
        machine=machine,
        optional_magic=optional_magic,
    )

    with pytest.raises(msvc_runtime.MsvcRuntimeError, match=r"not PE32\+ AMD64"):
        msvc_runtime.validate_msvc_runtime(
            runtime,
            expected_sha256=digest,
        )


def test_rejects_unapproved_runtime_hash_with_actionable_error(tmp_path):
    runtime = tmp_path / msvc_runtime.DLL_NAME
    _write_pe(runtime)

    with pytest.raises(msvc_runtime.MsvcRuntimeError) as exc_info:
        msvc_runtime.validate_msvc_runtime(runtime)

    message = str(exc_info.value)
    assert msvc_runtime.EXPECTED_SHA256 in message
    assert msvc_runtime.ENV_NAME in message
    assert "Wine built-in" in message


def test_rejects_wrong_runtime_filename(tmp_path):
    runtime = tmp_path / "renamed.dll"
    digest = _write_pe(runtime)

    with pytest.raises(msvc_runtime.MsvcRuntimeError, match="must end with"):
        msvc_runtime.validate_msvc_runtime(
            runtime,
            expected_sha256=digest,
        )


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"not-a-pe",
        b"MZ" + (b"\0" * 62),
    ],
)
def test_rejects_invalid_or_truncated_pe(tmp_path, payload):
    runtime = tmp_path / msvc_runtime.DLL_NAME
    runtime.write_bytes(payload)

    with pytest.raises(msvc_runtime.MsvcRuntimeError, match="PE"):
        msvc_runtime.validate_msvc_runtime(
            runtime,
            expected_sha256=hashlib.sha256(payload).hexdigest(),
        )


def test_explicit_runtime_wins_over_system32(monkeypatch, tmp_path):
    explicit = tmp_path / "explicit" / msvc_runtime.DLL_NAME
    system_root = tmp_path / "windows"
    seen = []

    def fake_validate(path):
        resolved = Path(path)
        seen.append(resolved)
        return resolved

    monkeypatch.setattr(msvc_runtime, "validate_msvc_runtime", fake_validate)
    result = msvc_runtime.resolve_msvc_runtime(
        environ={
            msvc_runtime.ENV_NAME: str(explicit),
            "SystemRoot": str(system_root),
        }
    )

    assert result == explicit
    assert seen == [explicit]


def test_native_system32_is_the_only_implicit_candidate(monkeypatch, tmp_path):
    system_root = tmp_path / "windows"
    expected = system_root / "System32" / msvc_runtime.DLL_NAME

    monkeypatch.setattr(
        msvc_runtime,
        "validate_msvc_runtime",
        lambda path: Path(path),
    )

    assert (
        msvc_runtime.resolve_msvc_runtime(
            environ={"SystemRoot": str(system_root)},
            platform="win32",
        )
        == expected
    )


def test_blank_explicit_runtime_does_not_fall_back(monkeypatch, tmp_path):
    monkeypatch.setattr(
        msvc_runtime,
        "validate_msvc_runtime",
        lambda path: pytest.fail(f"unexpected validation of {path}"),
    )

    with pytest.raises(msvc_runtime.MsvcRuntimeError, match="set but blank"):
        msvc_runtime.resolve_msvc_runtime(
            environ={
                msvc_runtime.ENV_NAME: " ",
                "SystemRoot": str(tmp_path / "windows"),
            },
            platform="win32",
        )


def test_non_windows_build_does_not_use_system32_fallback(tmp_path):
    with pytest.raises(msvc_runtime.MsvcRuntimeError, match="only allowed"):
        msvc_runtime.resolve_msvc_runtime(
            environ={"SystemRoot": str(tmp_path / "windows")},
            platform="linux",
        )


def test_missing_runtime_source_fails_closed():
    with pytest.raises(msvc_runtime.MsvcRuntimeError) as exc_info:
        msvc_runtime.resolve_msvc_runtime(environ={}, platform="win32")

    message = str(exc_info.value)
    assert msvc_runtime.ENV_NAME in message
    assert "SystemRoot" in message


def test_both_specs_explicitly_bundle_the_verified_runtime():
    expected_hash = msvc_runtime.EXPECTED_SHA256
    helper = (ROOT / "tools" / "msvc_runtime.py").read_text(encoding="utf-8")
    assert expected_hash in helper

    for filename in ("AlphaPOS.spec", "AlphaPOS-onefile.spec"):
        spec = (ROOT / filename).read_text(encoding="utf-8")
        assert "_msvc_runtime = resolve_msvc_runtime()" in spec
        assert "release_binaries = [(str(_msvc_runtime), '.')]" in spec
        assert "binaries=release_binaries" in spec


def test_installer_preflights_and_pins_the_runtime_for_both_builds():
    script = (ROOT / "build_installer.ps1").read_text(encoding="utf-8")

    assert "from tools.msvc_runtime import resolve_msvc_runtime" in script
    assert "from tools.msvc_runtime import validate_msvc_runtime" in script
    assert "$env:ALPHA_POS_MSVC_RUNTIME" in script
    assert script.index("resolve_msvc_runtime") < script.index("& $pyinstaller")
    assert script.index("validate_msvc_runtime") > script.index(
        "'AlphaPOS.spec'"
    )
