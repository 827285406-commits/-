from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urldefrag, urljoin, urlparse
from urllib.request import Request, urlopen

from suda_policy_agent.core import KNOWLEDGE_DIR, ROOT, ingest_paths, normalize_text


CONFIG_FILE = ROOT / "config" / "crawl_sources.json"
MANIFEST_FILE = ROOT / "data" / "official_crawl_manifest.json"
OUTPUT_DIR = KNOWLEDGE_DIR / "official_web"
ATTACHMENT_DIR = OUTPUT_DIR / "attachments"
DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".doc", ".wps", ".xls", ".xlsx"}
TEXT_EXTENSIONS = {"", ".html", ".htm", ".shtml", ".jhtml"}
USER_AGENT = "SudaPolicyAgent/0.2 (+local knowledge sync)"


@dataclass
class Link:
    url: str
    text: str


class SimpleHTMLExtractor(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.links: list[Link] = []
        self._capture_title = False
        self._current_href: str | None = None
        self._current_link_text: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {name.lower(): value or "" for name, value in attrs}
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
            return
        if tag == "title":
            self._capture_title = True
        if tag == "a" and attrs_dict.get("href"):
            self._current_href = urljoin(self.base_url, attrs_dict["href"])
            self._current_link_text = []
        if tag in {"p", "br", "li", "tr", "h1", "h2", "h3", "div"}:
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if tag == "title":
            self._capture_title = False
        if tag == "a" and self._current_href:
            text = normalize_text("".join(self._current_link_text))
            self.links.append(Link(self._current_href, text))
            self._current_href = None
            self._current_link_text = []
        if tag in {"p", "li", "tr", "h1", "h2", "h3", "div"}:
            self.text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        data = unescape(data)
        if self._capture_title:
            self.title_parts.append(data)
        if self._current_href is not None:
            self._current_link_text.append(data)
        self.text_parts.append(data)

    @property
    def title(self) -> str:
        return normalize_text("".join(self.title_parts))

    @property
    def text(self) -> str:
        text = "".join(self.text_parts)
        text = re.sub(r"[ \t\f\v]+", " ", text)
        text = re.sub(r"\n[ \t]+", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return normalize_text(text)


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def decode_response(data: bytes, content_type: str) -> str:
    match = re.search(r"charset=([\w\-]+)", content_type, re.I)
    encodings = [match.group(1)] if match else []
    encodings.extend(["utf-8", "gb18030", "big5"])
    for encoding in encodings:
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="ignore")


def fetch(url: str, timeout: int) -> tuple[bytes, str, str]:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout) as response:
        final_url = response.geturl()
        content_type = response.headers.get("Content-Type", "")
        return response.read(), content_type, final_url


def normalized_url(url: str) -> str:
    url, _ = urldefrag(url)
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return ""
    return parsed._replace(fragment="").geturl()


def allowed(url: str, allowed_hosts: set[str]) -> bool:
    host = urlparse(url).netloc.lower()
    for allowed_host in allowed_hosts:
        allowed_host = allowed_host.lower()
        if allowed_host.startswith("*."):
            suffix = allowed_host[1:]
            if host.endswith(suffix):
                return True
        elif host == allowed_host:
            return True
    return False


def suffix_for(url: str) -> str:
    return Path(urlparse(url).path).suffix.lower()


def safe_name(value: str, fallback: str = "document") -> str:
    value = normalize_text(value)
    value = re.sub(r"[\\/:*?\"<>|#%&{}$!`'@+=]+", "_", value)
    value = re.sub(r"\s+", "_", value).strip("._ ")
    return (value[:90] or fallback)


def policy_score(text: str, keywords: list[str], negative_keywords: list[str]) -> int:
    score = 0
    for keyword in keywords:
        if keyword and keyword in text:
            score += 2 if len(keyword) >= 4 else 1
    for keyword in negative_keywords:
        if keyword and keyword in text:
            score -= 1
    return score


