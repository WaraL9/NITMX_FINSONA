"""Catalogue of server text shown in the UI (E8-13, backend half).

    python -m app.i18n_catalog            # list every th() template
    python -m app.i18n_catalog --missing  # templates without English in the frontend dictionary

Every `th(...)` call in app/ becomes a template: a string constant as-is; an f-string with
each `{expression}` replaced by `{0}`, `{1}`, ... in order. Evidence-hint placeholders like
`{{amount}}` stay as they are. The frontend (`src/lib/i18n.ts` trServer) matches rendered
Thai text against these templates to show English from `src/i18n/en_server.json`.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

from app.config import REPO_DIR

APP_DIR = Path(__file__).resolve().parent
EN_FILE = REPO_DIR / "frontend" / "src" / "i18n" / "en_server.json"
PLACEHOLDER = re.compile(r"\{\d+\}|\{\{[a-z_]+\}\}")


def _template(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts, n = [], 0
        for v in node.values:
            if isinstance(v, ast.Constant):
                parts.append(str(v.value))
            else:
                parts.append(f"{{{n}}}")
                n += 1
        return "".join(parts)
    return None


def templates() -> dict[str, list[str]]:
    """template -> where it is used (file:line)."""
    out: dict[str, list[str]] = {}
    for path in sorted(APP_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "th"
                    and len(node.args) == 1):
                t = _template(node.args[0])
                if t is None:
                    raise ValueError(f"{path}:{node.lineno}: th() needs a string or f-string literal")
                out.setdefault(t, []).append(f"{path.relative_to(APP_DIR.parent)}:{node.lineno}")
    return out


def placeholders(text: str) -> list[str]:
    return sorted(PLACEHOLDER.findall(text))


def load_english() -> dict[str, str]:
    return json.loads(EN_FILE.read_text(encoding="utf-8")) if EN_FILE.exists() else {}


if __name__ == "__main__":
    cat, en = templates(), load_english()
    items = [(t, w) for t, w in cat.items() if "--missing" not in sys.argv or t not in en]
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps([{"th": t, "where": w[:2]} for t, w in items], ensure_ascii=False, indent=1))
