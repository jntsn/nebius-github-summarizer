# API Contract

## Endpoint
- Method: POST
- Path: /summarize
- Purpose: Accept a public GitHub repository URL and return a summary, main technologies, and a short structure description.

## Request

### Headers
- Content-Type: application/json

### Body (JSON)
Required fields:
- github_url (string): URL of a public GitHub repository.

Example:
{
  "github_url": "https://github.com/psf/requests"
}

### Input rules
- github_url is required.
- github_url must be a string.
- github_url must be a GitHub repository URL in the form:
  https://github.com/<owner>/<repo>
- Owner and repo are extracted from the path segments after github.com/ and must be non-empty.
- The service only supports public repositories (private repos are treated as an error).
- Optional: a trailing slash is allowed.
- Optional: a .git suffix is allowed.


### Invalid examples (must fail later)
- { "github_url": "psf/requests" }  (not a URL)
- { "github_url": "https://gitlab.com/a/b" }  (not GitHub)
- { "github_url": "https://github.com/psf" }  (missing repo part)
- { “github_url": “https://github.com/psf/requests/issues" } (not a repo root URL)



## Success response (HTTP 200)

JSON body must contain exactly:
- summary (string)
- technologies (array of strings)
- structure (string)

Schema example:
{
  "summary": "string",
  "technologies": ["string", "string"],
  "structure": "string"
}

Rules:
- All three keys are required.
- technologies must be an array (it may be empty, but it must be an array).
- On success, return only these keys (no extra debug fields).


Example:
{
  "summary": "This project provides an HTTP client library for Python. It focuses on a simple API and common features like sessions and authentication.",
  "technologies": ["Python", "HTTP", "Packaging"],
  "structure": "Top level includes source code, tests, and a README that explains installation and usage."
}


## Error response (HTTP 4xx or 5xx)

JSON body must be:
{
  "status": "error",
  "message": "string"
}

Rules:
- status is always the literal string "error".
- message explains what went wrong in plain language.
- On error, return only status and message (no extra keys).



### Status codes (Stage 1 level)
- 400: client errors (missing github_url, invalid GitHub URL format)
- 500: server errors (missing NEBIUS_API_KEY, unexpected failures)

Example (invalid URL, 400):
{ "status": "error", "message": "Invalid GitHub URL. Expected https://github.com/<owner>/<repo>" }

Example (missing API key, 500):
{ "status": "error", "message": "Missing NEBIUS_API_KEY environment variable" }

## Configuration
- The LLM API key must be provided via environment variable: NEBIUS_API_KEY
- The key must not be hardcoded into source code.

## Stage 1 done checklist
- Defined POST /summarize and its purpose.
- Defined request headers and request JSON with github_url.
- Defined success JSON with summary, technologies, structure and an example.
- Defined error JSON with status and message and examples.
- Defined basic status code rules (400 vs 500).
- Documented NEBIUS_API_KEY as an environment variable requirement.