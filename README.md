# GitHub Repo Summarizer API (FastAPI + Nebius)

API service that accepts a public GitHub repository URL and returns:
- a short project summary
- main technologies used
- brief repo structure description

## Requirements
- macOS
- Python 3.10+
- Nebius Token Factory API key set via `NEBIUS_API_KEY` (do not hardcode keys)

## Setup (macOS)

```bash
git clone https://github.com/jntsn/nebius-github-summarizer.git
cd nebius-github-summarizer

python3 -m venv .venv
source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
```

## Configure environment variables

Copy the example file and set your Nebius key:

```bash
cp .env.example .env
# edit .env and set NEBIUS_API_KEY
```

Required:
- `NEBIUS_API_KEY`

Defaults (already set in code and in `.env.example`):
- `NEBIUS_BASE_URL=https://api.tokenfactory.nebius.com/v1`
- `NEBIUS_MODEL=Qwen/Qwen3-32B-fast`

Security note:
- `.env` is ignored by git via `.gitignore`, so your real key is not committed.

## Run the server

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Useful endpoints:
- Swagger UI: http://localhost:8000/docs
- Health: http://localhost:8000/health

## Test: POST /summarize

```bash
curl -X POST http://localhost:8000/summarize \
  -H "Content-Type: application/json" \
  -d '{"github_url":"https://github.com/tiangolo/fastapi"}'
```

If you see `LLM authentication failed (check NEBIUS_API_KEY)`:
- Confirm `.env` exists and contains `NEBIUS_API_KEY=...`
- Restart uvicorn after updating `.env`

## Response format

### Success (200)
```json
{
  "summary": "…",
  "technologies": ["…"],
  "structure": "…"
}
```

### Error (4xx/5xx)
```json
{
  "status": "error",
  "message": "Description of what went wrong"
}
```

## Model choice
Default model: `Qwen/Qwen3-32B-fast`. Chosen for strong instruction following and good repository and codebase summarization.

## Repository content handling strategy
To stay within the LLM context window, the service selects a subset of high-signal text files before calling the LLM:
- Includes: top-level docs (README, LICENSE, CHANGELOG), key manifests (requirements.txt, pyproject.toml, package.json), GitHub workflows, and source files under common roots (src/, app/, lib/).
- Skips: dependency and build directories (node_modules/, dist/, build/, .venv/), caches, and other low-signal folders.
- Skips binary and large files (images, archives) and enforces a per-file size limit.
- Applies caps on file count and total bytes sent to the LLM, prioritizing docs and manifests first.
