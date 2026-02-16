"""
Claude-powered code review and analysis.

Uses Claude API to:
  - Analyze code quality with AI reasoning
  - Generate opinions on push changes
  - Detect code smells and suggest improvements
  - Produce a natural-language report
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import anthropic

from app.analyzer import CommitMetrics
from app.integrity import IntegrityResult


ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5-20250929")


@dataclass
class ClaudeReview:
    opinion: str = ""
    code_smells: list[str] | None = None
    suggestions: list[str] | None = None
    security_notes: str = ""
    overall_summary: str = ""
    raw_response: str = ""


def _build_review_prompt(
    diff_text: str,
    metrics: CommitMetrics,
    integrity: IntegrityResult,
    commit_message: str,
    repo_name: str,
    branch: str,
) -> str:
    integrity_issues_text = ""
    if integrity.issues:
        integrity_issues_text = "\n".join(
            f"  - [{i.severity.upper()}] {i.file}: {i.detail}"
            for i in integrity.issues
        )
    else:
        integrity_issues_text = "  Ninguno"

    return f"""Eres un senior code reviewer experto. Analiza el siguiente push y genera un reporte detallado en espanol.

## Contexto del Push
- **Repositorio:** {repo_name}
- **Branch:** {branch}
- **Commit message:** {commit_message}

## Metricas Calculadas
- Total lineas de codigo: {metrics.total_lines:,}
- Lineas agregadas: +{metrics.lines_added}
- Lineas eliminadas: -{metrics.lines_deleted}
- Archivos cambiados: {metrics.files_changed}
- Complejidad ciclomatica promedio: {metrics.complexity_avg}
- Indice de mantenibilidad: {metrics.maintainability_index}/100
- Puntaje de calidad: {metrics.quality_score}/100

## Resultado de Integridad
- Status: {integrity.status.upper()}
- Archivos escaneados: {integrity.files_scanned}
- Issues encontrados:
{integrity_issues_text}

## Diff del Push (ultimas modificaciones)
```
{diff_text[:15000]}
```

---

Genera tu reporte con las siguientes secciones:

1. **OPINION GENERAL**: Tu opinion honesta sobre este push (2-3 parrafos). Incluye si el commit message es descriptivo, si el tamano del cambio es apropiado, y la calidad general.

2. **CODE SMELLS**: Lista de code smells o malas practicas detectadas. Si no hay, indicalo.

3. **SUGERENCIAS DE MEJORA**: Recomendaciones concretas y accionables para mejorar el codigo.

4. **SEGURIDAD**: Notas sobre seguridad si aplica (credenciales expuestas, vulnerabilidades, etc).

5. **RESUMEN**: Un resumen de una linea con el puntaje que le darias al push (1-10).

Responde en formato Markdown limpio."""


def review_with_claude(
    diff_text: str,
    metrics: CommitMetrics,
    integrity: IntegrityResult,
    commit_message: str = "",
    repo_name: str = "",
    branch: str = "main",
) -> ClaudeReview:
    """Send code diff and metrics to Claude for AI-powered review."""
    if not ANTHROPIC_API_KEY:
        return ClaudeReview(
            opinion="Claude API key not configured. Set ANTHROPIC_API_KEY environment variable.",
            overall_summary="No AI review available - API key missing",
        )

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    prompt = _build_review_prompt(
        diff_text=diff_text,
        metrics=metrics,
        integrity=integrity,
        commit_message=commit_message,
        repo_name=repo_name,
        branch=branch,
    )

    try:
        message = client.messages.create(
            model=MODEL,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        response_text = message.content[0].text

        review = ClaudeReview(raw_response=response_text)
        _parse_review(review, response_text)
        return review

    except anthropic.APIError as e:
        return ClaudeReview(
            opinion=f"Claude API error: {e}",
            overall_summary="AI review failed",
        )


def _parse_review(review: ClaudeReview, text: str) -> None:
    """Best-effort parse of Claude's markdown response into structured fields."""
    sections = text.split("##")

    review.opinion = text  # fallback: whole response as opinion

    for section in sections:
        lower = section.lower().strip()
        content = section.strip()

        if lower.startswith("opinion") or "opinion general" in lower:
            review.opinion = _clean_section(content)
        elif "code smell" in lower or "malas practicas" in lower:
            review.code_smells = _extract_list(content)
        elif "sugerencia" in lower or "mejora" in lower:
            review.suggestions = _extract_list(content)
        elif "seguridad" in lower:
            review.security_notes = _clean_section(content)
        elif "resumen" in lower:
            review.overall_summary = _clean_section(content)


def _clean_section(text: str) -> str:
    """Remove the heading line from a section."""
    lines = text.strip().split("\n")
    if lines:
        return "\n".join(lines[1:]).strip()
    return text.strip()


def _extract_list(text: str) -> list[str]:
    """Extract bullet points from a section."""
    items = []
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith(("-", "*", "1", "2", "3", "4", "5", "6", "7", "8", "9")):
            # Strip leading markers
            cleaned = line.lstrip("-*0123456789. ").strip()
            if cleaned:
                items.append(cleaned)
    return items if items else ["Sin observaciones"]
