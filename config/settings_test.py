"""Deterministic settings used only by the local-edition test suite."""

import os

os.environ.setdefault("DEBUG", "True")
os.environ.setdefault("SECRET_KEY", "pytest-secret-key")
os.environ.setdefault(
    "LICENSE_FERNET_KEY",
    "6XzGcRmA0kcl-pX8R8wQbHCJqB7pDhVcMpC_Z8ZcKp4=",
)

from .settings import *  # noqa: E402,F401,F403
