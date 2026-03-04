from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class GitHubRepoRef:
    owner: str
    repo: str

    @property
    def canonical_url(self) -> str:
        return f"https://github.com/{self.owner}/{self.repo}"


def _strip_dot_git(name: str) -> str:
    return name[:-4] if name.lower().endswith(".git") else name


def parse_github_repo_url(raw_url: str) -> GitHubRepoRef:
    """
    Accept only repository-root URLs like:
      https://github.com/OWNER/REPO
      https://github.com/OWNER/REPO/
      https://github.com/OWNER/REPO.git

    Reject:
      - non-https
      - non-github.com
      - missing owner/repo
      - extra path segments like /tree/main or /blob/...
      - query/fragment
    """
    if not raw_url or not raw_url.strip():
        raise ValueError("github_url is required")

    raw_url = raw_url.strip()
    parsed = urlparse(raw_url)

    if parsed.scheme != "https":
        raise ValueError("Only https GitHub URLs are supported")

    host = (parsed.netloc or "").lower()
    if host not in {"github.com", "www.github.com"}:
        raise ValueError("URL must be a github.com repository link")

    if parsed.query or parsed.fragment:
        raise ValueError("URL must not include query parameters or fragments")

    parts = [p for p in (parsed.path or "").split("/") if p]

    if len(parts) < 2:
        raise ValueError("URL must be in the form https://github.com/{owner}/{repo}")

    if len(parts) > 2:
        raise ValueError("URL must point to the repository root, not a subpath")

    owner = parts[0].strip()
    repo = _strip_dot_git(parts[1].strip())

    if not owner or not repo:
        raise ValueError("URL must include both owner and repo")

    forbidden = {".", ".."}
    if owner in forbidden or repo in forbidden:
        raise ValueError("Invalid owner or repo in URL")

    return GitHubRepoRef(owner=owner, repo=repo)
