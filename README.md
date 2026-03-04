# GitHub Repo Summarizer API (FastAPI + Nebius)

API service that accepts a public GitHub repository URL and returns:
- a short project summary
- main technologies used
- brief repo structure description

## Requirements
- macOS
- Python 3.10+
- A Nebius Token Factory API key in `NEBIUS_API_KEY` (no hardcoded keys)

## Setup (macOS)

```bash
git clone <YOUR_REPO_URL>
cd <YOUR_REPO_FOLDER>

python3 -m venv .venv
source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt