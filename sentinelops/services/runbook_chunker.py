import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_MAX_WORDS_PER_CHUNK = 300


def _split_into_sections(markdown: str) -> list[tuple[str, str]]:
    """Splits markdown into heading-scoped sections so retrieval can preserve semantic context."""

    lines = markdown.splitlines()
    sections: list[tuple[str, list[str]]] = []
    current_title = "intro"
    current_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## ") or stripped.startswith("### "):
            if current_lines:
                sections.append((current_title, current_lines))
            current_title = stripped.lstrip("# ").strip() or "intro"
            current_lines = []
            continue
        current_lines.append(line)

    if current_lines:
        sections.append((current_title, current_lines))

    return [(title, "\n".join(content).strip()) for title, content in sections if "\n".join(content).strip()]


def _split_section_text(section_text: str) -> list[str]:
    """Sub-splits oversized sections on paragraph boundaries to enforce retrieval chunk size limits."""

    paragraphs = [paragraph.strip() for paragraph in section_text.split("\n\n") if paragraph.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_words = 0

    for paragraph in paragraphs:
        words = paragraph.split()
        if len(words) > _MAX_WORDS_PER_CHUNK:
            if current:
                chunks.append("\n\n".join(current).strip())
                current = []
                current_words = 0
            for start in range(0, len(words), _MAX_WORDS_PER_CHUNK):
                piece = " ".join(words[start : start + _MAX_WORDS_PER_CHUNK]).strip()
                if piece:
                    chunks.append(piece)
            continue

        if current_words + len(words) > _MAX_WORDS_PER_CHUNK and current:
            chunks.append("\n\n".join(current).strip())
            current = [paragraph]
            current_words = len(words)
        else:
            current.append(paragraph)
            current_words += len(words)

    if current:
        chunks.append("\n\n".join(current).strip())
    return chunks


def chunk_runbook(filepath: str) -> list[dict]:
    """Chunks one runbook file into heading-aware retrieval units bounded by token budget."""

    path = Path(filepath)
    raw_text = path.read_text(encoding="utf-8")
    filename_stem = path.stem
    sections = _split_into_sections(raw_text)

    output: list[dict] = []
    section_counter = 0
    for section_title, section_text in sections:
        for chunk_text in _split_section_text(section_text):
            token_estimate = len(chunk_text.split()) * 1.3
            output.append(
                {
                    "chunk_id": f"{filename_stem}_{section_counter}",
                    "source_file": path.name,
                    "section_title": section_title,
                    "text": chunk_text,
                    "token_estimate": float(token_estimate),
                }
            )
            section_counter += 1
    return output


def load_all_runbooks(runbook_dir: str) -> list[dict]:
    """Loads and chunks all markdown runbooks so indexing can embed a flat retrievable corpus."""

    directory = Path(runbook_dir)
    all_chunks: list[dict] = []
    for filepath in sorted(directory.glob("*.md")):
        chunks = chunk_runbook(str(filepath))
        logger.info("Runbook %s produced %d chunks", filepath.name, len(chunks))
        all_chunks.extend(chunks)
    return all_chunks