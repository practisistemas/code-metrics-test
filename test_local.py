"""
Local test script for Code Metrics.

Tests the full pipeline without Docker:
  1. Starts FastAPI server locally
  2. Sends a test push payload (using a real repo)
  3. Checks results, downloads .md report
  4. Opens dashboard in browser

Usage:
  cd code-metrics
  pip install -r requirements.txt
  python test_local.py
"""

import json
import os
import subprocess
import sys
import time
import webbrowser

import httpx

# Load .env if exists
env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ[key] = val

BASE_URL = "http://localhost:8080"

# Use the authenticated user's repo or a public test repo
TEST_REPO = os.getenv("TEST_REPO", "practisistemas/code-metrics-test")
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


def test_analyze(repo_name=None, repo_url=None):
    """Send a test push payload to the analyze endpoint."""
    payload = {
        "repo_name": repo_name or TEST_REPO,
        "repo_url": repo_url or TEST_REPO_URL,
        "branch": "main",
        "head_sha": "abc1234567890abcdef1234567890abcdef123456",
        "pusher": "test-user",
        "commits": [
            {
                "sha": "abc1234567890abcdef1234567890abcdef123456",
                "message": "test: initial commit for metrics testing",
                "author": "test-user",
                "added": ["README.md"],
                "modified": [],
                "removed": [],
            }
        ],
    }

    print(f"\nSending analysis request for: {payload['repo_name']}")
    print(f"  Repo URL: {payload['repo_url']}")
    print("  This may take 30-60 seconds (cloning + Claude review)...")

    try:
        r = httpx.post(f"{BASE_URL}/api/analyze", json=payload, timeout=120)
        print(f"\n  Status: {r.status_code}")

        if r.status_code == 200:
            data = r.json()
            print(f"  Quality Score: {data['quality_score']}/100")
            print(f"  Integrity: {data['integrity']}")
            print(f"  Deprecations: {data.get('deprecations_found', 0)}")
            print(f"  Report URL: {BASE_URL}{data['report_url']}")

            if "claude_review" in data:
                review = data["claude_review"]
                print(f"\n  Claude Opinion: {review.get('opinion', 'N/A')[:200]}...")
                print(f"  Claude Summary: {review.get('summary', 'N/A')}")

            # Download the .md report
            report_r = httpx.get(f"{BASE_URL}{data['report_url']}", timeout=10)
            if report_r.status_code == 200:
                report_path = os.path.join(os.path.dirname(__file__), "test-report.md")
                with open(report_path, "w") as f:
                    f.write(report_r.text)
                print(f"\n  Report saved to: {report_path}")

            return data
        else:
            print(f"  ERROR: {r.text}")
            return None
    except httpx.ReadTimeout:
        print("  TIMEOUT: Analysis took too long")
        return None


def test_results():
    """Check stored results."""
    r = httpx.get(f"{BASE_URL}/api/results", timeout=10)
    print(f"\nStored results: {r.status_code}")
    if r.status_code == 200:
        results = r.json()
        print(f"  Total analyses: {len(results)}")
        for res in results[:5]:
            print(f"  - [{res['sha']}] Score: {res['quality_score']} | Integrity: {res['integrity']}")
    return r.json() if r.status_code == 200 else []


def main():
    print("=" * 60)
    print("  CODE METRICS - Local Test")
    print("=" * 60)

    # Check API key
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if api_key:
        print(f"  Anthropic API key: ...{api_key[-8:]}")
    else:
        print("  WARNING: No ANTHROPIC_API_KEY set. Claude review will be skipped.")

    # Create /data directory for SQLite
    os.makedirs("/data", exist_ok=True)

    # Initialize database
    print("\nInitializing database...")
    from app.database import init_db
    init_db()
    print("  Database ready")

    # Start server in background
    print("\nStarting FastAPI server...")
    server_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"],
        cwd=os.path.dirname(__file__),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        if not wait_for_server():
            print("Server failed to start. Check logs.")
            server_proc.terminate()
            return

        # Run tests
        result = test_analyze()
        test_results()

        # Open dashboard
        print(f"\nDashboard: {BASE_URL}/")
        print("Opening in browser...")
        webbrowser.open(BASE_URL)

        print("\n" + "=" * 60)
        print("  Press Ctrl+C to stop the server")
        print("=" * 60)

        # Keep running
        server_proc.wait()

    except KeyboardInterrupt:
        print("\nStopping server...")
    finally:
        server_proc.terminate()
        server_proc.wait()
        print("Done.")


if __name__ == "__main__":
    main()
