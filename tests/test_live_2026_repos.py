import os
import pytest
import httpx

# Run these only when explicitly requested:
#   pytest -q -m live
pytestmark = pytest.mark.live

API_URL = os.getenv("LIVE_API_URL", "http://127.0.0.1:8000")


REPOS_CREATED_2026 = [
    # These are niche repos returned by GitHub search for:
    # created:2026-01-01..2026-12-31 stars:>50
    # (so they satisfy "created in 2026") and are public.
    "https://github.com/affaan-m/everything-claude-code",
    "https://github.com/koala73/worldmonitor",
    "https://github.com/HKUDS/nanobot",
]


def _post_summarize(github_url: str) -> dict:
    timeout = httpx.Timeout(300.0, connect=20.0)
    with httpx.Client(timeout=timeout) as client:
        r = client.post(f"{API_URL}/summarize", json={"github_url": github_url})
        data = r.json()
        assert r.status_code == 200, f"Expected 200, got {r.status_code}. Body: {data}"
        assert set(data.keys()) == {"summary", "technologies", "structure"}
        assert isinstance(data["summary"], str) and data["summary"].strip()
        assert isinstance(data["technologies"], list)
        assert isinstance(data["structure"], str)
        return data


@pytest.mark.parametrize("repo_url", REPOS_CREATED_2026)
def test_live_summarize_repo_created_2026(repo_url, capsys):
    data = _post_summarize(repo_url)

    # Print outputs so you can see model summaries in terminal.
    # Run with: pytest -q -m live -s
    print("\n" + "=" * 100)
    print("REPO:", repo_url)
    print("-" * 100)
    print("SUMMARY:\n", data["summary"])
    print("\nTECHNOLOGIES:\n", ", ".join(data["technologies"]))
    print("\nSTRUCTURE:\n", data["structure"])
