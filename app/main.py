from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from pydantic import BaseModel, ConfigDict
from typing import List, Literal

import logging
import os

from app.services.nebius_llm import (
    NebiusLLMError,
    NebiusLLMResponseError,
    summarize_repo_from_packet,
    chat_complete,
)
from app.utils.github_url import parse_github_repo_url
from app.services.github_fetch import GitHubFetchError, fetch_repo_zipball
from app.services.file_selection import select_repo_files
from app.services.llm_packet import build_llm_packet
from app.services.repo_snapshot import build_repo_tree_text, read_selected_files

import re

def _estimate_tokens(text: str) -> int:
    # Rough heuristic: 1 token ~ 4 chars for English/code mix
    return max(1, len(text) // 4)

def _priority_for_path(path: str) -> int:
    p = path.lower()

    # Highest: README and top-level docs
    if re.search(r"(^|/)(readme|readme\.md|readme\.rst)$", p):
        return 1000
    if re.search(r"(^|/)(docs?/|contributing|changelog|license)", p):
        return 900

    # High: project metadata / configs
    if re.search(r"(^|/)(pyproject\.toml|setup\.py|requirements\.txt|poetry\.lock|pipfile|package\.json|pnpm-lock\.yaml|yarn\.lock|go\.mod|cargo\.toml|composer\.json)$", p):
        return 800
    if re.search(r"(^|/)(dockerfile|docker-compose\.ya?ml|compose\.ya?ml|makefile|justfile|\.env\.example|\.editorconfig)$", p):
        return 750
    if re.search(r"(^|/)(\.github/workflows/|\.gitlab-ci\.yml)", p):
        return 700

    # Medium: actual source code
    if re.search(r"\.(py|js|ts|go|rs|java|kt|cpp|c|h|cs|rb|php)$", p):
        return 500

    # Low
    return 100

def _shrink_for_llm(repo_tree_text: str, selected_files_payload: list[dict]) -> tuple[str, list[dict], dict]:
    """
    Returns (tree_text, files_payload, meta) such that input stays within LLM budget.
    """

    max_input_tokens = int(os.getenv("MAX_LLM_INPUT_TOKENS", "32000"))
    max_tree_chars = int(os.getenv("MAX_TREE_CHARS", "20000"))
    max_file_chars_default = int(os.getenv("MAX_FILE_CHARS", "4000"))
    max_readme_chars = int(os.getenv("MAX_README_CHARS", "12000"))
    max_total_files_chars = int(os.getenv("MAX_TOTAL_FILES_CHARS", "140000"))
    max_files = int(os.getenv("MAX_FILES", "35"))

    # 1) Trim tree first
    tree = repo_tree_text[:max_tree_chars]

    # 2) Sort files by priority (README, configs, then code)
    files = []
    for f in selected_files_payload:
        path = f.get("path", "")
        content = f.get("content", "")
        files.append({"path": path, "content": content, "_prio": _priority_for_path(path)})

    files.sort(key=lambda x: x["_prio"], reverse=True)

    # 3) Truncate per file and enforce total budget
    kept = []
    total_chars = 0
    omitted = []

    for f in files[:max_files]:
        path = f["path"]
        content = f["content"] or ""

        per_file_cap = max_readme_chars if "readme" in path.lower() else max_file_chars_default
        content_truncated = content[:per_file_cap]

        if total_chars + len(content_truncated) > max_total_files_chars:
            omitted.append(path)
            continue

        kept.append({"path": path, "content": content_truncated})
        total_chars += len(content_truncated)

    # 4) Final token check: if still too big, drop lowest priority files until OK
    def build_preview_text(tree_text: str, files_payload: list[dict]) -> str:
        parts = ["REPO TREE:\n", tree_text, "\n\nFILES:\n"]
        for f in files_payload:
            parts.append(f"\n--- {f['path']} ---\n")
            parts.append(f["content"])
        return "".join(parts)

    preview = build_preview_text(tree, kept)
    while _estimate_tokens(preview) > max_input_tokens and len(kept) > 1:
        # drop last (lowest priority among kept)
        dropped = kept.pop()
        omitted.append(dropped["path"])
        preview = build_preview_text(tree, kept)

    meta = {
        "max_input_tokens": max_input_tokens,
        "estimated_input_tokens": _estimate_tokens(preview),
        "kept_files": len(kept),
        "omitted_files": len(omitted),
        "omitted_paths_sample": omitted[:20],
    }
    return tree, kept, meta



app = FastAPI()

logger = logging.getLogger("app")

class SummarizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    github_url: str


class SummarizeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str
    technologies: List[str]
    structure: str


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["error"] = "error"
    message: str

class AppError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message

@app.exception_handler(AppError)
def handle_app_error(_, exc: AppError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"status": "error", "message": exc.message},
    )


