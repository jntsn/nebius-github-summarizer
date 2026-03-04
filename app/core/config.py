import os
from dataclasses import dataclass

from dotenv import load_dotenv

# Loads .env for local development. In CI/production, real env vars still work.
load_dotenv()


@dataclass(frozen=True)
class Settings:
    nebius_api_key: str | None = os.getenv("NEBIUS_API_KEY")
    nebius_base_url: str = os.getenv("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1")
    nebius_model: str = os.getenv(
        "NEBIUS_MODEL",
        "meta-llama/Meta-Llama-3.1-70B-Instruct",
    )


settings = Settings()
