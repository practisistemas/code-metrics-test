"""
Markdown report generator.

Generates a .md file with:
  - Push summary and opinion
  - Code quality metrics
  - Integrity validation results
  - Recommendations
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.analyzer import CommitMetrics
from app.integrity import IntegrityResult


@dataclass
class PushInfo:
    repo_name: str
    branch: str
    pusher: str
    head_sha: str
    commit_message: str
    commit_count: int


def score_to_grade(score: float) -> str:
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"


def score_to_emoji(score: float) -> str:
    if score >= 80:
        return "green"
    if score >= 60:
        return "yellow"
    return "red"


def generate_opinion(metrics: CommitMetrics, integrity: IntegrityResult) -> str:
    """Generate a human-readable opinion about the push."""
    parts = []

    # Quality opinion
    grade = score_to_grade(metrics.quality_score)
    if grade in ("A", "B"):
        parts.append(
            f"**Excelente push.** La calidad del codigo es alta (Grade {grade}). "
            f"El indice de mantenibilidad es {metrics.maintainability_index}/100."
        )
    elif grade == "C":
        parts.append(
            f"**Push aceptable.** La calidad es moderada (Grade {grade}). "
            f"Se recomienda revisar la complejidad del codigo ({metrics.complexity_avg} promedio)."
        )
    else:
        parts.append(
            f"**Push con oportunidades de mejora.** La calidad es baja (Grade {grade}). "
            f"Complejidad alta ({metrics.complexity_avg}) y mantenibilidad baja ({metrics.maintainability_index}/100)."
        )

    # Size opinion
    total_changed = metrics.lines_added + metrics.lines_deleted
    if total_changed > 500:
        parts.append(
            f"El cambio es grande ({total_changed} lineas modificadas). "
            "Considerar dividir en commits mas pequenos para facilitar el code review."
        )
    elif total_changed > 200:
        parts.append(f"Cambio de tamano moderado ({total_changed} lineas).")
    else:
        parts.append(f"Cambio conciso ({total_changed} lineas). Buen tamano para review.")

    # Integrity opinion
    if integrity.status == "fail":
        parts.append(
            "**ALERTA:** Se detectaron problemas criticos de integridad. "
            "Posibles secretos o credenciales expuestas. Revisar urgentemente."
        )
    elif integrity.issues:
        parts.append(
            f"Se encontraron {len(integrity.issues)} advertencias de integridad (no criticas)."
        )
    else:
        parts.append("Sin problemas de integridad detectados.")

    return "\n\n".join(parts)


def generate_recommendations(metrics: CommitMetrics, integrity: IntegrityResult) -> list[str]:
    """Generate actionable recommendations."""
    recs = []

    if metrics.complexity_avg > 10:
        recs.append("Reducir la complejidad ciclomatica: extraer funciones mas pequenas")
    if metrics.maintainability_index < 60:
        recs.append("Mejorar mantenibilidad: simplificar logica, agregar documentacion")
    if metrics.lines_added > 300 and metrics.files_changed > 8:
        recs.append("Dividir cambios grandes en PRs mas focalizados")
    if any(i.issue_type == "secret" for i in integrity.issues):
        recs.append("CRITICO: Remover credenciales/secretos del codigo. Usar variables de entorno")
    if any(i.issue_type == "debug" for i in integrity.issues):
        recs.append("Limpiar codigo de debug (console.log, debugger, etc.)")
    if any(i.issue_type == "binary" for i in integrity.issues):
        recs.append("Mover archivos binarios a un servicio de almacenamiento externo")
    if not recs:
        recs.append("Sin recomendaciones adicionales. El codigo se ve bien.")

    return recs


def generate_markdown_report(
    push: PushInfo,
    metrics: CommitMetrics,
    integrity: IntegrityResult,
) -> str:
    """Generate a full Markdown report."""
    grade = score_to_grade(metrics.quality_score)
    color = score_to_emoji(metrics.quality_score)
    opinion = generate_opinion(metrics, integrity)
    recs = generate_recommendations(metrics, integrity)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    report = f"""# Code Metrics Report

> Generated: {now}

---

## Push Summary

| Field | Value |
|-------|-------|
| **Repository** | `{push.repo_name}` |
| **Branch** | `{push.branch}` |
| **Pusher** | `{push.pusher}` |
| **Head Commit** | `{push.head_sha[:8]}` |
| **Commit Message** | {push.commit_message[:100]} |
| **Commits in Push** | {push.commit_count} |

---

## Quality Score

| Metric | Value |
|--------|-------|
| **Overall Score** | **{metrics.quality_score}/100** (Grade **{grade}**) |
| **Integrity** | {integrity.status.upper()} |

---

## Code Metrics

| Metric | Value |
|--------|-------|
| Total Lines of Code | {metrics.total_lines:,} |
| Lines Added | +{metrics.lines_added:,} |
| Lines Deleted | -{metrics.lines_deleted:,} |
| Files Changed | {metrics.files_changed} |
| Avg Cyclomatic Complexity | {metrics.complexity_avg} |
| Maintainability Index | {metrics.maintainability_index}/100 |

---

## Integrity Validation

- **Status:** {integrity.status.upper()}
- **Content Hash:** `{integrity.content_hash[:16]}...`
- **Files Scanned:** {integrity.files_scanned}
"""

    if integrity.issues:
        report += "\n### Issues Found\n\n"
        report += "| File | Type | Severity | Detail |\n"
        report += "|------|------|----------|--------|\n"
        for issue in integrity.issues:
            report += f"| `{issue.file}` | {issue.issue_type} | **{issue.severity}** | {issue.detail} |\n"

    report += f"""
---

## Opinion

{opinion}

---

## Recommendations

"""
    for i, rec in enumerate(recs, 1):
        report += f"{i}. {rec}\n"

    report += f"""
---

*Report generated by Code Metrics v1.0*
"""

    return report
