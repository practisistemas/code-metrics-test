"""
Local test script for Code Metrics.

Tests the full pipeline without Docker:
  1. Starts FastAPI server locally
  2. Sends a test push payload (using a real repo)
  3. Checks results, downloads .md report
  4. Opens dashboard in browser

Usage:
  cd code-metrics
  source .venv/bin/activate
  python test_local.py
"""

import json
import os
import subprocess
import sys
import time
import webbrowser

# Set SQLite path to local data dir BEFORE importing app modules
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{PROJECT_DIR}/data/metrics.db")

# Load .env if exists
env_path = os.path.join(PROJECT_DIR, ".env")
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ.setdefault(key, val)

import httpx

BASE_URL = "http://localhost:8080"

# Use authenticated user's repo
TEST_REPO = "practisistemas/code-metrics-test"
TEST_REPO_URL = f"https://github.com/{TEST_REPO}.git"


def wait_for_server(timeout=15):
    """Wait for the FastAPI server to be ready."""
    print("Waiting for server...")
    for _ in range(timeout):
        try:
            r = httpx.get(f"{BASE_URL}/health", timeout=2)
            if r.status_code == 200:
                print(f"  Server ready: {r.json()}")
                return True
        except httpx.ConnectError:
            pass
        time.sleep(1)
    print("  ERROR: Server did not start in time")
    return False


def test_analyze():
    """Send a test push payload to the analyze endpoint."""
    payload = {
        "repo_name": TEST_REPO,
        "repo_url": TEST_REPO_URL,
        "branch": "main",
        "head_sha": "e8d8f52",
        "pusher": "practisistemas",
        "commits": [
            {
                "sha": "e8d8f52",
                "message": "ci: add GitHub Actions workflow for code analysis",
                "author": "practisistemas",
                "added": [".github/workflows/code-analysis.yml"],
                "modified": [],
                "removed": [],
            }
        ],
    }

    print(f"\nAnalyzing: {payload['repo_name']}")
    print(f"  Repo URL: {payload['repo_url']}")
    print("  This may take 30-60s (clone + Claude review)...\n")

    try:
        r = httpx.post(f"{BASE_URL}/api/analyze", json=payload, timeout=180)
        print(f"  HTTP Status: {r.status_code}")

        if r.status_code == 200:
            data = r.json()
            print(f"\n  === RESULTS ===")
            print(f"  Quality Score:  {data['quality_score']}/100")
            print(f"  Integrity:      {data['integrity']}")
            print(f"  Deprecations:   {data.get('deprecations_found', 0)}")
            print(f"  Report URL:     {BASE_URL}{data['report_url']}")

            metrics = data.get("metrics", {})
            print(f"\n  --- Metrics ---")
            print(f"  Total Lines:    {metrics.get('total_lines', 0):,}")
            print(f"  Lines Added:    +{metrics.get('lines_added', 0)}")
            print(f"  Lines Deleted:  -{metrics.get('lines_deleted', 0)}")
            print(f"  Files Changed:  {metrics.get('files_changed', 0)}")
            print(f"  Complexity Avg: {metrics.get('complexity_avg', 0)}")
            print(f"  Maintainability:{metrics.get('maintainability_index', 0)}")

            if "claude_review" in data:
                review = data["claude_review"]
                print(f"\n  --- Claude AI Review ---")
                summary = review.get("summary", "N/A")
                print(f"  Summary: {summary[:300]}")
                if review.get("suggestions"):
                    print(f"  Suggestions:")
                    for s in review["suggestions"][:5]:
                        print(f"    - {s[:100]}")

            # Download report
            report_r = httpx.get(f"{BASE_URL}{data['report_url']}", timeout=10)
            if report_r.status_code == 200:
                report_path = os.path.join(PROJECT_DIR, "test-report.md")
                with open(report_path, "w") as f:
                    f.write(report_r.text)
                print(f"\n  Report saved: {report_path}")

            return data
        else:
            print(f"  ERROR: {r.text[:500]}")
            return None
    except httpx.ReadTimeout:
        print("  TIMEOUT: Analysis took too long (>180s)")
        return None


def test_results():
    """Check stored results."""
    r = httpx.get(f"{BASE_URL}/api/results", timeout=10)
    if r.status_code == 200:
        results = r.json()
        print(f"\n  Stored analyses: {len(results)}")
        for res in results[:5]:
            print(f"    [{res['sha']}] Score: {res['quality_score']} | Integrity: {res['integrity']} | Claude: {'Yes' if res.get('has_claude_review') else 'No'}")


def main():
    print("=" * 60)
    print("  CODE METRICS - Local Test")
    print("=" * 60)

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    print(f"  API key: {'...' + api_key[-8:] if api_key else 'NOT SET'}")
    print(f"  DB: {os.environ.get('DATABASE_URL', 'default')}")

    # Init database
    print("\nInitializing database...")
    sys.path.insert(0, PROJECT_DIR)
    from app.database import init_db
    init_db()
    print("  Database ready")

    # Start server
    print("\nStarting server...")
    server_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"],
        cwd=PROJECT_DIR,
        env={**os.environ},
    )

    try:
        if not wait_for_server():
            server_proc.terminate()
            return

        test_analyze()
        test_results()

        print(f"\n  Dashboard: {BASE_URL}/")
        webbrowser.open(BASE_URL)

        print("\n" + "=" * 60)
        print("  Server running. Press Ctrl+C to stop.")
        print("=" * 60)
        server_proc.wait()

    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        server_proc.terminate()
        server_proc.wait()
        print("Done.")


if __name__ == "__main__":
    main()
