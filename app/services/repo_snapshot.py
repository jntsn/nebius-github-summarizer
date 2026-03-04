from __future__ import annotations

from pathlib import Path
from typing import Iterable

from app.services.file_selection import SelectedFile


def build_repo_tree_text(root_path: Path, *, max_lines: int = 800) -> str:
    """
    Simple text tree for LLM context.
    Uses a line budget so large repos do not explode the packet.
    """
    lines: list[str] = []
    root_name = root_path.name.rstrip("/")

    lines.append(f"{root_name}/")

    count = 0
    for p in sorted(root_path.rglob("*")):
        if count >= max_lines:
            lines.append("[TREE_TRUNCATED]")
            break

        rel = p.relative_to(root_path).as_posix()
        depth = rel.count("/")
        indent = "  " * (depth + 1)

        if p.is_dir():
            lines.append(f"{indent}{p.name}/")
        else:
            lines.append(f"{indent}{p.name}")

        count += 1

    return "\n".join(lines)


def read_selected_files(
    root_path: Path,
    selected: Iterable[SelectedFile],
    *,
    max_chars_per_file: int = 200_000,
) -> list[dict[str, str]]:
    """
    Converts your SelectedFile list into the shape expected by build_llm_packet:
      [{"path": "...", "content": "..."}]
    Reads as text with errors replaced to avoid crashes on odd encodings.
    """
    out: list[dict[str, str]] = []

    for s in selected:
        abs_path = root_path / s.rel_path

        try:
            content = abs_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            content = f"[READ_ERROR: {e}]"

        if len(content) > max_chars_per_file:
            content = content[:max_chars_per_file] + "\n\n[TRUNCATED]\n"

        out.append({"path": s.rel_path, "content": content})

    return out