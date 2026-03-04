from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
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
    return {
        "Accept": "application/vnd.github+json",
        "User-Agent": "nebius-repo-summarizer",
    }


def _check_rate_limit(resp: httpx.Response) -> None:
    if resp.status_code == 403 and resp.headers.get("X-RateLimit-Remaining") == "0":
        reset = resp.headers.get("X-RateLimit-Reset")
        msg = "GitHub rate limit exceeded"
        if reset:
            msg += f" (reset epoch seconds: {reset})"
        raise GitHubFetchError(msg, status_code=429)


def fetch_repo_zipball(
    repo: GitHubRepoRef,
    *,
    timeout_seconds: float = 30.0,
    max_zip_bytes: int = 25 * 1024 * 1024,
) -> FetchedRepo:
    api_base = "https://api.github.com"
    repo_api_url = f"{api_base}/repos/{repo.owner}/{repo.repo}"
    zip_url = f"{repo_api_url}/zipball"

    timeout = httpx.Timeout(timeout_seconds)

    tmp: tempfile.TemporaryDirectory | None = None
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            meta = client.get(repo_api_url, headers=_headers())
            _check_rate_limit(meta)

            if meta.status_code == 404:
                raise GitHubFetchError(
                    "Repository not found (404). Check the owner/repo and that it is public.",
                    status_code=502,
                )
            if meta.status_code == 403:
                raise GitHubFetchError(
                    "Access forbidden (403). Repo may be private or you may be rate-limited.",
                    status_code=502,
                )
            if meta.status_code >= 400:
                raise GitHubFetchError(f"GitHub API error: {meta.status_code}", status_code=502)

            tmp = tempfile.TemporaryDirectory(prefix="repo_")
            tmp_path = Path(tmp.name)
            zip_path = tmp_path / "repo.zip"

            downloaded = 0
            with client.stream("GET", zip_url, headers=_headers()) as r:
                _check_rate_limit(r)
                if r.status_code >= 400:
                    raise GitHubFetchError(f"Zipball download failed: {r.status_code}", status_code=502)

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

            extract_dir = tmp_path / "extracted"
            extract_dir.mkdir(parents=True, exist_ok=True)

            with zipfile.ZipFile(zip_path, "r") as z:
                z.extractall(extract_dir)

            dirs = [p for p in extract_dir.iterdir() if p.is_dir()]
            root = dirs[0] if len(dirs) == 1 else extract_dir

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