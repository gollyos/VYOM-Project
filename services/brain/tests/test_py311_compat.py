"""Guard: bundled desktop runtime is Python 3.11 — app code must stay 3.11-compatible.

The 2026-08-27 installed build shipped ``app/agency/content_ops.py`` with a
backslash inside an f-string expression (PEP 701, Python 3.12-only syntax).
The dev machine runs 3.12 so nothing failed until the bundled 3.11 runtime
crashed at import with a SyntaxError and the desktop app showed
"VYOM Brain disconnected" forever.

Two layers of protection here:
1. If the bundled 3.11 interpreter exists on this machine, ast-parse every
   app file with it (authoritative).
2. Otherwise, walk the AST for f-string expressions containing backslash
   string constants (heuristic that works on 3.12 dev machines too).
"""

from __future__ import annotations

import ast
import shutil
import subprocess
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "app"
BUNDLED_PYTHON_CANDIDATES = (
    Path.home() / "AppData/Local/VYOM/runtime/python/python.exe",
    Path("C:/Users/GunjanAdmin/AppData/Local/VYOM/runtime/python/python.exe"),
)


def _bundled_python() -> str | None:
    for candidate in BUNDLED_PYTHON_CANDIDATES:
        if candidate.exists():
            return str(candidate)
    return None


def _scan_script() -> str:
    return (
        "import ast, pathlib, sys\n"
        f"root = pathlib.Path(r'{APP_DIR}')\n"
        "bad = []\n"
        "for p in root.rglob('*.py'):\n"
        "    try:\n"
        "        ast.parse(p.read_text(encoding='utf-8'))\n"
        "    except SyntaxError as e:\n"
        "        bad.append(f'{p}:{e.lineno}: {e.msg}')\n"
        "print('\\n'.join(bad))\n"
        "sys.exit(1 if bad else 0)\n"
    )


def _formatted_value_has_backslash(node: ast.AST) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and "\\" in sub.value:
            return True
    return False


def test_no_python312_only_fstring_syntax() -> None:
    """f-string expressions must not contain backslashes (3.12-only, PEP 701)."""
    violations: list[str] = []
    for path in sorted(APP_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.FormattedValue) and _formatted_value_has_backslash(node.value):
                violations.append(f"{path.relative_to(APP_DIR.parent)}: backslash inside f-string expression")
                break
    assert not violations, "Python 3.12-only f-string syntax found:\n" + "\n".join(violations)


def test_app_parses_under_bundled_runtime_if_present() -> None:
    """Authoritative check when the bundled 3.11 interpreter is available."""
    bundled = _bundled_python()
    if bundled is None or shutil.which(bundled) is None:
        if sys.version_info < (3, 12):
            # This dev interpreter is already 3.11-compatible; nothing extra to prove.
            return
        # Heuristic layer above still ran; skip silently when no bundled runtime.
        return
    result = subprocess.run(  # noqa: S603 - fixed script, fixed interpreter
        [bundled, "-c", _scan_script()],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, f"bundled-runtime parse failures:\n{result.stdout}{result.stderr}"
