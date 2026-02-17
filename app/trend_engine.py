"""
Trend computation engine.

Compares current codebase metrics against historical baselines.
Used by /api/analyze and by the Claude review prompt.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.database import CodebaseSnapshot


@dataclass
class TrendAnalysis:
    direction: str  # improving | stable | declining
    quality_delta: float
    complexity_delta: float
    lines_delta: int
    summary: str
    previous_score: float | None
    current_score: float


def compute_trend(
    db: Session,
    repo_name: str,
    branch: str,
    current_score: float,
    current_complexity: float,
    current_lines: int,
) -> TrendAnalysis:
    """Compare current metrics against the most recent baseline snapshot."""
    previous = (
        db.query(CodebaseSnapshot)
        .filter_by(repo_name=repo_name, branch=branch)
        .order_by(CodebaseSnapshot.timestamp.desc())
        .first()
    )

    if not previous:
        return TrendAnalysis(
            direction="stable",
            quality_delta=0.0,
            complexity_delta=0.0,
            lines_delta=0,
            summary="Primera ejecucion - sin baseline para comparar.",
            previous_score=None,
            current_score=current_score,
        )

    quality_delta = current_score - previous.quality_score
    complexity_delta = current_complexity - previous.complexity_avg
    lines_delta = current_lines - previous.total_lines

    if quality_delta > 1.0:
        direction = "improving"
    elif quality_delta < -1.0:
        direction = "declining"
    else:
        direction = "stable"

    parts = []
    if direction == "improving":
        parts.append(f"Calidad mejoro {quality_delta:+.1f} puntos ({previous.quality_score:.1f} -> {current_score:.1f})")
    elif direction == "declining":
        parts.append(f"Calidad bajo {quality_delta:+.1f} puntos ({previous.quality_score:.1f} -> {current_score:.1f})")
    else:
        parts.append(f"Calidad estable en {current_score:.1f}")

    if abs(lines_delta) > 50:
        parts.append(f"Codebase {'crecio' if lines_delta > 0 else 'se redujo'} en {abs(lines_delta)} lineas")

    if abs(complexity_delta) > 0.5:
        parts.append(f"Complejidad {'aumento' if complexity_delta > 0 else 'disminuyo'} en {abs(complexity_delta):.1f}")

    return TrendAnalysis(
        direction=direction,
        quality_delta=round(quality_delta, 2),
        complexity_delta=round(complexity_delta, 2),
        lines_delta=lines_delta,
        summary=". ".join(parts) + ".",
        previous_score=previous.quality_score,
        current_score=current_score,
    )