@app.exception_handler(RequestValidationError)
def handle_validation_error(_, exc: RequestValidationError):
    # You can make this more detailed if you want, but keep the same shape.
    return JSONResponse(
        status_code=422,
        content={"status": "error", "message": "Invalid request body"},
    )


@app.exception_handler(StarletteHTTPException)
def handle_http_exception(_, exc: StarletteHTTPException):
    # Ensure *any* raised HTTPException also matches your error JSON format
    detail = exc.detail if isinstance(exc.detail, str) else "Request failed"
    return JSONResponse(
        status_code=exc.status_code,
        content={"status": "error", "message": detail},
    )


@app.exception_handler(Exception)
def handle_unexpected_error(_, exc: Exception):
    logger.exception("Unhandled exception")
    return JSONResponse(
        status_code=500,
        content={"status": "error", "message": "Internal server error"},
    )

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/health/llm")
def llm_health():
    try:
        text = chat_complete("Reply with exactly: ok")
        return {"status": "ok", "llm_reply": text}
    except NebiusLLMError as e:
        logger.exception("LLM health check failed")
        raise AppError(getattr(e, "status_code", 500), str(e))

@app.post(
    "/summarize",
    response_model=SummarizeResponse,
    responses={
        400: {"model": ErrorResponse},
        413: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
        504: {"model": ErrorResponse},
    },
)
def summarize(payload: SummarizeRequest):
    try:
        repo_ref = parse_github_repo_url(payload.github_url)
    except ValueError as e:
        raise AppError(400, str(e))

    fetched = None
    try:
        fetched = fetch_repo_zipball(repo_ref)
        selected = select_repo_files(fetched.root_path)
        tree_text = build_repo_tree_text(fetched.root_path)
        selected_files_payload = read_selected_files(fetched.root_path, selected)

        tree_text, selected_files_payload, shrink_meta = _shrink_for_llm(tree_text, selected_files_payload)
        logger.info(f"LLM input shrink meta: {shrink_meta}")

        packet, packet_meta = build_llm_packet(
            github_url=repo_ref.canonical_url,
            repo_tree_text=tree_text,
            selected_files=selected_files_payload,
        )
    except GitHubFetchError as e:
        raise AppError(getattr(e, "status_code", 502), str(e))
    except Exception as e:
        raise AppError(500, f"Unexpected error while fetching repo: {e}")
    finally:
        if fetched is not None:
            fetched.temp_dir.cleanup()

    try:
        result = summarize_repo_from_packet(packet)
    except NebiusLLMResponseError as e:
        logger.exception("LLM returned invalid response")
        raise AppError(getattr(e, "status_code", 502), str(e))
    except NebiusLLMError as e:
        logger.exception("LLM call failed")
        raise AppError(getattr(e, "status_code", 502), str(e))
    except Exception as e:
        logger.exception("Unexpected LLM error")
        raise AppError(502, f"Unexpected LLM error: {e}")

    return SummarizeResponse(
        summary=result["summary"],
        technologies=result["technologies"],
        structure=result["structure"],
    )