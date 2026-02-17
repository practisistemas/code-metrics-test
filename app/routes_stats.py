"""
Statistics and chart data API routes.

All endpoints return data shaped for Chart.js and support date filtering.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import (
    CodebaseSnapshot, CommitAnalysis, DeveloperStats,
    PushEvent, get_db,
)

router = APIRouter(tags=["statistics"])


def _parse_date(date_str: str | None) -> datetime | None:
    if not date_str:
        return None
    try:
        dt = datetime.fromisoformat(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _apply_date_filter(query, model, from_date: str | None, to_date: str | None):
    fd = _parse_date(from_date)
    td = _parse_date(to_date)
    if fd:
        query = query.filter(model.timestamp >= fd)
    if td:
        query = query.filter(model.timestamp <= td)
    return query


# ── Developers list (for dropdown) ────────────────────────────

@router.get("/api/developers")
def list_developers(repo: str | None = None, db: Session = Depends(get_db)):
    query = db.query(CommitAnalysis.author).distinct()
    if repo:
        query = query.filter(CommitAnalysis.repo_name == repo)
    return [r[0] for r in query.all() if r[0]]


# ── Developer stats with date filtering ───────────────────────

@router.get("/api/stats/developers")
def get_developer_stats(
    repo: str | None = None,
    developer: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(
        CommitAnalysis.author,
        func.count(CommitAnalysis.id).label("total_pushes"),
        func.sum(CommitAnalysis.lines_added).label("total_lines_added"),
        func.sum(CommitAnalysis.lines_deleted).label("total_lines_deleted"),
        func.avg(CommitAnalysis.quality_score).label("avg_quality_score"),
        func.avg(CommitAnalysis.complexity_avg).label("avg_complexity"),
        func.max(CommitAnalysis.quality_score).label("best_score"),
        func.min(CommitAnalysis.quality_score).label("worst_score"),
        func.min(CommitAnalysis.timestamp).label("first_push"),
        func.max(CommitAnalysis.timestamp).label("last_push"),
    ).group_by(CommitAnalysis.author)

    if repo:
        query = query.filter(CommitAnalysis.repo_name == repo)
    if developer:
        query = query.filter(CommitAnalysis.author == developer)
    query = _apply_date_filter(query, CommitAnalysis, from_date, to_date)

    return [
        {
            "developer": r.author,
            "total_pushes": r.total_pushes,
            "total_lines_added": r.total_lines_added or 0,
            "total_lines_deleted": r.total_lines_deleted or 0,
            "avg_quality_score": round(r.avg_quality_score or 0, 1),
            "avg_complexity": round(r.avg_complexity or 0, 2),
            "best_score": r.best_score or 0,
            "worst_score": r.worst_score or 0,
            "first_push": r.first_push.isoformat() if r.first_push else None,
            "last_push": r.last_push.isoformat() if r.last_push else None,
        }
        for r in query.all()
        if r.author
    ]


# ── Score evolution (line chart) ──────────────────────────────

@router.get("/api/stats/score-evolution")
def get_score_evolution(
    repo: str | None = None,
    developer: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    db: Session = Depends(get_db),
):
    query = (
        db.query(CommitAnalysis)
        .order_by(CommitAnalysis.timestamp.asc())
    )
    if repo:
        query = query.filter(CommitAnalysis.repo_name == repo)
    if developer:
        query = query.filter(CommitAnalysis.author == developer)
    query = _apply_date_filter(query, CommitAnalysis, from_date, to_date)

    results = query.all()

    # Group by developer
    dev_data: dict[str, dict] = {}
    all_labels: list[str] = []

    for r in results:
        if not r.author:
            continue
        label = r.timestamp.strftime("%Y-%m-%d %H:%M") if r.timestamp else ""
        if label not in all_labels:
            all_labels.append(label)

        if r.author not in dev_data:
            dev_data[r.author] = {"developer": r.author, "scores": [], "complexity": [], "maintainability": [], "labels": []}

        dev_data[r.author]["scores"].append(r.quality_score)
        dev_data[r.author]["complexity"].append(r.complexity_avg)
        dev_data[r.author]["maintainability"].append(r.maintainability_index)
        dev_data[r.author]["labels"].append(label)

    return {
        "labels": all_labels,
        "datasets": list(dev_data.values()),
    }


# ── Push activity (bar chart) ─────────────────────────────────

@router.get("/api/stats/push-activity")
def get_push_activity(
    repo: str | None = None,
    developer: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(CommitAnalysis).order_by(CommitAnalysis.timestamp.asc())
    if repo:
        query = query.filter(CommitAnalysis.repo_name == repo)
    if developer:
        query = query.filter(CommitAnalysis.author == developer)
    query = _apply_date_filter(query, CommitAnalysis, from_date, to_date)

    results = query.all()

    # Group by week and developer
    week_dev: dict[str, dict[str, dict]] = {}
    week_order: list[str] = []

    for r in results:
        if not r.author or not r.timestamp:
            continue
        iso = r.timestamp.isocalendar()
        week_label = f"{iso[0]}-W{iso[1]:02d}"
        if week_label not in week_order:
            week_order.append(week_label)

        if week_label not in week_dev:
            week_dev[week_label] = {}
        if r.author not in week_dev[week_label]:
            week_dev[week_label][r.author] = {"pushes": 0, "lines_added": 0}

        week_dev[week_label][r.author]["pushes"] += 1
        week_dev[week_label][r.author]["lines_added"] += r.lines_added or 0

    # Build datasets per developer
    all_devs = sorted({dev for week in week_dev.values() for dev in week})
    datasets = []
    for dev in all_devs:
        datasets.append({
            "developer": dev,
            "pushes": [week_dev.get(w, {}).get(dev, {}).get("pushes", 0) for w in week_order],
            "lines_added": [week_dev.get(w, {}).get(dev, {}).get("lines_added", 0) for w in week_order],
        })

    return {"labels": week_order, "datasets": datasets}


# ── Quality distribution (donut chart) ────────────────────────

@router.get("/api/stats/quality-distribution")
def get_quality_distribution(
    repo: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(CommitAnalysis.quality_score)
    if repo:
        query = query.filter(CommitAnalysis.repo_name == repo)
    query = _apply_date_filter(query, CommitAnalysis, from_date, to_date)

    scores = [r[0] for r in query.all() if r[0] is not None]

    buckets = {"A (90-100)": 0, "B (80-89)": 0, "C (70-79)": 0, "D (60-69)": 0, "F (0-59)": 0}
    for s in scores:
        if s >= 90:
            buckets["A (90-100)"] += 1
        elif s >= 80:
            buckets["B (80-89)"] += 1
        elif s >= 70:
            buckets["C (70-79)"] += 1
        elif s >= 60:
            buckets["D (60-69)"] += 1
        else:
            buckets["F (0-59)"] += 1

    return {
        "labels": list(buckets.keys()),
        "counts": list(buckets.values()),
        "colors": ["#3fb950", "#56d364", "#d29922", "#e3b341", "#f85149"],
    }


# ── Codebase trend (snapshot history) ─────────────────────────

@router.get("/api/stats/codebase-trend")
def get_codebase_trend(
    repo: str | None = None,
    branch: str = "main",
    limit: int = 30,
    db: Session = Depends(get_db),
):
    query = (
        db.query(CodebaseSnapshot)
        .order_by(CodebaseSnapshot.timestamp.desc())
    )
    if repo:
        query = query.filter(CodebaseSnapshot.repo_name == repo)
    query = query.filter(CodebaseSnapshot.branch == branch)

    snapshots = query.limit(limit).all()
    snapshots.reverse()  # oldest first for charts

    results = []
    for i, s in enumerate(snapshots):
        delta = {}
        if i > 0:
            prev = snapshots[i - 1]
            delta = {
                "quality_score": round(s.quality_score - prev.quality_score, 2),
                "total_lines": s.total_lines - prev.total_lines,
                "complexity_avg": round(s.complexity_avg - prev.complexity_avg, 2),
            }

        results.append({
            "timestamp": s.timestamp.isoformat() if s.timestamp else None,
            "commit_sha": s.commit_sha[:8] if s.commit_sha else "",
            "total_lines": s.total_lines,
            "total_files": s.total_files,
            "complexity_avg": s.complexity_avg,
            "maintainability_index": s.maintainability_index,
            "quality_score": s.quality_score,
            "delta": delta,
        })

    # Determine overall trend from last 5
    current_trend = "stable"
    trend_summary = "Sin datos suficientes"
    if len(snapshots) >= 2:
        recent_deltas = [
            results[i]["delta"].get("quality_score", 0)
            for i in range(max(0, len(results) - 5), len(results))
            if results[i].get("delta")
        ]
        if recent_deltas:
            avg_delta = sum(recent_deltas) / len(recent_deltas)
            if avg_delta > 0.5:
                current_trend = "improving"
                trend_summary = f"Calidad mejorando +{avg_delta:.1f} puntos promedio por push"
            elif avg_delta < -0.5:
                current_trend = "declining"
                trend_summary = f"Calidad declinando {avg_delta:.1f} puntos promedio por push"
            else:
                trend_summary = "Calidad estable en los ultimos pushes"

    return {
        "snapshots": results,
        "current_trend": current_trend,
        "trend_summary": trend_summary,
    }


# ── Leaderboard ───────────────────────────────────────────────

@router.get("/api/stats/leaderboard")
def get_leaderboard(
    repo: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(
        CommitAnalysis.author,
        func.count(CommitAnalysis.id).label("pushes"),
        func.avg(CommitAnalysis.quality_score).label("avg_score"),
        func.sum(CommitAnalysis.lines_added).label("lines_added"),
        func.sum(CommitAnalysis.lines_deleted).label("lines_deleted"),
    ).group_by(CommitAnalysis.author)

    if repo:
        query = query.filter(CommitAnalysis.repo_name == repo)
    query = _apply_date_filter(query, CommitAnalysis, from_date, to_date)

    results = query.order_by(func.avg(CommitAnalysis.quality_score).desc()).all()

    rankings = []
    for rank, r in enumerate(results, 1):
        if not r.author:
            continue

        badges = []
        avg = r.avg_score or 0
        if avg >= 80:
            badges.append("quality-champion")
        if (r.pushes or 0) >= 10:
            badges.append("consistent-contributor")
        if (r.lines_deleted or 0) > (r.lines_added or 0):
            badges.append("refactor-hero")

        rankings.append({
            "rank": rank,
            "developer": r.author,
            "avg_score": round(avg, 1),
            "pushes": r.pushes or 0,
            "lines_added": r.lines_added or 0,
            "lines_deleted": r.lines_deleted or 0,
            "badges": badges,
        })

    return {"rankings": rankings}
