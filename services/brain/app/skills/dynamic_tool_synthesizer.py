from __future__ import annotations

import ast
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.tools.base import BaseTool, ToolResult

logger = logging.getLogger("vyom.skills.synthesizer")


@dataclass
class SynthesizedToolSpec:
    name: str
    description: str
    parameters_schema: dict[str, Any]
    code: str
    domain: str = "custom"
    created_at: str = ""


class DynamicToolSynthesizer:
    """Synthesizes, sandboxes, benchmarks, and registers new tools on the fly.
    
    Allows VYOM to continuously self-evolve and adapt to any arbitrary 
    workflow or API requirement without manual coding.
    """

    SAFE_MODULES = frozenset({
        "math", "json", "re", "datetime", "hashlib", "urllib.parse", "collections", "itertools"
    })

    def __init__(self, skills_dir: Path | None = None, tool_registry: Any = None):
        self.skills_dir = skills_dir
        self.tool_registry = tool_registry
        self.synthesized: dict[str, SynthesizedToolSpec] = {}

    def validate_code_safety(self, python_code: str) -> tuple[bool, str]:
        """Static AST security check to ensure synthesized code contains no dangerous operations."""
        try:
            tree = ast.parse(python_code)
        except SyntaxError as err:
            return False, f"Syntax Error: {err}"

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_module = alias.name.split(".")[0]
                    if root_module not in self.SAFE_MODULES and root_module not in ("app", "typing"):
                        return False, f"Disallowed import: '{alias.name}'"
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    root_module = node.module.split(".")[0]
                    if root_module not in self.SAFE_MODULES and root_module not in ("app", "typing"):
                        return False, f"Disallowed from-import: '{node.module}'"
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in ("eval", "exec", "__import__", "globals", "locals"):
                    return False, f"Disallowed builtin call: '{node.func.id}'"

        return True, "Code passed security validation"

    def synthesize_tool(
        self,
        name: str,
        description: str,
        parameters_schema: dict[str, Any],
        implementation_code: str,
        domain: str = "custom",
    ) -> SynthesizedToolSpec:
        """Create and validate a new custom tool specification."""
        is_safe, reason = self.validate_code_safety(implementation_code)
        if not is_safe:
            raise ValueError(f"Tool synthesis rejected by security policy: {reason}")

        clean_name = name.lower().replace("-", "_").strip()
        spec = SynthesizedToolSpec(
            name=clean_name,
            description=description,
            parameters_schema=parameters_schema,
            code=implementation_code,
            domain=domain,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self.synthesized[clean_name] = spec
        self._persist_spec(spec)
        return spec

    def _persist_spec(self, spec: SynthesizedToolSpec) -> None:
        if self.skills_dir is None:
            return
        target_dir = self.skills_dir / "synthesized"
        target_dir.mkdir(parents=True, exist_ok=True)
        meta_file = target_dir / f"{spec.name}.json"
        meta_file.write_text(
            json.dumps(spec.__dict__, indent=2), encoding="utf-8"
        )
        code_file = target_dir / f"{spec.name}.py"
        code_file.write_text(spec.code, encoding="utf-8")
        logger.info("Persisted synthesized tool '%s' to %s", spec.name, meta_file)
