#!/usr/bin/env python3
"""Scan for credentials and licensed model content before it reaches git.

Usage:
    python tools/check_confidential.py [PATHS...] [--staged] [--tracked] [--history] [--deny FILE]

With no arguments it scans every tracked file inside a git repository, and the
current directory elsewhere. Exit status: 0 clean, 1 findings, 2 usage error.
``--help`` lists the options, ``--list-rules`` the rules. The git hook in
tools/hooks/pre-commit runs this script with ``--staged``.

The engine is oegem/leakcheck.py. It is loaded straight from the source tree,
so the check runs without installing the package and without its third-party
dependencies (the package ``__init__`` imports pandas and requests).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_engine():
    """Import oegem/leakcheck.py by file path, without running oegem/__init__.py."""
    name = "oegem_leakcheck"
    spec = importlib.util.spec_from_file_location(name, ROOT / "oegem" / "leakcheck.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses look the module up while building classes
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    sys.exit(_load_engine().main())
