import os

PATCH_TARGETS = {
    "GITHUB_FETCH": "app.main.fetch_repo_zipball",
    "LLM_CALL": "app.main.summarize_repo_from_packet",
}

def _patch(monkeypatch, dotted_path: str, value):
    module_path, attr = dotted_path.rsplit(".", 1)
    module = __import__(module_path, fromlist=[attr])
    monkeypatch.setattr(module, attr, value)

def test_summarize_success_valid_url(client, monkeypatch):
    def fake_fetch(*args, **kwargs):
        class Fetched:
            def __init__(self):
                self.root_path = "/tmp/fake"
                class TD:
                    def cleanup(self): 
                        return None
                self.temp_dir = TD()
        return Fetched()

    def fake_select_repo_files(root_path):
        return ["README.md"]

    def fake_build_repo_tree_text(root_path):
        return "README.md\n"

    def fake_read_selected_files(root_path, selected):
        return [{"path": "README.md", "content": "# Demo\n"}]

    def fake_build_llm_packet(**kwargs):
        return ({"packet": "x"}, {"meta": "y"})

    def fake_llm(packet):
        return {
            "summary": "Demo project summary.",
            "technologies": ["Python", "FastAPI"],
            "structure": "app/ has API; services/ has integrations.",
        }

    _patch(monkeypatch, PATCH_TARGETS["GITHUB_FETCH"], fake_fetch)
    _patch(monkeypatch, "app.main.select_repo_files", fake_select_repo_files)
    _patch(monkeypatch, "app.main.build_repo_tree_text", fake_build_repo_tree_text)
    _patch(monkeypatch, "app.main.read_selected_files", fake_read_selected_files)
    _patch(monkeypatch, "app.main.build_llm_packet", fake_build_llm_packet)
    _patch(monkeypatch, PATCH_TARGETS["LLM_CALL"], fake_llm)

    resp = client.post("/summarize", json={"github_url": "https://github.com/psf/requests"})
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"summary", "technologies", "structure"}

def test_summarize_invalid_url_rejected(client):
    resp = client.post("/summarize", json={"github_url": "https://example.com/not-github"})
    assert resp.status_code in (400, 422)
    body = resp.json()
    assert body.get("status") == "error"
    assert isinstance(body.get("message"), str)

def test_summarize_missing_field_422(client):
    resp = client.post("/summarize", json={})
    assert resp.status_code == 422
    body = resp.json()
    assert body.get("status") == "error"

def test_summarize_private_repo_maps_to_error(client, monkeypatch):
    from app.main import GitHubFetchError

    def fake_fetch(*args, **kwargs):
        raise GitHubFetchError("Repository is private or forbidden", status_code=403)

    _patch(monkeypatch, PATCH_TARGETS["GITHUB_FETCH"], fake_fetch)

    resp = client.post("/summarize", json={"github_url": "https://github.com/someone/private-repo"})
    assert resp.status_code in (403, 404, 502)
    body = resp.json()
    assert body.get("status") == "error"
    assert isinstance(body.get("message"), str)

def test_summarize_github_rate_limit(client, monkeypatch):
    from app.main import GitHubFetchError

    def fake_fetch(*args, **kwargs):
        raise GitHubFetchError("GitHub rate limit exceeded", status_code=429)

    _patch(monkeypatch, PATCH_TARGETS["GITHUB_FETCH"], fake_fetch)

    resp = client.post("/summarize", json={"github_url": "https://github.com/psf/requests"})
    assert resp.status_code in (429, 502)
    body = resp.json()
    assert body.get("status") == "error"
    assert isinstance(body.get("message"), str)

def test_summarize_llm_failure_returns_error(client, monkeypatch):
    def fake_fetch(*args, **kwargs):
        class Fetched:
            def __init__(self):
                self.root_path = "/tmp/fake"
                class TD:
                    def cleanup(self): 
                        return None
                self.temp_dir = TD()
        return Fetched()

    def fake_select_repo_files(root_path):
        return ["README.md"]

    def fake_build_repo_tree_text(root_path):
        return "README.md\n"

    def fake_read_selected_files(root_path, selected):
        return [{"path": "README.md", "content": "# Demo\n"}]

    def fake_build_llm_packet(**kwargs):
        return ({"packet": "x"}, {"meta": "y"})

    def fake_llm(packet):
        raise TimeoutError("Nebius timed out")

    _patch(monkeypatch, PATCH_TARGETS["GITHUB_FETCH"], fake_fetch)
    _patch(monkeypatch, "app.main.select_repo_files", fake_select_repo_files)
    _patch(monkeypatch, "app.main.build_repo_tree_text", fake_build_repo_tree_text)
    _patch(monkeypatch, "app.main.read_selected_files", fake_read_selected_files)
    _patch(monkeypatch, "app.main.build_llm_packet", fake_build_llm_packet)
    _patch(monkeypatch, PATCH_TARGETS["LLM_CALL"], fake_llm)

    resp = client.post("/summarize", json={"github_url": "https://github.com/psf/requests"})
    assert resp.status_code in (502, 504, 500)
    body = resp.json()
    assert body.get("status") == "error"
    assert isinstance(body.get("message"), str)
