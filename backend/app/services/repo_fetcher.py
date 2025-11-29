"""Utilities for downloading repositories and building file manifests."""

from __future__ import annotations
import json
import logging
import re
import shutil
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Tuple
from urllib.parse import urlparse

import requests

from backend.app.core.settings import get_settings

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2] / "data" / "repos"
_MANIFEST_NAME = "manifest.json"

# Known indicators for higher risk configuration or secret-bearing files
_HIGH_RISK_SUFFIXES = {
    ".env",
    ".yaml",
    ".yml",
    ".json",
    ".ini",
    ".cfg",
    ".conf",
    ".tf",
    ".toml",
    ".pem",
    ".key",
    ".ppk",
}
_HIGH_RISK_FILENAMES = {
    "dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
}
_SENSITIVE_KEYWORDS = {
    "secret",
    "credential",
    "token",
    "password",
    "config",
    "deploy",
    "workflow",
    "env",
    "key",
}


class RepoFetchError(RuntimeError):
    """Raised when repository retrieval fails."""


class ManifestNotFoundError(FileNotFoundError):
    """Raised when a manifest cannot be located for a repository."""


def get_repo_directory(repo_id: str) -> Path:
    """Return the path where the repository contents should be stored."""

    return _REPO_ROOT / repo_id


def fetch_and_store_repo(repo_id: str, repo_url: str) -> Dict[str, object]:
    """Download a GitHub repository zipball and build its manifest."""

    owner, name = _parse_github_repo(repo_url)
    settings = get_settings()
    zip_url = f"https://api.github.com/repos/{owner}/{name}/zipball"

    headers = {"Accept": "application/vnd.github+json"}
    if settings.github_token:
        headers["Authorization"] = f"token {settings.github_token}"

    logger.info(
        "Fetching repository zipball",
        extra={"repo_id": repo_id, "repo_url": repo_url, "zip_url": zip_url},
    )

    try:
        response = requests.get(zip_url, headers=headers, timeout=60)
        if response.status_code >= 400:
            raise RepoFetchError(
                f"GitHub responded with {response.status_code}: {response.text[:200]}"
            )
    except requests.RequestException as exc:
        raise RepoFetchError("Failed to download repository zipball") from exc

    repo_dir = get_repo_directory(repo_id)
    repo_dir_parent = repo_dir.parent
    repo_dir_parent.mkdir(parents=True, exist_ok=True)

    if repo_dir.exists():
        shutil.rmtree(repo_dir)

    with tempfile.TemporaryDirectory() as tmp_dir:
        archive_path = Path(tmp_dir) / "repo.zip"
        archive_path.write_bytes(response.content)

        extract_dir = Path(tmp_dir) / "extracted"
        extract_dir.mkdir(parents=True, exist_ok=True)
        shutil.unpack_archive(str(archive_path), extract_dir)

        extracted_root = _locate_extract_root(extract_dir)
        shutil.move(str(extracted_root), str(repo_dir))

    manifest = _build_manifest(repo_id, repo_url, owner, name, repo_dir)
    _write_manifest(repo_dir, manifest)

    logger.info(
        "Repository fetched and manifest written",
        extra={
            "repo_id": repo_id,
            "file_count": manifest.get("file_count"),
            "high_risk_files": manifest.get("high_risk_file_count"),
        },
    )
    return manifest


def _locate_extract_root(extract_dir: Path) -> Path:
    """Find the top-level folder inside the extracted zipball."""

    candidates = [item for item in extract_dir.iterdir() if item.is_dir()]
    if not candidates:
        raise RepoFetchError("Zipball archive did not contain a root directory")
    # GitHub zipballs typically contain a single root directory
    return candidates[0]


