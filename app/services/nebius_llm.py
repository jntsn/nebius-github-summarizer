import json
import re
from typing import Any, Dict, List

from openai import OpenAI
from openai import (
    APIConnectionError,
    APITimeoutError,
    APIError,
    RateLimitError,
    AuthenticationError,
    BadRequestError,
)

from app.core.config import settings


class NebiusLLMError(RuntimeError):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


class NebiusLLMResponseError(NebiusLLMError):
    pass


def get_nebius_client() -> OpenAI:
    if not settings.nebius_api_key:
        raise NebiusLLMError("NEBIUS_API_KEY is not set", status_code=500)
    return OpenAI(
        api_key=settings.nebius_api_key,
        base_url=settings.nebius_base_url,
    )


def chat_complete(prompt: str) -> str:
    client = get_nebius_client()

    try:
        resp = client.chat.completions.create(
            model=settings.nebius_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )
    except APITimeoutError:
        raise NebiusLLMError("LLM request timed out", status_code=504)
    except RateLimitError:
        raise NebiusLLMError("LLM rate limit exceeded", status_code=429)
    except AuthenticationError:
        raise NebiusLLMError("LLM authentication failed (check NEBIUS_API_KEY)", status_code=500)
    except BadRequestError as e:
        raise NebiusLLMError(f"LLM request rejected: {e}", status_code=502)
    except APIConnectionError as e:
        raise NebiusLLMError(f"Network error contacting LLM: {e}", status_code=502)
    except APIError as e:
        raise NebiusLLMError(f"LLM upstream error: {e}", status_code=502)
    except Exception as e:
        raise NebiusLLMError(f"LLM request failed: {e}", status_code=502)

    return resp.choices[0].message.content or ""


def _extract_json_object(text: str) -> Dict[str, Any]:
    """
    Tries hard to extract a single JSON object from an LLM response.
    Handles:
    - raw JSON
    - ```json ... ```
    - extra commentary (we still try to find the first {...})
    """
    if not text or not text.strip():
        raise NebiusLLMResponseError("LLM returned empty response")

    s = text.strip()

    # Strip fenced blocks if present
    fence_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", s, flags=re.DOTALL | re.IGNORECASE)
    if fence_match:
        s = fence_match.group(1).strip()

    # If still not pure JSON, try to locate first {...}
    if not s.startswith("{"):
        obj_match = re.search(r"(\{.*\})", s, flags=re.DOTALL)
        if obj_match:
            s = obj_match.group(1).strip()

    try:
        data = json.loads(s)
    except json.JSONDecodeError as e:
        raise NebiusLLMResponseError(f"Failed to parse LLM JSON: {e}")

    if not isinstance(data, dict):
        raise NebiusLLMResponseError("LLM JSON is not an object")

    return data


def summarize_repo_from_packet(packet: str) -> Dict[str, Any]:
    """
    Takes your stage-8 packet string, calls Nebius, and returns a validated dict:
      {"summary": str, "technologies": list[str], "structure": str}
    """
    client = get_nebius_client()

    system_prompt = (
        "You are an expert software analyst. "
        "Return ONLY valid JSON. No markdown. No extra text."
    )

    user_prompt = (
        "Analyze the repository content in the input packet and return JSON with exactly these keys:\n"
        "- summary: a concise plain-English overview (2-6 sentences)\n"
        "- technologies: an array of key languages/frameworks/tools (5-20 items, strings only)\n"
        "- structure: a brief description of the repo layout (2-6 sentences)\n\n"
        "Rules:\n"
        "- Output must be a single JSON object and nothing else.\n"
        "- technologies must be a JSON array of strings.\n\n"
        "INPUT PACKET:\n"
        f"{packet}"
    )

    try:
        resp = client.chat.completions.create(
            model=settings.nebius_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )
    except APITimeoutError:
        raise NebiusLLMError("LLM request timed out", status_code=504)
    except RateLimitError:
        raise NebiusLLMError("LLM rate limit exceeded", status_code=429)
    except AuthenticationError:
        raise NebiusLLMError("LLM authentication failed (check NEBIUS_API_KEY)", status_code=500)
    except BadRequestError as e:
        raise NebiusLLMError(f"LLM request rejected: {e}", status_code=502)
    except APIConnectionError as e:
        raise NebiusLLMError(f"Network error contacting LLM: {e}", status_code=502)
    except APIError as e:
        raise NebiusLLMError(f"LLM upstream error: {e}", status_code=502)
    except Exception as e:
        raise NebiusLLMError(f"LLM request failed: {e}", status_code=502)

    if not getattr(resp, "choices", None):
        raise NebiusLLMResponseError("LLM returned no choices")

    content = resp.choices[0].message.content or ""
    data = _extract_json_object(content)

    # Validate and normalize
    summary = data.get("summary")
    technologies = data.get("technologies")
    structure = data.get("structure")

    if not isinstance(summary, str) or not summary.strip():
        raise NebiusLLMResponseError("LLM JSON missing or invalid 'summary'")
    if not isinstance(structure, str) or not structure.strip():
        raise NebiusLLMResponseError("LLM JSON missing or invalid 'structure'")

    if isinstance(technologies, list) and all(isinstance(x, str) for x in technologies):
        tech_list: List[str] = technologies
    else:
        raise NebiusLLMResponseError("LLM JSON missing or invalid 'technologies' (must be list of strings)")

    return {
        "summary": summary.strip(),
        "technologies": [t.strip() for t in tech_list if t and t.strip()],
        "structure": structure.strip(),
    }