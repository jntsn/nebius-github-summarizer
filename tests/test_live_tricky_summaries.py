import os
import pytest
import httpx

pytestmark = pytest.mark.live

API_URL = os.getenv("LIVE_API_URL", "http://127.0.0.1:8000")

TRICKY_REPOS = [
    # Large-ish, lots of docs and configs
    "https://github.com/affaan-m/everything-claude-code",
    # Mixed languages + proto + app + e2e tests
    "https://github.com/koala73/worldmonitor",
    # Python + TS bridge + Docker
    "https://github.com/HKUDS/nanobot",
]

def _summarize(repo_url: str) -> dict:
    timeout = httpx.Timeout(300.0, connect=20.0)
    with httpx.Client(timeout=timeout) as client:
        r = client.post(f"{API_URL}/summarize", json={"github_url": repo_url})
        data = r.json()
        assert r.status_code == 200, f"Expected 200, got {r.status_code}. Body: {data}"
        return data

@pytest.mark.parametrize("repo_url", TRICKY_REPOS)
def test_live_print_summary(repo_url):
    data = _summarize(repo_url)
    print("\n" + "=" * 100)
    print("REPO:", repo_url)
    print("SUMMARY:\n", data["summary"])
    print("\nTECHNOLOGIES:\n", ", ".join(data["technologies"]))
    print("\nSTRUCTURE:\n", data["structure"])
