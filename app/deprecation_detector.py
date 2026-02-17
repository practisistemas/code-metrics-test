"""
Deprecation detector.

Scans code for deprecated function/API usage across multiple languages.
Also uses Claude to identify context-specific deprecations.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class DeprecationWarning:
    file: str
    line: int
    pattern: str
    message: str
    language: str
    severity: str = "warning"  # warning | critical


# ── Known deprecated patterns by language ──────────────────────

PYTHON_DEPRECATIONS = [
    (r"\bos\.popen\b", "os.popen() is deprecated. Use subprocess.run() instead"),
    (r"\boptparse\b", "optparse is deprecated. Use argparse instead"),
    (r"\bimp\b\.\w+", "imp module is deprecated. Use importlib instead"),
    (r"\bcgi\b\.\w+", "cgi module is deprecated since Python 3.11. Use alternatives"),
    (r"\bpkg_resources\b", "pkg_resources is deprecated. Use importlib.metadata instead"),
    (r"\basyncio\.coroutine\b", "asyncio.coroutine is deprecated. Use async def instead"),
    (r"\bcollections\.(Mapping|MutableMapping|Sequence|MutableSequence|Set)\b",
     "collections.ABC classes moved to collections.abc"),
    (r"\btyping\.(Dict|List|Tuple|Set|FrozenSet|Type)\b",
     "typing.Dict/List/etc deprecated since 3.9. Use dict, list, tuple directly"),
    (r"\bunittest\.makeSuite\b", "unittest.makeSuite() is deprecated"),
    (r"\blogging\.warn\b", "logging.warn() is deprecated. Use logging.warning()"),
    (r"\bbase64\.encodestring\b", "base64.encodestring() removed. Use base64.encodebytes()"),
    (r"\bthreading\.currentThread\b", "threading.currentThread() deprecated. Use current_thread()"),
    (r"\bsqlite3\.OptimizedUnicode\b", "sqlite3.OptimizedUnicode deprecated since 3.10"),
    (r"@asyncio\.coroutine", "@asyncio.coroutine decorator deprecated. Use async def"),
    (r"\bdistutils\b", "distutils is deprecated since Python 3.12. Use setuptools"),
]

JAVASCRIPT_DEPRECATIONS = [
    (r"\b__defineGetter__\b", "__defineGetter__ is deprecated. Use Object.defineProperty()"),
    (r"\b__defineSetter__\b", "__defineSetter__ is deprecated. Use Object.defineProperty()"),
    (r"\bescape\(", "escape() is deprecated. Use encodeURIComponent()"),
    (r"\bunescape\(", "unescape() is deprecated. Use decodeURIComponent()"),
    (r"\bdocument\.write\b", "document.write() is deprecated. Manipulate DOM directly"),
    (r"\b\.substr\(", "String.substr() is deprecated. Use .substring() or .slice()"),
    (r"\bnew\s+Buffer\(", "new Buffer() is deprecated. Use Buffer.from() or Buffer.alloc()"),
    (r"\bfs\.exists\(", "fs.exists() is deprecated. Use fs.access() or fs.stat()"),
    (r"\brequire\(\s*['\"]crypto['\"]", "Consider: Node.js crypto some methods are deprecated"),
    (r"\bcomponentWillMount\b", "componentWillMount is deprecated. Use componentDidMount"),
    (r"\bcomponentWillReceiveProps\b", "componentWillReceiveProps deprecated. Use getDerivedStateFromProps"),
    (r"\bcomponentWillUpdate\b", "componentWillUpdate deprecated. Use getSnapshotBeforeUpdate"),
    (r"\bReactDOM\.render\b", "ReactDOM.render() deprecated in React 18. Use createRoot()"),
    (r"\bpropTypes\s*=", "PropTypes is deprecated for TypeScript projects. Use TS interfaces"),
]

JAVA_DEPRECATIONS = [
    (r"\bnew\s+Date\(\s*\d", "Date(int, int, int) constructor deprecated. Use LocalDate"),
    (r"\b\.stop\(\)\s*;.*Thread", "Thread.stop() is deprecated and dangerous"),
    (r"\b\.suspend\(\)\s*;.*Thread", "Thread.suspend() is deprecated"),
    (r"\b\.resume\(\)\s*;.*Thread", "Thread.resume() is deprecated"),
    (r"\bnew\s+Integer\(", "new Integer() deprecated since Java 9. Use Integer.valueOf()"),
    (r"\bnew\s+Boolean\(", "new Boolean() deprecated. Use Boolean.valueOf()"),
    (r"\bRuntime\.getRuntime\(\)\.exec\(String\b", "Runtime.exec(String) deprecated. Use ProcessBuilder"),
    (r"\b@SuppressWarnings\(\"deprecation\"\)", "Code explicitly suppressing deprecation warnings"),
]

GO_DEPRECATIONS = [
    (r"\bioutil\.\w+", "ioutil package is deprecated since Go 1.16. Use io and os packages"),
    (r"\bstrings\.Title\b", "strings.Title() deprecated since Go 1.18. Use golang.org/x/text"),
    (r"\bsyscall\.\w+", "syscall package is deprecated. Use golang.org/x/sys"),
]

GENERAL_DEPRECATIONS = [
    (r"@[Dd]eprecated", "Contains @Deprecated annotation - review if still needed"),
    (r"#\s*pragma.*deprecated", "Contains #pragma deprecated"),
    (r"\[\[deprecated\]\]", "Contains [[deprecated]] attribute (C++14+)"),
    (r"DeprecationWarning", "Code references DeprecationWarning"),
    (r"DEPRECATED", "Contains DEPRECATED marker"),
]

LANG_MAP = {
    ".py": PYTHON_DEPRECATIONS,
    ".js": JAVASCRIPT_DEPRECATIONS,
    ".jsx": JAVASCRIPT_DEPRECATIONS,
    ".ts": JAVASCRIPT_DEPRECATIONS,
    ".tsx": JAVASCRIPT_DEPRECATIONS,
    ".java": JAVA_DEPRECATIONS,
    ".go": GO_DEPRECATIONS,
}


def detect_deprecations(directory: str) -> list[DeprecationWarning]:
    """Scan all source files for deprecated patterns."""
    warnings: list[DeprecationWarning] = []

    for root, _, files in os.walk(directory):
        if any(part.startswith(".") or part in ("node_modules", "__pycache__", "venv", ".git", "dist", "build")
               for part in Path(root).parts):
            continue

        for fname in files:
            # Skip self-detection (this file contains patterns as strings, not usage)
            if fname == "deprecation_detector.py":
                continue

            fpath = os.path.join(root, fname)
            ext = Path(fname).suffix.lower()

            patterns = LANG_MAP.get(ext, []) + GENERAL_DEPRECATIONS
            if not patterns:
                continue

            try:
                with open(fpath, "r", errors="ignore") as f:
                    lines = f.readlines()
            except OSError:
                continue

            rel_path = os.path.relpath(fpath, directory)

            for line_num, line_content in enumerate(lines, 1):
                for pattern, message in patterns:
                    if re.search(pattern, line_content):
                        lang = {
                            ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript",
                            ".ts": "TypeScript", ".tsx": "TypeScript",
                            ".java": "Java", ".go": "Go",
                        }.get(ext, "General")

                        warnings.append(DeprecationWarning(
                            file=rel_path,
                            line=line_num,
                            pattern=pattern[:50],
                            message=message,
                            language=lang,
                        ))
                        break  # one warning per line

    return warnings


def format_deprecations_md(warnings: list[DeprecationWarning]) -> str:
    """Format deprecation warnings as a Markdown section."""
    if not warnings:
        return "Sin deprecaciones detectadas."

    lines = [f"Se detectaron **{len(warnings)}** uso(s) de funciones/APIs deprecadas:\n"]
    lines.append("| Archivo | Linea | Lenguaje | Detalle |")
    lines.append("|---------|-------|----------|---------|")

    for w in warnings[:50]:  # cap at 50 to avoid huge reports
        lines.append(f"| `{w.file}` | {w.line} | {w.language} | {w.message} |")

    if len(warnings) > 50:
        lines.append(f"\n... y {len(warnings) - 50} mas.")

    return "\n".join(lines)
