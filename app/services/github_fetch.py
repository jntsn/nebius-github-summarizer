from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import tempfile
import zipfile

import httpx

from app.utils.github_url import GitHubRepoRef


class GitHubFetchError(RuntimeError):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class FetchedRepo:
    repo: GitHubRepoRef
    temp_dir: tempfile.TemporaryDirectory
    root_path: Path


def _headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "nebius-repo-summarizer",
    }

    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    return headers


def _check_rate_limit(resp: httpx.Response) -> None:
    if resp.status_code == 403 and resp.headers.get("X-RateLimit-Remaining") == "0":
        reset = resp.headers.get("X-RateLimit-Reset")
        msg = "GitHub rate limit exceeded"
        if reset:
            msg += f" (reset epoch seconds: {reset})"
        raise GitHubFetchError(msg, status_code=429)


def _download_to_zip(
    client: httpx.Client,
    url: str,
    zip_path: Path,
    *,
    max_zip_bytes: int,
    headers: dict[str, str] | None = None,
) -> None:
    downloaded = 0
    with client.stream("GET", url, headers=headers, follow_redirects=True) as r:
        if headers is not None and "api.github.com" in url:
            _check_rate_limit(r)

        if r.status_code == 404:
            raise GitHubFetchError("Repository not found (404).", status_code=404)
        if r.status_code == 403:
            raise GitHubFetchError("Access forbidden (403). Repo may be private.", status_code=403)
        if r.status_code >= 400:
            raise GitHubFetchError(f"Download failed: {r.status_code}", status_code=502)

        with open(zip_path, "wb") as f:
            for chunk in r.iter_bytes(chunk_size=65536):
                if not chunk:
                    continue
                downloaded += len(chunk)
                if downloaded > max_zip_bytes:
                    raise GitHubFetchError(
                        f"Repository archive too large (>{max_zip_bytes} bytes).",
                        status_code=413,
                    )
                f.write(chunk)


def _extract_zip(zip_path: Path, extract_dir: Path) -> Path:
    extract_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(extract_dir)

    dirs = [p for p in extract_dir.iterdir() if p.is_dir()]
    root = dirs[0] if len(dirs) == 1 else extract_dir
    return root


def fetch_repo_zipball(
    repo: GitHubRepoRef,
    *,
    timeout_seconds: float = 30.0,
    max_zip_bytes: int = int(os.getenv("MAX_REPO_ZIP_MB", "150")) * 1024 * 1024,
) -> FetchedRepo:
    """
    Token optional behavior:
    - First try direct public archive downloads from github.com (no API key, no API rate limit).
    - If that fails, fall back to GitHub API zipball (better errors, supports private repos if token provided).
    """
    timeout = httpx.Timeout(timeout_seconds)
    tmp: tempfile.TemporaryDirectory | None = None

    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            tmp = tempfile.TemporaryDirectory(prefix="repo_")
            tmp_path = Path(tmp.name)
            zip_path = tmp_path / "repo.zip"
            extract_dir = tmp_path / "extracted"

            # 1) Try public archive URLs without GitHub API
            public_candidates = [
                f"https://github.com/{repo.owner}/{repo.repo}/archive/refs/heads/main.zip",
                f"https://github.com/{repo.owner}/{repo.repo}/archive/refs/heads/master.zip",
            ]

            last_public_error: GitHubFetchError | None = None
            for url in public_candidates:
                try:
                    _download_to_zip(
                        client,
                        url,
                        zip_path,
                        max_zip_bytes=max_zip_bytes,
                        headers={"User-Agent": "nebius-repo-summarizer"},
                    )
                    root = _extract_zip(zip_path, extract_dir)
                    return FetchedRepo(repo=repo, temp_dir=tmp, root_path=root)
                except GitHubFetchError as e:
                    last_public_error = e
                    # if forbidden, it might be private
                    if e.status_code == 403:
                        break
                    continue

            # 2) If a token exists, or public download did not succeed, use GitHub API for better diagnostics
            api_base = "https://api.github.com"
            repo_api_url = f"{api_base}/repos/{repo.owner}/{repo.repo}"
            zip_url = f"{repo_api_url}/zipball"

            meta = client.get(repo_api_url, headers=_headers())
            _check_rate_limit(meta)

            if meta.status_code == 404:
                raise GitHubFetchError(
                    "Repository not found (404). Check owner/repo and that it is public.",
                    status_code=404,
                )
            if meta.status_code == 403:
                # This might be private or rate limit without token
                raise GitHubFetchError(
                    "Access forbidden (403). Repo may be private. If public, you may be rate-limited. "
                    "Optional fix: set GITHUB_TOKEN for higher rate limits.",
                    status_code=403,
                )
            if meta.status_code >= 400:
                raise GitHubFetchError(f"GitHub API error: {meta.status_code}", status_code=502)

            _download_to_zip(
                client,
                zip_url,
                zip_path,
                max_zip_bytes=max_zip_bytes,
                headers=_headers(),
            )
            root = _extract_zip(zip_path, extract_dir)
            return FetchedRepo(repo=repo, temp_dir=tmp, root_path=root)

    except httpx.TimeoutException:
        raise GitHubFetchError("GitHub request timed out", status_code=504)
    except httpx.RequestError as e:
        raise GitHubFetchError(f"Network error while contacting GitHub: {e}", status_code=502)
    except zipfile.BadZipFile:
        raise GitHubFetchError("Downloaded archive is not a valid zip file", status_code=502)
    except Exception:
        if tmp is not None:
            tmp.cleanup()
        raise