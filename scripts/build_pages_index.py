from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "knowledge" / "official_web"
OUTPUT_FILE = ROOT / "docs" / "search-index.json"

MAX_CHARS_PER_DOC = 18000
CHUNK_SIZE = 720
CHUNK_OVERLAP = 120


def read_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="ignore")


def clean_text(text: str) -> str:
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t\u3000]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def title_from(path: Path, text: str) -> str:
    for line in text.splitlines():
        line = line.strip(" #\t")
        if line:
            return re.sub(r"_[0-9a-f]{12}$", "", line)
    return re.sub(r"_[0-9a-f]{12}$", "", path.stem)


def source_url(text: str) -> str:
    match = re.search(r"原文链接[:：]\s*(https?://\S+)", text)
    return match.group(1) if match else ""


def chunk_text(text: str) -> list[str]:
    text = text[:MAX_CHARS_PER_DOC]
    paragraphs = [item.strip() for item in re.split(r"\n\s*\n", text) if item.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(current) + len(paragraph) + 1 <= CHUNK_SIZE:
            current = f"{current}\n{paragraph}".strip()
            continue
        if current:
            chunks.append(current)
        if len(paragraph) <= CHUNK_SIZE:
            current = paragraph
            continue
        start = 0
        step = CHUNK_SIZE - CHUNK_OVERLAP
        while start < len(paragraph):
            chunks.append(paragraph[start : start + CHUNK_SIZE])
            start += step
        current = ""
    if current:
        chunks.append(current)
    return chunks


def department_from(path: Path) -> str:
    try:
        relative = path.relative_to(SOURCE_DIR)
    except ValueError:
        return "官网制度"
    return relative.parts[0] if len(relative.parts) > 1 else "官网制度"


def build() -> dict[str, object]:
    docs = []
    chunk_count = 0
    for path in sorted(SOURCE_DIR.rglob("*.md")):
        if "attachments" in path.parts:
            continue
        text = clean_text(read_text(path))
        if not text:
            continue
        title = title_from(path, text)
        department = department_from(path)
        url = source_url(text)
        chunks = chunk_text(text)
        chunk_count += len(chunks)
        docs.append(
            {
                "title": title,
                "department": department,
                "url": url,
                "path": str(path.relative_to(ROOT)).replace("\\", "/"),
                "chunks": chunks,
            }
        )
    payload = {
        "generatedAt": "2026-07-07",
        "source": "knowledge/official_web",
        "documents": docs,
        "documentCount": len(docs),
        "chunkCount": chunk_count,
    }
    OUTPUT_FILE.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return payload


if __name__ == "__main__":
    result = build()
    print(f"Wrote {OUTPUT_FILE} with {result['documentCount']} documents and {result['chunkCount']} chunks.")
