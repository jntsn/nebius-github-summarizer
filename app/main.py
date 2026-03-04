from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from pydantic import BaseModel, ConfigDict
from typing import List, Literal

import logging

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