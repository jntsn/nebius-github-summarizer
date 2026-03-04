from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Dict, Any, Tuple


@dataclass
class PacketMeta:
    files_included: int
    files_truncated: int
    packet_truncated: bool
    total_chars: int


def _truncate(text: str, limit: int) -> Tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit] + "\n\n[TRUNCATED]\n", True


def build_llm_packet(
    github_url: str,
    repo_tree_text: str,
    selected_files: Iterable[Dict[str, Any]],
    *,
    tree_max_chars: int = 12_000,
    max_file_chars: int = 12_000,
    max_packet_chars: int = 120_000,
) -> Tuple[str, PacketMeta]:
    """
    selected_files is expected to be an iterable of dicts like:
      {"path": "path/in/repo.py", "content": "..."}
    If your stage-7 output uses different keys, adapt here.
    """

    tree_text, _ = _truncate(repo_tree_text or "", tree_max_chars)

    header = (
        "REPO_SUMMARY_INPUT_PACKET\n"
        f"GitHub URL: {github_url}\n\n"
        "DIRECTORY_TREE\n"
        "------------\n"
        f"{tree_text}\n\n"
        "SELECTED_FILES\n"
        "--------------\n"
    )

    parts: List[str] = [header]
    used = len(header)

    files_included = 0
    files_truncated = 0
    packet_truncated = False

    for f in selected_files:
        path = f.get("path") or f.get("filepath") or f.get("name") or "UNKNOWN_PATH"
        content = f.get("content") or ""

        content2, was_truncated = _truncate(content, max_file_chars)
        if was_truncated:
            files_truncated += 1

        block = (
            f"\nFILE: {path}\n"
            "-----\n"
            "```text\n"
            f"{content2}\n"
            "```\n"
        )

        # Check packet budget before adding
        if used + len(block) > max_packet_chars:
            packet_truncated = True
            parts.append("\n[PACKET_TRUNCATED: budget reached]\n")
            break

        parts.append(block)
        used += len(block)
        files_included += 1

    footer = (
        "\nMETA\n"
        "----\n"
        f"files_included: {files_included}\n"
        f"files_truncated: {files_truncated}\n"
        f"packet_truncated: {packet_truncated}\n"
        f"total_chars: {used}\n"
    )

    if used + len(footer) <= max_packet_chars:
        parts.append(footer)
        used += len(footer)

    packet = "".join(parts)

    meta = PacketMeta(
        files_included=files_included,
        files_truncated=files_truncated,
        packet_truncated=packet_truncated,
        total_chars=used,
    )
    return packet, meta