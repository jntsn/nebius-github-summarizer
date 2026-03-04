from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SelectionLimits:
    max_files: int = 60
    max_bytes_per_file: int = 200_000
    max_total_bytes: int = 1_500_000
    max_lockfile_bytes: int = 50_000  # only used if you choose to allow lockfiles


@dataclass(frozen=True)
class SelectedFile:
    rel_path: str
    size_bytes: int


IGNORE_DIRS = {
    ".git", ".venv", "venv", "env", "__pycache__", ".pytest_cache", ".mypy_cache",
    "node_modules", "dist", "build", "target", "out", ".next", ".cache", "coverage",
    ".idea", ".vscode",
}

BINARY_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp",
    ".zip", ".tar", ".gz", ".tgz", ".rar", ".7z",
    ".exe", ".dll", ".so", ".dylib", ".class", ".jar",
    ".pyc", ".pyo",
    ".pdf",
}

TEXT_EXTS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".java", ".rs", ".rb", ".php", ".cs", ".c", ".cpp", ".h", ".hpp",
    ".md", ".rst", ".txt", ".yml", ".yaml", ".toml", ".json", ".ini", ".cfg",
}

SPECIAL_TEXT_NAMES = {"Dockerfile", "Makefile", ".env.example"}

PREFERRED_STEMS = {"readme", "license", "changelog", "contributing", "security"}

MANIFEST_NAMES = {
    "pyproject.toml", "requirements.txt", "pipfile", "setup.py", "setup.cfg",
    "package.json", "tsconfig.json",
    "docker-compose.yml", "docker-compose.yaml",
}

LOCKFILES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "pipfile.lock",
}


def _is_ignored_path(rel_parts: tuple[str, ...]) -> bool:
    return any(part in IGNORE_DIRS for part in rel_parts)


def _looks_binary_by_ext(path: Path) -> bool:
    return path.suffix.lower() in BINARY_EXTS


def _looks_text_candidate(path: Path) -> bool:
    if path.name in SPECIAL_TEXT_NAMES:
        return True
    return path.suffix.lower() in TEXT_EXTS


def _is_probably_binary_by_content(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            chunk = f.read(8192)
        return b"\x00" in chunk
    except Exception:
        return True


def _score(rel_path: str) -> int:
    p = rel_path.lower()
    name = Path(p).name
    stem = Path(name).stem

    score = 0

    # top docs and manifests
    if any(stem.startswith(s) for s in PREFERRED_STEMS):
        score += 10_000
    if name in MANIFEST_NAMES:
        score += 9_000

    # GitHub workflows often describe CI, language, commands
    if p.startswith(".github/workflows/") and p.endswith((".yml", ".yaml")):
        score += 4_000

    # prefer typical source roots
    if p.startswith(("src/", "app/", "lib/")):
        score += 2_000
    if p.startswith(("tests/", "test/")):
        score += 500
    if p.startswith(("docs/", "doc/")):
        score += 700

    # extension preferences
    ext = Path(p).suffix
    if ext in {".py", ".ts", ".js", ".go", ".rs", ".java"}:
        score += 200
    if ext in {".md", ".yml", ".yaml", ".toml", ".json"}:
        score += 150

    # lockfiles are low signal
    if name in LOCKFILES:
        score -= 2_000

    # prefer shallower paths
    score -= p.count("/") * 10
    return score


def select_repo_files(root_path: Path, limits: SelectionLimits = SelectionLimits()) -> list[SelectedFile]:
    candidates: list[tuple[int, str, int]] = []

    for abs_path in root_path.rglob("*"):
        if not abs_path.is_file():
            continue

        rel_path = abs_path.relative_to(root_path).as_posix()
        rel_parts = tuple(rel_path.split("/"))

        if _is_ignored_path(rel_parts):
            continue

        if _looks_binary_by_ext(abs_path):
            continue

        if not _looks_text_candidate(abs_path):
            continue

        try:
            size = abs_path.stat().st_size
        except Exception:
            continue

        if size <= 0:
            continue
        if size > limits.max_bytes_per_file:
            continue

        # lockfiles: only allow if small enough
        if abs_path.name.lower() in LOCKFILES and size > limits.max_lockfile_bytes:
            continue

        if _is_probably_binary_by_content(abs_path):
            continue

        candidates.append((_score(rel_path), rel_path, size))

    # sort by score desc, then smaller first, then path
    candidates.sort(key=lambda t: (-t[0], t[2], t[1]))

    selected: list[SelectedFile] = []
    total = 0

    for _, rel_path, size in candidates:
        if len(selected) >= limits.max_files:
            break
        if total + size > limits.max_total_bytes:
            continue
        selected.append(SelectedFile(rel_path=rel_path, size_bytes=size))
        total += size

    return selected