def _build_manifest(
    repo_id: str,
    repo_url: str,
    owner: str,
    name: str,
    repo_dir: Path,
) -> Dict[str, object]:
    """Create a manifest describing the files inside the repository."""

    files: List[Dict[str, object]] = []
    for path in repo_dir.rglob('*'):
        if not path.is_file():
            continue

        rel_path = path.relative_to(repo_dir).as_posix()
        size = path.stat().st_size
        risk_level, risk_reasons = _assess_risk(path, rel_path)
        files.append(
            {
                "path": rel_path,
                "size": size,
                "extension": path.suffix.lower(),
                "risk_level": risk_level,
                "risk_reasons": risk_reasons,
            }
        )

    extension_counter = Counter(file.get("extension") for file in files if file.get("extension"))
    top_extensions = [
        {"extension": ext, "count": count}
        for ext, count in extension_counter.most_common(5)
    ]

    manifest: Dict[str, object] = {
        "repo_id": repo_id,
        "repo_url": repo_url,
        "owner": owner,
        "name": name,
        "fetched_at": datetime.utcnow().isoformat() + "Z",
        "file_count": len(files),
        "high_risk_file_count": sum(1 for file in files if file.get("risk_level") == "high"),
        "files": files,
        "top_extensions": top_extensions,
    }

    return manifest


def _write_manifest(repo_dir: Path, manifest: Dict[str, object]) -> None:
    """Persist the manifest as JSON along the repository contents."""

    manifest_path = repo_dir / _MANIFEST_NAME
    with manifest_path.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)


def _assess_risk(path: Path, rel_path: str) -> Tuple[str, List[str]]:
    """Heuristically grade file risk level and provide reasoning tags."""

    reasons: List[str] = []
    suffix = path.suffix.lower()
    name = path.name.lower()
    rel_lower = rel_path.lower()

    if name in _HIGH_RISK_FILENAMES or suffix in _HIGH_RISK_SUFFIXES:
        reasons.append("Sensitive configuration or secret-bearing file")

    if any(keyword in name for keyword in _SENSITIVE_KEYWORDS):
        reasons.append("Filename contains sensitive keyword")

    if ".github/workflows" in rel_lower:
        reasons.append("GitHub Actions workflow may expose CI secrets")

    if "docker" in rel_lower and suffix in {"", ".yml", ".yaml"}:
        reasons.append("Docker artefact impacting container security")

    if rel_lower.endswith("/config.json") or rel_lower.endswith("/config.yaml"):
        reasons.append("Configuration file with potential secrets")

    if reasons:
        return "high", reasons
    if suffix in {".sh", ".ps1", ".bat"}:
        return "medium", ["Executable script"]
    return "low", []


def _parse_github_repo(repo_url: str) -> Tuple[str, str]:
    """Extract owner and repository name from a GitHub URL."""

    parsed = urlparse(repo_url)
    if parsed.netloc.lower() not in {"github.com", "www.github.com"}:
        raise RepoFetchError("Only GitHub repositories are supported right now")

    parts = [segment for segment in parsed.path.strip('/').split('/') if segment]
    if len(parts) < 2:
        raise RepoFetchError("Unable to determine owner/repo from URL")

    owner = parts[0]
    name = re.sub(r"\.git$", "", parts[1])
    return owner, name


def load_repo_manifest(repo_id: str) -> Dict[str, object]:
    """Load the manifest for a repository from disk."""

    manifest_path = get_repo_directory(repo_id) / _MANIFEST_NAME
    if not manifest_path.exists():
        raise ManifestNotFoundError(f"Manifest not found for repo '{repo_id}'")

    with manifest_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def select_high_risk_files(manifest: Dict[str, object], limit: int = 10) -> List[Dict[str, object]]:
    """Return up to ``limit`` high-risk file entries from the manifest."""

    files: Iterable[Dict[str, object]] = manifest.get("files", [])
    high_risk = [file for file in files if file.get("risk_level") == "high"]

    high_risk.sort(
        key=lambda file: (
            -len(file.get("risk_reasons", [])),
            -file.get("size", 0),
            file.get("path", ""),
        )
    )

    if high_risk:
        return high_risk[:limit]

    # Fallback: choose the largest files if nothing was marked explicitly high risk
    sorted_files = sorted(files, key=lambda file: file.get("size", 0), reverse=True)
    return sorted_files[:limit]


def list_all_paths(manifest: Dict[str, object]) -> List[str]:
    """Return all file paths from the manifest."""

    return [file.get("path") for file in manifest.get("files", []) if file.get("path")]
