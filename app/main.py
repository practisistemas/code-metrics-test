"""
Code Metrics API & Dashboard.

Endpoints:
  POST /api/analyze     - Receive push event, clone, analyze with Claude, store results
  GET  /api/results     - List analysis results (JSON)
  GET  /api/results/:id - Single analysis detail (includes Claude review)
  GET  /api/report/:id  - Download .md report
  GET  /health          - Health check
  GET  /                - Dashboard (mini portal)
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.analyzer import analyze_diff, analyze_directory
from app.claude_review import ClaudeReview, review_with_claude
from app.database import CommitAnalysis, PushEvent, Repository, get_db, init_db
from app.deprecation_detector import detect_deprecations, format_deprecations_md
from app.integrity import validate_integrity
from app.reporter import PushInfo, generate_markdown_report


app = FastAPI(title="Code Metrics", version="1.0.0")
templates = Jinja2Templates(directory="app/templates")


# ── Request models ──────────────────────────────────────────────

class PushPayload(BaseModel):
    """Matches the payload sent from GitHub Actions."""
    repo_name: str
    repo_url: str
    branch: str
    head_sha: str
    pusher: str
    commits: list[CommitPayload] = []


class CommitPayload(BaseModel):
    sha: str
    message: str
    author: str
    added: list[str] = []
    modified: list[str] = []
    removed: list[str] = []


# ── Health ──────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "service": "code-metrics"}


# ── Analysis endpoint (called from GitHub Actions) ─────────────

@app.post("/api/analyze")
def analyze_push(payload: PushPayload, db: Session = Depends(get_db)):
    # Upsert repository
    repo = db.query(Repository).filter_by(name=payload.repo_name).first()
    if not repo:
        repo = Repository(name=payload.repo_name, url=payload.repo_url)
        db.add(repo)
        db.flush()

    # Clone full repo into temp dir
    work_dir = tempfile.mkdtemp(prefix="metrics-")
    try:
        subprocess.run(
            ["git", "clone", "--branch", payload.branch, payload.repo_url, work_dir],
            capture_output=True, timeout=300, check=True,
        )

        # ── Step 1: Static analysis (radon, LOC, complexity) ───
        code_metrics = analyze_directory(work_dir)

        # Get diff for the head commit
        diff_text = ""
        diff_result = subprocess.run(
            ["git", "-C", work_dir, "diff", "HEAD~1", "HEAD"],
            capture_output=True, text=True, timeout=30,
        )
        if diff_result.returncode == 0:
            diff_text = diff_result.stdout
            added, deleted = analyze_diff(diff_text)
            code_metrics.lines_added = added
            code_metrics.lines_deleted = deleted

        # ── Step 2: Integrity validation ───────────────────────
        integrity = validate_integrity(work_dir)

        # ── Step 3: Deprecation detection ─────────────────────
        deprecation_warnings = detect_deprecations(work_dir)
        deprecation_md = format_deprecations_md(deprecation_warnings)

        # ── Step 4: Claude AI review ───────────────────────────
        commit_msg = payload.commits[0].message if payload.commits else ""
        claude_review = review_with_claude(
            diff_text=diff_text,
            metrics=code_metrics,
            integrity=integrity,
            commit_message=commit_msg,
            repo_name=payload.repo_name,
            branch=payload.branch,
        )

        # ── Step 5: Generate .md report ────────────────────────
        push_info = PushInfo(
            repo_name=payload.repo_name,
            branch=payload.branch,
            pusher=payload.pusher,
            head_sha=payload.head_sha,
            commit_message=commit_msg,
            commit_count=len(payload.commits),
        )
        md_report = generate_markdown_report(push_info, code_metrics, integrity)

        # Append deprecation warnings
        md_report += "\n\n---\n\n## Deprecation Warnings\n\n"
        md_report += deprecation_md

        # Append Claude's review to the markdown report
        md_report += "\n\n---\n\n## Claude AI Review\n\n"
        md_report += claude_review.raw_response or claude_review.opinion

        # ── Step 6: Store in database ──────────────────────────
        analysis = CommitAnalysis(
            repo_name=payload.repo_name,
            commit_sha=payload.head_sha,
            branch=payload.branch,
            author=payload.pusher,
            message=commit_msg,
            total_lines=code_metrics.total_lines,
            lines_added=code_metrics.lines_added,
            lines_deleted=code_metrics.lines_deleted,
            files_changed=code_metrics.files_changed,
            complexity_avg=code_metrics.complexity_avg,
            maintainability_index=code_metrics.maintainability_index,
            quality_score=code_metrics.quality_score,
            integrity_hash=integrity.content_hash,
            integrity_status=integrity.status,
            claude_review=claude_review.raw_response or claude_review.opinion,
            md_report=md_report,
            deprecation_warnings=deprecation_md,
        )
        db.add(analysis)

        push_event = PushEvent(
            repo_name=payload.repo_name,
            branch=payload.branch,
            pusher=payload.pusher,
            commit_count=len(payload.commits),
            head_sha=payload.head_sha,
            overall_score=code_metrics.quality_score,
        )
        db.add(push_event)
        db.commit()

        return {
            "status": "success",
            "analysis_id": analysis.id,
            "quality_score": code_metrics.quality_score,
            "integrity": integrity.status,
            "issues_count": len(integrity.issues),
            "claude_review": {
                "opinion": claude_review.opinion[:500],
                "suggestions": claude_review.suggestions,
                "security": claude_review.security_notes,
                "summary": claude_review.overall_summary,
            },
            "metrics": {
                "total_lines": code_metrics.total_lines,
                "lines_added": code_metrics.lines_added,
                "lines_deleted": code_metrics.lines_deleted,
                "files_changed": code_metrics.files_changed,
                "complexity_avg": code_metrics.complexity_avg,
                "maintainability_index": code_metrics.maintainability_index,
            },
            "report_url": f"/api/report/{analysis.id}",
            "deprecations_found": len(deprecation_warnings),
        }
    except subprocess.CalledProcessError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Git clone failed: {e.stderr.decode() if isinstance(e.stderr, bytes) else e.stderr}",
        )
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


# ── Results API ────────────────────────────────────────────────

@app.get("/api/results")
def list_results(repo: str | None = None, limit: int = 50, db: Session = Depends(get_db)):
    query = db.query(CommitAnalysis).order_by(CommitAnalysis.timestamp.desc())
    if repo:
        query = query.filter_by(repo_name=repo)
    results = query.limit(limit).all()
    return [
        {
            "id": r.id,
            "repo": r.repo_name,
            "sha": r.commit_sha[:8],
            "branch": r.branch,
            "author": r.author,
            "message": r.message[:80],
            "quality_score": r.quality_score,
            "total_lines": r.total_lines,
            "lines_added": r.lines_added,
            "lines_deleted": r.lines_deleted,
            "complexity": r.complexity_avg,
            "integrity": r.integrity_status,
            "has_claude_review": bool(r.claude_review),
            "timestamp": r.timestamp.isoformat() if r.timestamp else None,
        }
        for r in results
    ]


@app.get("/api/results/{analysis_id}")
def get_result(analysis_id: int, db: Session = Depends(get_db)):
    r = db.query(CommitAnalysis).get(analysis_id)
    if not r:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return {
        "id": r.id,
        "repo": r.repo_name,
        "sha": r.commit_sha,
        "branch": r.branch,
        "author": r.author,
        "message": r.message,
        "quality_score": r.quality_score,
        "total_lines": r.total_lines,
        "lines_added": r.lines_added,
        "lines_deleted": r.lines_deleted,
        "files_changed": r.files_changed,
        "complexity_avg": r.complexity_avg,
        "maintainability_index": r.maintainability_index,
        "integrity_hash": r.integrity_hash,
        "integrity_status": r.integrity_status,
        "claude_review": r.claude_review,
        "timestamp": r.timestamp.isoformat() if r.timestamp else None,
    }


# ── Markdown Report Download ──────────────────────────────────

@app.get("/api/report/{analysis_id}")
def get_report(analysis_id: int, db: Session = Depends(get_db)):
    r = db.query(CommitAnalysis).get(analysis_id)
    if not r:
        raise HTTPException(status_code=404, detail="Analysis not found")
    if not r.md_report:
        raise HTTPException(status_code=404, detail="Report not generated yet")
    return PlainTextResponse(
        content=r.md_report,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="report-{r.commit_sha[:8]}.md"'},
    )


# ── Dashboard (mini portal) ───────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    recent = (
        db.query(CommitAnalysis)
        .order_by(CommitAnalysis.timestamp.desc())
        .limit(20)
        .all()
    )
    pushes = (
        db.query(PushEvent)
        .order_by(PushEvent.timestamp.desc())
        .limit(10)
        .all()
    )
    repos = db.query(Repository).all()

    total_analyses = db.query(CommitAnalysis).count()
    avg_score = 0.0
    if total_analyses > 0:
        scores = [r.quality_score for r in db.query(CommitAnalysis).all()]
        avg_score = round(sum(scores) / len(scores), 1)

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "recent": recent,
        "pushes": pushes,
        "repos": repos,
        "total_analyses": total_analyses,
        "avg_score": avg_score,
    })
