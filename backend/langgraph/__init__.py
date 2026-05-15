# backend/langgraph/__init__.py
"""LangGraph orchestration layer — DAG-based multi-agent pipeline."""
import os
import sys


# ── Resolve package shadowing ──────────────────────────────────────────────
# This local `langgraph` package shadows the installed `langgraph` library on
# PyPI.  By extending ``__path__`` to include the installed package's directory,
# submodule lookups (e.g. ``langgraph.graph``, ``langgraph.pregel``) resolve
# from the installed library while our own modules (``state``, ``agents``) take
# precedence because our directory is listed first.
_OUR_DIR = os.path.dirname(os.path.abspath(__file__))

# langgraph 1.1+ is a PEP 420 implicit namespace package (no top-level __init__.py).
# Check for the presence of known submodules. Support both:
#   - graph/__init__.py (package — langgraph >= 1.1)
#   - graph.py (module — older langgraph, unlikely but safe)
_INSTALLED_FOUND = False

for _site_dir in __import__("site").getsitepackages():
    _installed = os.path.join(_site_dir, "langgraph")
    if not os.path.isdir(_installed):
        continue
    # Check for subpackage (graph/__init__.py) or module (graph.py)
    if os.path.exists(os.path.join(_installed, "graph", "__init__.py")) or \
       os.path.exists(os.path.join(_installed, "graph.py")):
        __path__ = [_installed, _OUR_DIR]  # type: ignore[valid-type]
        _INSTALLED_FOUND = True
        break

if not _INSTALLED_FOUND:
    raise ImportError(
        "Cannot find the installed langgraph SDK. "
        "The local 'langgraph/' package in backend/ shadows the library. "
        "Run: pip install 'langgraph>=1.1.10'"
    )
