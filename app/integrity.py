"""
Integrity validation subprocess.

Validates:
  - SHA-256 hash consistency of committed files
  - Detects suspicious patterns (secrets, debug leftovers, large binaries)
  - Returns pass/fail status with details
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path


SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|api[_-]?secret)\s*[:=]\s*['\"]?.{8,}", re.MULTILINE),
    re.compile(r"(?i)(password|passwd|pwd)\s*[:=]\s*['\"]?.{4,}", re.MULTILINE),
    re.compile(r"(?i)(aws_access_key_id|aws_secret_access_key)\s*[:=]", re.MULTILINE),
    re.compile(r"(?i)bearer\s+[a-zA-Z0-9\-_.]{20,}", re.MULTILINE),
    re.compile(r"-----BEGIN\s+(RSA|DSA|EC|OPENSSH)?\s*PRIVATE KEY-----", re.MULTILINE),
]

DEBUG_PATTERNS = [
    re.compile(r"\bconsole\.log\b"),
    re.compile(r"\bprint\s*\(.*debug", re.IGNORECASE),
    re.compile(r"\bTODO\b.*\bHACK\b", re.IGNORECASE),
    re.compile(r"\bdebugger\b"),
]

BINARY_EXTENSIONS = {".exe", ".dll", ".so", ".dylib", ".bin", ".zip", ".tar", ".gz"}
MAX_FILE_SIZE_MB = 10


@dataclass
class IntegrityIssue:
    file: str
    issue_type: str  # secret | debug | binary | size
    detail: str
    severity: str  # warning | critical


@dataclass
class IntegrityResult:
    status: str = "pass"  # pass | fail
    content_hash: str = ""
    issues: list[IntegrityIssue] = field(default_factory=list)
    files_scanned: int = 0

    @property
    def has_critical(self) -> bool:
        return any(i.severity == "critical" for i in self.issues)


def compute_tree_hash(directory: str) -> str:
    """SHA-256 hash of all source file contents (sorted by path for determinism)."""
    hasher = hashlib.sha256()
    file_hashes = []

    for root, _, files in sorted(os.walk(directory)):
        if ".git" in Path(root).parts:
            continue
        for fname in sorted(files):
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, "rb") as f:
                    content = f.read()
                file_hash = hashlib.sha256(content).hexdigest()
                rel_path = os.path.relpath(fpath, directory)
                file_hashes.append(f"{rel_path}:{file_hash}")
            except OSError:
                continue

    hasher.update("\n".join(file_hashes).encode())
    return hasher.hexdigest()


def validate_integrity(directory: str) -> IntegrityResult:
    """Run all integrity checks on a directory."""
    result = IntegrityResult()
    result.content_hash = compute_tree_hash(directory)

    for root, _, files in os.walk(directory):
        if any(part.startswith(".") or part in ("node_modules", "__pycache__", "venv")
               for part in Path(root).parts):
            continue

        for fname in files:
            fpath = os.path.join(root, fname)
            rel_path = os.path.relpath(fpath, directory)
            result.files_scanned += 1

            ext = Path(fname).suffix.lower()

            # Check binary files
            if ext in BINARY_EXTENSIONS:
                result.issues.append(IntegrityIssue(
                    file=rel_path,
                    issue_type="binary",
                    detail=f"Binary file detected: {ext}",
                    severity="warning",
                ))
                continue

            # Check file size
            try:
                size_mb = os.path.getsize(fpath) / (1024 * 1024)
                if size_mb > MAX_FILE_SIZE_MB:
                    result.issues.append(IntegrityIssue(
                        file=rel_path,
                        issue_type="size",
                        detail=f"File too large: {size_mb:.1f}MB (limit {MAX_FILE_SIZE_MB}MB)",
                        severity="warning",
                    ))
                    continue
            except OSError:
                continue

            # Scan text content
            try:
                with open(fpath, "r", errors="ignore") as f:
                    content = f.read(500_000)  # cap read to 500KB
            except OSError:
                continue

            # Secret detection
            for pattern in SECRET_PATTERNS:
                if pattern.search(content):
                    result.issues.append(IntegrityIssue(
                        file=rel_path,
                        issue_type="secret",
                        detail=f"Potential secret/credential detected",
                        severity="critical",
                    ))
                    break  # one secret issue per file is enough

            # Debug leftover detection
            for pattern in DEBUG_PATTERNS:
                if pattern.search(content):
                    result.issues.append(IntegrityIssue(
                        file=rel_path,
                        issue_type="debug",
                        detail=f"Debug code detected: {pattern.pattern[:40]}",
                        severity="warning",
                    ))
                    break

    if result.has_critical:
        result.status = "fail"

    return result