def is_policy_like(text: str, keywords: list[str], negative_keywords: list[str], threshold: int = 2) -> bool:
    return policy_score(text, keywords, negative_keywords) >= threshold


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def url_hash(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def write_policy_page(source_name: str, title: str, url: str, text: str, digest: str) -> Path:
    source_dir = OUTPUT_DIR / safe_name(source_name, "source")
    source_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{safe_name(title, 'official_policy')}_{url_hash(url)}.md"
    path = source_dir / filename
    fetched_at = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    body = (
        f"# {title}\n\n"
        f"来源网站：{source_name}\n\n"
        f"原文链接：{url}\n\n"
        f"抓取时间：{fetched_at}\n\n"
        f"内容指纹：{digest}\n\n"
        "---\n\n"
        f"{text}\n"
    )
    path.write_text(body, encoding="utf-8")
    return path


def write_attachment_record(source_name: str, title: str, url: str, saved_path: Path, digest: str) -> Path:
    record_dir = OUTPUT_DIR / safe_name(source_name, "source") / "attachment_records"
    record_dir.mkdir(parents=True, exist_ok=True)
    record = record_dir / f"{safe_name(title, saved_path.stem)}_{url_hash(url)}.md"
    fetched_at = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    body = (
        f"# {title}\n\n"
        f"来源网站：{source_name}\n\n"
        f"原文链接：{url}\n\n"
        f"本地附件：{saved_path}\n\n"
        f"抓取时间：{fetched_at}\n\n"
        f"内容指纹：{digest}\n\n"
        "---\n\n"
        f"该条目为官网附件索引。若附件格式可解析，系统会同时把附件正文加入知识库。\n"
    )
    record.write_text(body, encoding="utf-8")
    return record


def download_attachment(source_name: str, title: str, url: str, data: bytes, digest: str) -> tuple[Path, Path]:
    ATTACHMENT_DIR.mkdir(parents=True, exist_ok=True)
    suffix = suffix_for(url) or ".bin"
    base = safe_name(title or Path(urlparse(url).path).stem, "attachment")
    path = ATTACHMENT_DIR / f"{base}_{url_hash(url)}{suffix}"
    path.write_bytes(data)
    record = write_attachment_record(source_name, title or base, url, path, digest)
    return path, record


def crawl_official_policies(config_path: Path = CONFIG_FILE) -> dict[str, Any]:
    config = load_json(config_path, {})
    allowed_hosts = {host.lower() for host in config.get("allowed_hosts", [])}
    keywords = config.get("policy_keywords", [])
    negative_keywords = config.get("negative_keywords", [])
    max_pages = int(config.get("max_pages", 120))
    max_depth = int(config.get("max_depth", 3))
    save_threshold = int(config.get("save_threshold", 3))
    link_threshold = int(config.get("link_threshold", 1))
    timeout = int(config.get("timeout_seconds", 15))
    delay = float(config.get("polite_delay_seconds", 0.25))
    manifest = load_json(MANIFEST_FILE, {"items": {}})
    items = manifest.setdefault("items", {})

    queue: list[tuple[str, str, int, str]] = []
    for seed in config.get("seeds", []):
        url = normalized_url(seed["url"])
        if url:
            queue.append((seed.get("name", url), url, 0, seed.get("name", url)))

    seen: set[str] = set()
    saved_paths: list[Path] = []
    errors: list[dict[str, str]] = []
    stats = {"visited": 0, "saved_pages": 0, "saved_attachments": 0, "skipped_unchanged": 0}

    while queue and stats["visited"] < max_pages:
        source_name, url, depth, link_text = queue.pop(0)
        url = normalized_url(url)
        if not url or url in seen or not allowed(url, allowed_hosts):
            continue
        seen.add(url)

        ext = suffix_for(url)
        if ext and ext not in TEXT_EXTENSIONS and ext not in DOCUMENT_EXTENSIONS:
            continue

        try:
            data, content_type, final_url = fetch(url, timeout)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            errors.append({"url": url, "error": str(exc)[:180]})
            continue

        digest = content_hash(data)
        manifest_item = items.get(final_url) or items.get(url)
        if manifest_item and manifest_item.get("hash") == digest:
            stats["skipped_unchanged"] += 1
            continue

        stats["visited"] += 1
        ext = suffix_for(final_url) or ext
        combined_hint = f"{link_text} {final_url}"

        if ext in DOCUMENT_EXTENSIONS:
            if is_policy_like(combined_hint, keywords, negative_keywords, threshold=link_threshold):
                attachment_path, record_path = download_attachment(source_name, link_text or Path(final_url).name, final_url, data, digest)
                saved_paths.extend([attachment_path, record_path])
                stats["saved_attachments"] += 1
                items[final_url] = {"hash": digest, "path": str(attachment_path), "updated_at": datetime.now().isoformat()}
            time.sleep(delay)
            continue

        html = decode_response(data, content_type)
        parser = SimpleHTMLExtractor(final_url)
        parser.feed(html)
        title = parser.title or link_text or final_url
        text = parser.text
        page_hint = f"{title}\n{final_url}\n{text[:2500]}"

        if is_policy_like(page_hint, keywords, negative_keywords, threshold=save_threshold) and len(text) >= 120:
            path = write_policy_page(source_name, title, final_url, text, digest)
            saved_paths.append(path)
            stats["saved_pages"] += 1
            items[final_url] = {"hash": digest, "path": str(path), "updated_at": datetime.now().isoformat()}

        if depth < max_depth:
            for link in parser.links:
                child_url = normalized_url(link.url)
                if not child_url or child_url in seen or not allowed(child_url, allowed_hosts):
                    continue
                child_ext = suffix_for(child_url)
                hint = f"{link.text} {child_url}"
                if child_ext in DOCUMENT_EXTENSIONS:
                    if is_policy_like(hint, keywords, negative_keywords, threshold=link_threshold):
                        queue.append((source_name, child_url, depth + 1, link.text))
                elif child_ext in TEXT_EXTENSIONS and is_policy_like(hint, keywords, negative_keywords, threshold=link_threshold):
                    queue.append((source_name, child_url, depth + 1, link.text))

        time.sleep(delay)

    save_json(MANIFEST_FILE, manifest)
    ingest_report = ingest_paths(saved_paths)
    return {"crawl": stats, "saved_files": [str(path) for path in saved_paths], "ingest": ingest_report, "errors": errors[:20]}


if __name__ == "__main__":
    report = crawl_official_policies()
    print(json.dumps(report, ensure_ascii=False, indent=2))
