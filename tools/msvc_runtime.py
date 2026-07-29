"""Resolve the exact Microsoft C++ runtime required by Windows releases."""

from __future__ import annotations

import hashlib
import os
import struct
import sys
from collections.abc import Mapping
from pathlib import Path


ENV_NAME = "ALPHA_POS_MSVC_RUNTIME"
DLL_NAME = "MSVCP140.dll"
EXPECTED_SHA256 = (
    "7c26614e1d733892c2deac7e245ce115504b1d80592dd0a01b08e3e5a55f89ca"
)
_PE_SIGNATURE = b"PE\0\0"
_PE32_PLUS_MAGIC = 0x20B
_AMD64_MACHINE = 0x8664


class MsvcRuntimeError(RuntimeError):
    """Raised when a release-safe MSVCP140.dll cannot be resolved."""


def _actionable(message: str) -> MsvcRuntimeError:
    return MsvcRuntimeError(
        f"{message} Set {ENV_NAME} to the exact verified x64 {DLL_NAME} "
        f"(SHA-256 {EXPECTED_SHA256}); never use a Wine built-in DLL."
    )


def _validate_pe32_plus_amd64(path: Path) -> None:
    try:
        with path.open("rb") as stream:
            dos_header = stream.read(64)
            if len(dos_header) != 64 or dos_header[:2] != b"MZ":
                raise _actionable(f"{path} is not a PE file.")

            pe_offset = struct.unpack_from("<I", dos_header, 0x3C)[0]
            stream.seek(pe_offset)
            pe_header = stream.read(26)
    except OSError as exc:
        raise _actionable(f"Could not read {path}: {exc}.") from exc

    if len(pe_header) != 26 or pe_header[:4] != _PE_SIGNATURE:
        raise _actionable(f"{path} has an invalid PE header.")

    machine = struct.unpack_from("<H", pe_header, 4)[0]
    optional_magic = struct.unpack_from("<H", pe_header, 24)[0]
    if machine != _AMD64_MACHINE or optional_magic != _PE32_PLUS_MAGIC:
        raise _actionable(
            f"{path} is not PE32+ AMD64 "
            f"(machine=0x{machine:04x}, optional_magic=0x{optional_magic:03x})."
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise _actionable(f"Could not hash {path}: {exc}.") from exc
    return digest.hexdigest()


def validate_msvc_runtime(
    path: str | os.PathLike[str],
    *,
    expected_sha256: str = EXPECTED_SHA256,
) -> Path:
    """Return an absolute path after identity and architecture verification."""

    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        raise _actionable(f"{candidate} is not an absolute path.")

    try:
        candidate = candidate.resolve(strict=True)
    except OSError as exc:
        raise _actionable(f"Required runtime {candidate} is unavailable: {exc}.") from exc

    if not candidate.is_file():
        raise _actionable(f"Required runtime {candidate} is not a regular file.")
    if candidate.name.casefold() != DLL_NAME.casefold():
        raise _actionable(
            f"Runtime path must end with {DLL_NAME}, got {candidate.name!r}."
        )

    _validate_pe32_plus_amd64(candidate)
    actual_sha256 = _sha256(candidate)
    if actual_sha256 != expected_sha256:
        raise _actionable(
            f"{candidate} has SHA-256 {actual_sha256}, expected {expected_sha256}."
        )
    return candidate


def resolve_msvc_runtime(
    *,
    environ: Mapping[str, str] | None = None,
    system_root: str | os.PathLike[str] | None = None,
    platform: str | None = None,
) -> Path:
    """Resolve an explicit runtime or the native Windows System32 candidate."""

    env = os.environ if environ is None else environ
    if ENV_NAME in env:
        explicit = (env.get(ENV_NAME) or "").strip()
        if not explicit:
            raise _actionable(f"{ENV_NAME} is set but blank.")
        return validate_msvc_runtime(explicit)

    current_platform = sys.platform if platform is None else platform
    if current_platform != "win32":
        raise _actionable(
            f"{ENV_NAME} is unset and System32 fallback is only allowed on "
            "native Windows builds."
        )

    root = system_root or env.get("SystemRoot") or env.get("WINDIR")
    if not root:
        raise _actionable(
            f"{ENV_NAME} is unset and neither SystemRoot nor WINDIR is available."
        )
    return validate_msvc_runtime(Path(root) / "System32" / DLL_NAME)
