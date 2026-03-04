import pytest

from app.services.github_fetch import GitHubFetchError
from app.services.nebius_llm import NebiusLLMError


def _patch(monkeypatch, dotted_path: str, value):
    module_path, attr = dotted_path.rsplit(".", 1)
    module = __import__(module_path, fromlist=[attr])
    monkeypatch.setattr(module, attr, value)


def _fake_fetched_repo():
    class TD:
        def cleanup(self):
            return None

    class Fetched:
        root_path = "/tmp/fake_repo"
        temp_dir = TD()

    return Fetched()


def test_get_summarize_returns_405(client):
    r = client.get("/summarize")
    assert r.status_code == 405


def test_post_text_plain_body_is_rejected(client):
    r = client.post("/summarize", data="not json", headers={"Content-Type": "text/plain"})
    assert r.status_code in (415, 422)


def test_post_malformed_json_is_rejected(client):
    r = client.post("/summarize", data="{", headers={"Content-Type": "application/json"})
    assert r.status_code == 422


def test_github_fetch_error_maps_to_status_and_error_shape(client, monkeypatch):
    def fake_fetch(*args, **kwargs):
        raise GitHubFetchError("Repository not found (404).", status_code=404)

    _patch(monkeypatch, "app.main.fetch_repo_zipball", fake_fetch)

    r = client.post("/summarize", json={"github_url": "https://github.com/nope/nope"})
    assert r.status_code == 404

    body = r.json()
    assert body.get("status") == "error"
    assert isinstance(body.get("message"), str) and body["message"]


def test_llm_error_maps_to_status_and_error_shape(client, monkeypatch):
    def fake_fetch(*args, **kwargs):
        return _fake_fetched_repo()

    def fake_select_repo_files(root_path):
        return ["README.md"]

    def fake_build_repo_tree_text(root_path):
        return "README.md\n"

    def fake_read_selected_files(root_path, selected):
        return [{"path": "README.md", "content": "# Demo\n"}]

    def fake_build_llm_packet(**kwargs):
        return ({"messages": []}, {"debug": "x"})

    def fake_summarize_repo_from_packet(packet):
        raise NebiusLLMError("LLM timed out", status_code=503)

    _patch(monkeypatch, "app.main.fetch_repo_zipball", fake_fetch)
    _patch(monkeypatch, "app.main.select_repo_files", fake_select_repo_files)
    _patch(monkeypatch, "app.main.build_repo_tree_text", fake_build_repo_tree_text)
    _patch(monkeypatch, "app.main.read_selected_files", fake_read_selected_files)
    _patch(monkeypatch, "app.main.build_llm_packet", fake_build_llm_packet)
    _patch(monkeypatch, "app.main.summarize_repo_from_packet", fake_summarize_repo_from_packet)

    r = client.post("/summarize", json={"github_url": "https://github.com/psf/requests"})
    assert r.status_code == 503

    body = r.json()
    assert body.get("status") == "error"
    assert isinstance(body.get("message"), str) and body["message"]
