"""
Code analysis engine.

Calculates:
  - Lines of code (total, added, deleted)
  - Cyclomatic complexity (via radon)
  - Maintainability index
  - Quality score (composite 0-100)
"""

from __future__ import annotations

import os
import statistics
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from radon.complexity import cc_visit
from radon.metrics import mi_visit


ANALYZABLE_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx",
    ".java", ".go", ".rs", ".rb", ".php",
    ".c", ".cpp", ".h", ".cs",
}


@dataclass
class FileMetrics:
    path: str
    lines: int = 0
    complexity: float = 0.0
    maintainability: float = 100.0


@dataclass
class CommitMetrics:
    total_lines: int = 0
    lines_added: int = 0
    lines_deleted: int = 0
    files_changed: int = 0
    complexity_avg: float = 0.0
    maintainability_index: float = 100.0
    quality_score: float = 0.0
    file_details: list[FileMetrics] = field(default_factory=list)


def analyze_file(filepath: str) -> FileMetrics | None:
    """Analyze a single file for complexity and maintainability."""
    ext = Path(filepath).suffix.lower()
    if ext not in ANALYZABLE_EXTENSIONS:
        return None

    try:
        with open(filepath, "r", errors="ignore") as f:
            content = f.read()
    except (OSError, UnicodeDecodeError):
        return None

    lines = content.count("\n") + (1 if content and not content.endswith("\n") else 0)

    complexity = 0.0
    maintainability = 100.0

    if ext == ".py":
        try:
            blocks = cc_visit(content)
            if blocks:
                complexity = statistics.mean(b.complexity for b in blocks)
        except Exception:
            pass
        try:
            maintainability = mi_visit(content, multi=False)
        except Exception:
            maintainability = 50.0
    else:
        # Heuristic for non-Python: estimate complexity from nesting depth
        nesting = 0
        max_nesting = 0
        for char in content:
            if char == "{":
                nesting += 1
                max_nesting = max(max_nesting, nesting)
            elif char == "}":
                nesting = max(0, nesting - 1)
        complexity = min(max_nesting, 20)
        maintainability = max(0, 100 - (complexity * 4) - (lines / 50))

    return FileMetrics(
        path=filepath,
        lines=lines,
        complexity=round(complexity, 2),
        maintainability=round(max(0, min(100, maintainability)), 2),
    )


def compute_quality_score(metrics: CommitMetrics) -> float:
    """
    Composite score 0-100:
      40% maintainability index (normalized)
      30% low complexity (inverted)
      20% change size penalty (large diffs score lower)
      10% files-changed penalty
    """
    mi_score = min(metrics.maintainability_index, 100)

    complexity_score = max(0, 100 - (metrics.complexity_avg * 10))

    total_changed = metrics.lines_added + metrics.lines_deleted
    if total_changed <= 50:
        size_score = 100
    elif total_changed <= 200:
        size_score = 80
    elif total_changed <= 500:
        size_score = 60
    else:
        size_score = max(20, 100 - (total_changed / 20))

    if metrics.files_changed <= 3:
        files_score = 100
    elif metrics.files_changed <= 10:
        files_score = 70
    else:
        files_score = max(20, 100 - (metrics.files_changed * 3))

    return round(
        mi_score * 0.40
        + complexity_score * 0.30
        + size_score * 0.20
        + files_score * 0.10,
        1,
    )


def analyze_diff(diff_text: str) -> tuple[int, int]:
    """Count lines added and deleted from a unified diff."""
    added = 0
    deleted = 0
    for line in diff_text.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            deleted += 1
    return added, deleted


def analyze_directory(directory: str) -> CommitMetrics:
    """Walk a directory tree and produce aggregate metrics."""
    metrics = CommitMetrics()
    complexities = []
    maintainabilities = []

    for root, _, files in os.walk(directory):
        # Skip hidden dirs and common non-source dirs
        if any(part.startswith(".") or part in ("node_modules", "__pycache__", "venv", ".git")
               for part in Path(root).parts):
            continue

        for fname in files:
            fpath = os.path.join(root, fname)
            fm = analyze_file(fpath)
            if fm is None:
                continue

            metrics.total_lines += fm.lines
            metrics.files_changed += 1
            metrics.file_details.append(fm)
            complexities.append(fm.complexity)
            maintainabilities.append(fm.maintainability)

    if complexities:
        metrics.complexity_avg = round(statistics.mean(complexities), 2)
    if maintainabilities:
        metrics.maintainability_index = round(statistics.mean(maintainabilities), 2)

    metrics.quality_score = compute_quality_score(metrics)
    return metrics
