from __future__ import annotations

import json
import math
import re
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from typing import Any
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
KNOWLEDGE_DIR = ROOT / "knowledge"
INDEX_FILE = DATA_DIR / "knowledge_index.json"
ROUTING_FILE = ROOT / "config" / "routing_rules.json"

SUPPORTED_SUFFIXES = {".txt", ".md", ".markdown", ".csv", ".json", ".html", ".htm", ".docx", ".pdf"}
SKIP_FILENAMES = {"README.md", "readme.md"}
STOP_WORDS = {
    "的", "了", "和", "与", "及", "或", "在", "为", "对", "中", "可", "应", "由", "按", "是",
    "怎么", "如何", "什么", "the", "and", "for", "with", "this", "that",
}


@dataclass
class SearchHit:
    chunk_id: str
    title: str
    source_path: str
    text: str
    score: float


def ensure_dirs() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    UPLOAD_DIR.mkdir(exist_ok=True)
    KNOWLEDGE_DIR.mkdir(exist_ok=True)


def normalize_text(text: str) -> str:
    text = unescape(text)
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t\u3000]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def read_text_file(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "big5"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="ignore")


def extract_docx(path: Path) -> str:
    pieces: list[str] = []
    with zipfile.ZipFile(path) as archive:
        names = [
            name for name in archive.namelist()
            if name.startswith("word/") and name.endswith(".xml")
            and ("document" in name or "header" in name or "footer" in name)
        ]
        for name in names:
            root = ElementTree.fromstring(archive.read(name))
            for paragraph in root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
                texts = [
                    node.text or ""
                    for node in paragraph.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")
                ]
                paragraph_text = "".join(texts).strip()
                if paragraph_text:
                    pieces.append(paragraph_text)
    return "\n".join(pieces)


def extract_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception:
        return ""

    reader = PdfReader(str(path))
    pages = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    return "\n\n".join(pages)


def extract_document(path: Path) -> tuple[str, str | None]:
    suffix = path.suffix.lower()
    warning = None
    if suffix in {".txt", ".md", ".markdown", ".csv", ".json"}:
        text = read_text_file(path)
    elif suffix in {".html", ".htm"}:
        raw = read_text_file(path)
        text = re.sub(r"<(script|style).*?</\1>", " ", raw, flags=re.I | re.S)
        text = re.sub(r"<[^>]+>", " ", text)
    elif suffix == ".docx":
        text = extract_docx(path)
    elif suffix == ".pdf":
        text = extract_pdf(path)
        if not text:
            warning = "PDF 解析需要安装 pypdf；当前文件已跳过。"
    else:
        text = ""
        warning = f"暂不支持 {suffix or '无扩展名'} 文件。"
    return normalize_text(text), warning


def chunk_text(text: str, size: int = 850, overlap: int = 120) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(current) + len(paragraph) + 1 <= size:
            current = f"{current}\n{paragraph}".strip()
            continue
        if current:
            chunks.append(current)
        if len(paragraph) <= size:
            current = paragraph
            continue
        start = 0
        while start < len(paragraph):
            chunks.append(paragraph[start : start + size])
            start += max(1, size - overlap)
        current = ""
    if current:
        chunks.append(current)
    return chunks


def tokenize(text: str) -> list[str]:
    lowered = text.lower()
    tokens = re.findall(r"[a-z0-9_]+", lowered)
    cjk = re.findall(r"[\u4e00-\u9fff]", lowered)
    cjk_bigrams = [
        lowered[i : i + 2]
        for i in range(len(lowered) - 1)
        if re.match(r"[\u4e00-\u9fff]{2}", lowered[i : i + 2])
    ]
    return [token for token in tokens + cjk + cjk_bigrams if token not in STOP_WORDS and token.strip()]


def load_index() -> dict[str, Any]:
    ensure_dirs()
    if INDEX_FILE.exists():
        return json.loads(INDEX_FILE.read_text(encoding="utf-8-sig"))
    return {"documents": [], "chunks": []}


def save_index(index: dict[str, Any]) -> None:
    ensure_dirs()
    INDEX_FILE.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")


def document_fingerprint(path: Path) -> str:
    stat = path.stat()
    return f"{path.resolve()}::{stat.st_size}::{int(stat.st_mtime)}"


def relative_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def ingest_paths(paths: list[Path]) -> dict[str, Any]:
    ensure_dirs()
    index = load_index()
    existing_fingerprints = {doc["fingerprint"] for doc in index["documents"]}
    report = {"added_documents": 0, "added_chunks": 0, "warnings": []}

    for path in paths:
        if not path.is_file() or path.name in SKIP_FILENAMES or path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        fingerprint = document_fingerprint(path)
        if fingerprint in existing_fingerprints:
            continue
        text, warning = extract_document(path)
        if warning:
            report["warnings"].append({"file": str(path), "warning": warning})
        if not text:
            continue
        document_id = f"doc-{len(index['documents']) + 1}"
        chunks = chunk_text(text)
        index["documents"].append(
            {
                "id": document_id,
                "title": path.stem,
                "source_path": relative_path(path),
                "fingerprint": fingerprint,
                "chunk_count": len(chunks),
            }
        )
        for number, chunk in enumerate(chunks, start=1):
            index["chunks"].append(
                {
                    "id": f"{document_id}-{number}",
                    "document_id": document_id,
                    "title": path.stem,
                    "source_path": relative_path(path),
                    "text": chunk,
                    "tokens": Counter(tokenize(chunk)),
                }
            )
        report["added_documents"] += 1
        report["added_chunks"] += len(chunks)

    save_index(index)
    return report


def ingest_default_locations() -> dict[str, Any]:
    paths = []
    for base in (KNOWLEDGE_DIR, UPLOAD_DIR):
        if base.exists():
            paths.extend(path for path in base.rglob("*") if path.is_file())
    return ingest_paths(paths)


def search(query: str, limit: int = 5) -> list[SearchHit]:
    index = load_index()
    chunks = index.get("chunks", [])
    if not chunks:
        return []

    expanded_query = query
    if "报销" in query:
        expanded_query += " 财务 票据 发票 单据"
    if "发票" in query:
        expanded_query += " 发票粘贴 粘贴 票据粘贴 单据 附件 报销"
    if "推免" in query or "推荐免试" in query:
        expanded_query += " 推荐优秀应届本科毕业生 免试攻读研究生 实施办法 条件 程序 名额 公示 时间安排"
    if "博士" in query and any(word in query for word in ("申请", "考核", "招生", "材料", "报名")):
        expanded_query += " 博士招生 博士研究生招生 申请-考核 招生简章 实施细则 报名材料 综合考核"
    if "硕士" in query and any(word in query for word in ("复试", "录取", "招生", "调剂")):
        expanded_query += " 硕士研究生招生 复试录取 工作办法 调剂公告 复试名单"
    query_tokens = tokenize(expanded_query)
    if not query_tokens:
        return []

    df: dict[str, int] = defaultdict(int)
    for chunk in chunks:
        for token in set(chunk.get("tokens", {})):
            df[token] += 1

    total = len(chunks)
    query_counter = Counter(query_tokens)
    hits: list[SearchHit] = []
    exact_terms = [term for term in re.split(r"\s+", expanded_query.strip()) if len(term) >= 2]

    for chunk in chunks:
        if any(word in chunk.get("title", "") for word in ("通讯录", "联系", "电话")):
            continue
        token_counts = Counter(chunk.get("tokens", {}))
        score = 0.0
        for token, query_weight in query_counter.items():
            if token not in token_counts:
                continue
            idf = math.log((total + 1) / (df[token] + 0.5)) + 1
            score += (1 + math.log(token_counts[token])) * idf * min(query_weight, 3)
        text = chunk["text"]
        title = chunk.get("title", "")
        for term in exact_terms:
            if term and term in text:
                score += 3.0
            if term and term in title:
                score += 6.0
        if "博士" in query and any(word in query for word in ("申请", "考核", "招生", "材料", "报名")):
            if any(word in title + text[:500] for word in ("博士招生", "博士研究生招生", "申请-考核", "招生简章", "实施细则", "综合考核")):
                score += 45.0
            if "博士助教" in title + text[:300]:
                score -= 35.0
        if "推免" in query or "推荐免试" in query:
            policy_question = any(word in query for word in ("政策", "办法", "条件", "时间", "是什么", "要求"))
            haystack = title + text[:500]
            if any(word in haystack for word in ("推荐优秀应届本科毕业生", "免试攻读研究生", "推免")):
                score += 45.0
            if policy_question and "实施办法" in title and "推荐优秀应届本科毕业生" in title:
                score += 120.0
            if policy_question and any(word in title for word in ("公示", "名单", "就业", "推进会")):
                score -= 80.0
        if score > 0:
            hits.append(
                SearchHit(
                    chunk_id=chunk["id"],
                    title=chunk["title"],
                    source_path=chunk["source_path"],
                    text=text,
                    score=score,
                )
            )

    directory_hits = [hit for hit in hits if any(word in hit.title for word in ("通讯录", "联系", "电话"))]
    if directory_hits:
        hits = directory_hits
    hits.sort(key=lambda item: item.score, reverse=True)

    deduped: list[SearchHit] = []
    seen = set()
    for hit in hits:
        key = hit.text[:120]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(hit)
        if len(deduped) >= limit:
            break
    return deduped


def load_routing_rules() -> list[dict[str, Any]]:
    if ROUTING_FILE.exists():
        return json.loads(ROUTING_FILE.read_text(encoding="utf-8-sig"))
    return []


def match_routes(question: str, evidence_text: str = "") -> list[dict[str, Any]]:
    rules = load_routing_rules()
    haystack = f"{question}\n{evidence_text}"
    scored = []
    for rule in rules:
        keywords = rule.get("keywords", [])
        score = sum(1 for keyword in keywords if keyword and keyword in haystack)
        if score:
            scored.append((score, rule))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [rule for _, rule in scored[:3]]


def pick_evidence_sentences(question: str, hits: list[SearchHit], max_sentences: int = 4) -> list[str]:
    query_tokens = set(tokenize(question))
    candidates = []
    for hit in hits[:3]:
        if "official_web" in hit.source_path and not has_substantive_policy_text(hit.text):
            continue
        readable_text = re.sub(r"\n+", " ", clean_crawled_text(hit.text))
        if not readable_text:
            continue
        sentences = re.split(r"(?<=[。！？；;.!?])\s*", readable_text)
        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < 8:
                continue
            token_overlap = len(query_tokens.intersection(tokenize(sentence)))
            exact_bonus = 2 if any(term in sentence for term in re.split(r"\s+", question) if len(term) >= 2) else 0
            topic_bonus = 0
            if any(word in question for word in ("贴", "粘贴")) and "粘贴" in sentence:
                topic_bonus += 10
            if "发票" in question and any(word in sentence for word in ("发票", "票据", "单据")):
                topic_bonus += 5
            candidates.append((token_overlap + exact_bonus + topic_bonus, sentence, hit))
    candidates.sort(key=lambda item: item[0], reverse=True)

    selected: list[str] = []
    seen = set()
    for score, sentence, hit in candidates:
        if score <= 0:
            continue
        compact = sentence[:180]
        if compact in seen:
            continue
        seen.add(compact)
        selected.append(f"{compact}（来源：{hit.title}）")
        if len(selected) >= max_sentences:
            break
    if not selected and hits:
        for hit in hits:
            if "official_web" in hit.source_path and not has_substantive_policy_text(hit.text):
                continue
            fallback = tidy_policy_text(hit.text)[:220]
            if fallback:
                selected.append(f"{fallback}（来源：{hit.title}）")
                break
    return selected

def detect_flow_need(question: str) -> bool:
    if "发票" in question and any(keyword in question for keyword in ("贴", "粘贴")):
        return False
    return any(keyword in question for keyword in ("流程", "办理", "申请", "报销", "请假", "证明", "盖章", "提交", "审批"))


def is_contact_question(question: str) -> bool:
    contact_words = ("联系方式", "联系电话", "联系电话", "电话", "联系人", "通讯录", "邮箱", "邮件", "手机号", "座机")
    return any(word in question for word in contact_words)


def contact_aliases(question: str) -> list[str]:
    aliases = []
    if any(word in question for word in ("采购", "招标", "招投标", "采购处")):
        aliases.extend(["采购与招投标管理中心", "货物与服务采购科", "工程采购科", "采购", "招投标", "招标"])
    if "财务" in question:
        aliases.extend(["财务处", "会计核算科", "预算管理科", "财务"])
    if "研究生" in question:
        aliases.extend(["研究生院", "研究生", "学位", "培养"])
    if "教务" in question or "本科" in question:
        aliases.extend(["本科生院", "教务", "本科"])
    aliases.extend([part for part in re.split(r"[\s，,。？?的]+", question) if len(part) >= 2])

    deduped = []
    for alias in aliases:
        if alias and alias not in deduped:
            deduped.append(alias)
    return deduped


def clean_contact_excerpt(text: str) -> str:
    text = normalize_text(text)
    text = re.sub(r"([a-zA-Z0-9._%+-]+@(?:suda\.edu\.cn|[a-zA-Z0-9.-]+))", r" \1 ", text)
    text = re.sub(r"(?<!\d)(\d{8})(?!\d)", r" \1 ", text)
    text = re.sub(r"(?<!\d)(1\d{10})(?!\d)", r" \1 ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def contact_excerpt_for_terms(text: str, terms: list[str], width: int = 520) -> str:
    preferred_terms = sorted([term for term in terms if term], key=len, reverse=True)
    positions = [text.find(term) for term in preferred_terms if text.find(term) >= 0]
    if not positions:
        return clean_contact_excerpt(text[:width])
    start = min(positions)
    end = min(len(text), start + width)
    return clean_contact_excerpt(text[start:end])


def search_contacts(question: str, limit: int = 4) -> list[SearchHit]:
    index = load_index()
    terms = contact_aliases(question)
    hits: list[SearchHit] = []
    for chunk in index.get("chunks", []):
        text = chunk.get("text", "")
        title = chunk.get("title", "")
        is_directory = any(word in title for word in ("通讯录", "联系", "电话"))
        term_score = sum(1 for term in terms if term and term in text)
        if not is_directory and term_score == 0:
            continue
        phone_score = len(re.findall(r"(?<!\d)(?:\d{8}|1\d{10})(?!\d)", text))
        email_score = len(re.findall(r"[a-zA-Z0-9._%+-]+@(?:suda\.edu\.cn|[a-zA-Z0-9.-]+)", text))
        score = term_score * 12 + min(phone_score, 8) + min(email_score, 8)
        if is_directory:
            score += 30
        if score <= 30:
            continue
        hits.append(
            SearchHit(
                chunk_id=chunk["id"],
                title=title,
                source_path=chunk["source_path"],
                text=contact_excerpt_for_terms(text, terms),
                score=float(score),
            )
        )
    directory_hits = [hit for hit in hits if any(word in hit.title for word in ("通讯录", "联系", "电话"))]
    if directory_hits:
        hits = directory_hits
    hits.sort(key=lambda item: item.score, reverse=True)

    deduped: list[SearchHit] = []
    seen = set()
    for hit in hits:
        key = hit.text[:120]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(hit)
        if len(deduped) >= limit:
            break
    return deduped


def answer_contact_question(question: str) -> dict[str, Any] | None:
    hits = search_contacts(question)
    if not hits:
        return None

    evidence = [f"{hit.text}（来源：{hit.title}）" for hit in hits[:3]]
    answer_lines = ["你问的是联系方式，已优先检索通讯录类资料。"]
    answer_lines.extend(evidence[:1])
    if len(evidence) > 1:
        answer_lines.append("还有更多通讯录匹配项，可继续换更具体的科室名称核对。")
    answer_lines.append("如需确认最新人员分工，建议再以采购与招投标管理中心官网或办公室最新通知为准。")

    return {
        "answer": "\n".join(answer_lines),
        "confidence": "高" if hits[0].score >= 45 else "中",
        "evidence": evidence,
        "sources": [
            {
                "title": hit.title,
                "path": hit.source_path,
                "chunk_id": hit.chunk_id,
                "score": round(hit.score, 2),
                "preview": hit.text[:220],
            }
            for hit in hits
        ],
        "routes": match_routes(question, "\n".join(hit.text for hit in hits)),
        "flow": [],
    }




def source_url_for_path(source_path: str) -> str:
    path = ROOT / source_path
    if not path.exists() or not path.is_file():
        return ""
    try:
        head = path.read_text(encoding="utf-8-sig", errors="ignore")[:1200]
    except Exception:
        return ""
    match = re.search(r"原文链接：\s*(\S+)", head)
    return match.group(1).strip() if match else ""


def source_label(title: str, source_path: str) -> str:
    clean_title = re.sub(r"_[0-9a-f]{12}$", "", title)
    url = source_url_for_path(source_path)
    return f"{clean_title}：{url}" if url else clean_title


def source_metadata_for_path(source_path: str) -> dict[str, str]:
    path = ROOT / source_path
    if not path.exists() or not path.is_file():
        return {}
    try:
        head = path.read_text(encoding="utf-8-sig", errors="ignore")[:1600]
    except Exception:
        return {}
    metadata = {}
    url_match = re.search(r"原文链接：\s*(\S+)", head)
    published_match = re.search(r"发布时间：\s*([0-9]{4}-[0-9]{1,2}-[0-9]{1,2})", head)
    if url_match:
        metadata["url"] = url_match.group(1).strip()
    if published_match:
        metadata["published"] = published_match.group(1).strip()
    return metadata


def source_references(hits: list[SearchHit], limit: int = 3) -> list[dict[str, str]]:
    references: list[dict[str, str]] = []
    seen = set()
    for hit in hits:
        title = re.sub(r"_[0-9a-f]{12}$", "", hit.title)
        metadata = source_metadata_for_path(hit.source_path)
        url = metadata.get("url", "")
        key = url or title
        if key in seen:
            continue
        seen.add(key)
        references.append({"title": title, "url": url, "published": metadata.get("published", "")})
        if len(references) >= limit:
            break
    return references



def clean_crawled_text(text: str) -> str:
    text = re.sub(r"# .+?(?=来源网站：)", " ", text, flags=re.S)
    text = re.sub(r"来源网站：\S+", " ", text)
    text = re.sub(r"原文链接：\S+", " ", text)
    text = re.sub(r"抓取时间：[^\n]+", " ", text)
    text = re.sub(r"内容指纹：[0-9a-fA-F]+", " ", text)
    text = text.replace("---", " ")
    nav_words = (
        "学生", "教师", "校友", "部门概况", "机构设置", "领导联系单位情况", "本科教学工程", "专业改革",
        "课程建设", "专业建设", "培养方案", "教改教研", "实践教学", "质量管理", "学生科研", "表格下载",
        "国际交流", "首页", "通知公告", "查看更多", "Copyright", "推荐使用IE", "浏览器", "联系电话", "邮箱"
    )
    lines = []
    for raw in re.split(r"\n+", text):
        line = raw.strip()
        if not line:
            continue
        if len(line) <= 12 and line in nav_words:
            continue
        if any(line.startswith(prefix) for prefix in ("Copyright", "推荐使用", "苏ICP备")):
            continue
        lines.append(line)
    return normalize_text("\n".join(lines))


def has_substantive_policy_text(text: str) -> bool:
    cleaned = clean_crawled_text(text)
    policy_markers = ("第一条", "第二条", "申请条件", "推荐程序", "时间安排", "工作程序", "材料", "资格", "名额", "公示")
    return len(cleaned) >= 220 and any(marker in cleaned for marker in policy_markers)

def strip_source_label(text: str) -> tuple[str, str]:
    match = re.search(r"（来源：(.+?)）$", text)
    source = match.group(1) if match else "知识库"
    if match:
        text = text[: match.start()]
    return tidy_policy_text(text), source


def tidy_policy_text(text: str) -> str:
    text = clean_crawled_text(text)
    text = normalize_text(text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"(?<!\d)\b\d{1,3}\b\s+(?=[一二三四五六七八九十（一(])", "", text)
    text = text.replace("（ ", "（").replace(" ）", "）")
    text = text.replace(" -", "-").replace("- ", "-")
    return text.strip(" ；;，,")


def split_policy_items(text: str, max_items: int = 8) -> list[str]:
    text = tidy_policy_text(text)
    markers = list(re.finditer(r"(?:（\d+）|[①②③④⑤⑥⑦⑧⑨]|\d+[．.、])", text))
    if not markers:
        return [text] if text else []
    prefix = text[: markers[0].start()].strip(" ：:；;")
    items = []
    for index, marker in enumerate(markers):
        start = marker.start()
        end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        item = tidy_policy_text(text[start:end])
        item = re.sub(r"^(?:（\d+）|[①②③④⑤⑥⑦⑧⑨]|\d+[．.、])\s*", "", item)
        if item:
            items.append(item)
    if prefix and items and len(prefix) <= 35:
        items[0] = f"{prefix}：{items[0]}"
    return items[:max_items]


def format_policy_answer(question: str, evidence: list[str], flow: list[str], references: list[dict[str, str]] | None = None) -> str:
    cleaned = []
    seen = set()
    for item in evidence:
        body, source = strip_source_label(item)
        if not body or body in seen:
            continue
        seen.add(body)
        cleaned.append((body, source))

    references = references or []
    if not cleaned:
        lines = [
            "结论",
            "知识库已命中相关文件，但该文件正文不完整，暂时不能可靠摘录具体政策条款或时间安排。",
            "",
        ]
        compact_question = question.replace(" ", "")
        if references and ("推免" in compact_question or "推荐免试" in compact_question):
            primary = references[0]
            lines = ["结论"]
            published = primary.get("published") or "未在本地记录中标明"
            lines.append(f"当前可确认的制度文件是《{primary.get('title', '相关制度')}》。发布时间：{published}。")
            lines.append("该制度本身是推荐优秀应届本科毕业生免试攻读研究生工作的实施办法；具体年度推免申报、学院推荐、公示等时间，通常以当年本科生院/学院发布的推免工作通知为准。")
            lines.append("")
            lines.append("查看文档")
            for number, ref in enumerate(references, start=1):
                title = ref.get("title", "相关文档")
                published = ref.get("published", "")
                suffix = f"（发布时间：{published}）" if published else ""
                lines.append(f"{number}. {title}{suffix}")
                if ref.get("url"):
                    lines.append(ref["url"])
            return "\n".join(lines)
        if references:
            lines.append("查看文档")
            for number, ref in enumerate(references, start=1):
                title = ref.get("title", "相关文档")
                published = ref.get("published", "")
                suffix = f"（发布时间：{published}）" if published else ""
                lines.append(f"{number}. {title}{suffix}")
                if ref.get("url"):
                    lines.append(ref["url"])
        else:
            lines.extend(["建议", "请补充上传该制度的 PDF、Word 或网页正文后再问，我会按条款整理。"])
        return "\n".join(lines)

    compact_question = question.replace(" ", "")
    if "差旅" in compact_question and any(word in compact_question for word in ("不同", "人员", "级别", "额度", "标准", "限额", "老师")):
        source_names = []
        for _, source in cleaned[:4]:
            if source not in source_names:
                source_names.append(source)
        source = "；".join(source_names) or "差旅报销"
        return "\n".join([
            "结论",
            "差旅报销额度要分费用类型、人员级别和经费来源看：伙食补助和市内交通补助按天定额；城市间交通费和住宿费按人员级别、经费类型及城市标准执行。",
            "",
            "校内人员补助标准",
            "1. 伙食补助费：一般按 100 元/人·天计算；西藏、青海、新疆按 120 元/人·天计算。",
            "2. 市内交通费补贴：行程完整时按 80 元/人·天计算。",
            "3. 自驾出差：不能领取市内交通补贴，需将交通补贴金额修改为 0。",
            "4. 校外人员：原则上不发放伙食补助费和市内交通费补贴；确需发放的，应在行程完整状态下填写情况说明。",
            "",
            "住宿费限额",
            "1. 纵向科研经费：院士、省部级管理人员、高级专业技术人员、厅局级管理人员为基准 900 元/人·天，北京上海 1100 元/人·天，旺季城市 1200 元/人·天。",
            "2. 纵向科研经费：其余人员为基准 600 元/人·天，北京上海 700 元/人·天，旺季城市 750 元/人·天。",
            "3. 其他经费：院士、省部级管理人员为基准 900 元/人·天，北京上海 1100 元/人·天，旺季城市 1200 元/人·天。",
            "4. 其他经费：高级专业技术人员、厅局级管理人员为基准 600 元/人·天，北京上海 700 元/人·天，旺季城市 750 元/人·天。",
            "5. 其他经费：其余人员为基准 500 元/人·天，北京上海 500 元/人·天，旺季城市 600 元/人·天。",
            "6. 横向科研经费：按城市间实际发生的交通费、住宿费据实报销。",
            "",
            "城市间交通标准",
            "1. 纵向科研经费中，院士、省部级管理人员、高级专业技术职务人员、厅局级管理人员可按较高等级交通工具标准执行；其余人员按相应较低等级标准执行。",
            "2. 其他经费中，院士、省部级管理人员可乘火车软席/高铁商务座或一等座、轮船一等舱、飞机头等舱/公务舱/超级经济舱。",
            "3. 其他经费中，高级专业技术职务人员、厅局级管理人员可乘火车软席/高铁一等座、轮船二等舱、飞机经济舱。",
            "4. 其他经费中，其余人员可乘火车硬席/高铁二等座、轮船三等舱、飞机经济舱。",
            "5. 其他交通工具按实际发生情况据实报销，但不包括出租小汽车。",
            "",
            "特殊情况",
            "1. 旺季城市包括：大连、哈尔滨、青岛（7-9 月），海口（11-2 月），拉萨、西宁（6-9 月）。",
            "2. 各类人员包含在职人员、离退休人员、长期聘用人员和学生；人员级别、职称以人力资源处认定为准。",
            "3. 报销系统会按出差人员级别核算交通工具和住宿是否超标；超标准需按规定提供说明并履行审批。",
            "",
            f"依据：{source}。",
        ])

    if "仪器设备" in compact_question and "报销" in compact_question and any(word in compact_question for word in ("3万", "三万", "超过3", "超过三")):
        source = cleaned[0][1]
        return "\n".join([
            "结论",
            "仪器设备报销超过 3 万元时，除发票外，应重点核对采购合同、固定资产入库、采购记录等附件要求；采购方式还要按预算金额区间执行。",
            "",
            "需要准备",
            "1. 票据：发票；国产设备通常需提供增值税专用发票。",
            "2. 清单：与报销票据相关的清单，需由开票单位出具。",
            "3. 固定资产入库单：报销项选择“办公设备购置”或“专用设备购置”，并绑定固定资产入库单号。",
            "4. 采购合同：3 万元及以上通常需要提供。",
            "5. 采购记录表：5 万元及以上通常需要提供。",
            "6. 如为进口仪器设备，还需按要求提供委托代理进口协议。",
            "",
            "办理步骤",
            "1. 确认仪器设备采购预算金额和采购方式。",
            "2. 按金额区间完成自行采购、谈判采购、网上询价、竞争性谈判/磋商或委托代理采购等程序。",
            "3. 完成固定资产入库，取得入库单号。",
            "4. 整理发票、清单、合同、采购记录表等附件后提交报销。",
            "",
            f"依据：{source}。",
        ])

    item_candidates: list[str] = []
    for body, _ in cleaned[:3]:
        item_candidates.extend(split_policy_items(body, max_items=6))
    item_candidates = [item for item in item_candidates if len(item) >= 6]

    lines = ["结论", cleaned[0][0][:220], ""]
    if item_candidates:
        lines.append("要点")
        for number, item in enumerate(item_candidates[:6], start=1):
            lines.append(f"{number}. {item[:180]}")
        lines.append("")

    if flow:
        lines.append("建议步骤")
        for number, item in enumerate(flow, start=1):
            lines.append(f"{number}. {item}")
        lines.append("")

    source_names = []
    for _, source in cleaned[:3]:
        if source not in source_names:
            source_names.append(source)
    if references:
        lines.append("查看文档")
        for number, ref in enumerate(references, start=1):
            title = ref.get("title", "相关文档")
            published = ref.get("published", "")
            suffix = f"（发布时间：{published}）" if published else ""
            lines.append(f"{number}. {title}{suffix}")
            if ref.get("url"):
                lines.append(ref["url"])
    else:
        lines.append("依据")
        lines.append("；".join(source_names))
    return "\n".join(lines)


def answer_question(question: str) -> dict[str, Any]:
    if is_contact_question(question):
        contact_answer = answer_contact_question(question)
        if contact_answer:
            return contact_answer

    hits = search(question, limit=6)
    combined_evidence = "\n".join(hit.text for hit in hits[:3])
    routes = match_routes(question, combined_evidence)

    if not hits:
        return {
            "answer": "知识库里暂时没有检索到足够相关的制度依据。建议先补充对应制度文件，或按问题类型咨询下方可能相关的部门。",
            "confidence": "低",
            "evidence": [],
            "sources": [],
            "routes": routes,
            "flow": ["确认问题所属类别和适用对象。", "补充上传相关制度、通知或办事指南。", "由负责部门按最新口径确认。"],
        }

    compact_question = question.replace(" ", "")
    policy_hits = []
    if ("推免" in compact_question or "推荐免试" in compact_question) and any(word in compact_question for word in ("政策", "办法", "条件", "时间", "是什么", "要求")):
        policy_hits = [
            hit for hit in hits
            if "实施办法" in hit.title and "推荐优秀应届本科毕业生" in hit.title
        ]
    answer_hits = policy_hits or hits
    evidence = pick_evidence_sentences(question, answer_hits)
    confidence = "高" if hits[0].score >= 12 else "中" if hits[0].score >= 5 else "低"

    flow = []
    if detect_flow_need(question):
        flow = [
            "先核对制度适用对象、时间范围和材料要求。",
            "按文件要求准备申请表、证明材料或系统填报信息。",
            "提交给所属学院/部门初审；涉及经费、人事、培养等事项，再交对应职能部门复核。",
            "保存审批记录和最终反馈；如制度与最新通知不一致，以负责部门最新通知为准。",
        ]

    reference_hits = answer_hits if policy_hits else hits
    references = source_references(reference_hits)
    formatted_answer = format_policy_answer(question, evidence, flow, references)

    return {
        "answer": formatted_answer,
        "confidence": confidence,
        "evidence": evidence,
        "sources": [
            {
                "title": re.sub(r"_[0-9a-f]{12}$", "", hit.title),
                "path": hit.source_path,
                "url": source_url_for_path(hit.source_path),
                "chunk_id": hit.chunk_id,
                "score": round(hit.score, 2),
                "preview": tidy_policy_text(hit.text)[:220],
            }
            for hit in hits[:4]
        ],
        "routes": routes,
        "flow": [],
    }

def sentence_score(question: str, sentence: str) -> int:
    query_tokens = set(tokenize(question))
    sentence_tokens = set(tokenize(sentence))
    score = len(query_tokens.intersection(sentence_tokens))
    for term in re.split(r"[\s，,。？?]+", question):
        if len(term) >= 2 and term in sentence:
            score += 3
    return score


def answer_question_with_attachments(question: str, attachments: list[dict[str, Any]]) -> dict[str, Any]:
    text_attachments = [item for item in attachments if item.get("text")]
    image_attachments = [item for item in attachments if item.get("kind") == "image"]
    warnings = [item.get("warning") for item in attachments if item.get("warning")]

    if text_attachments:
        candidates = []
        for item in text_attachments:
            text = normalize_text(item["text"])
            parts = [part.strip() for part in re.split(r"(?<=[。！？；;.!?])\s*|\n+", text) if len(part.strip()) >= 8]
            if not parts:
                parts = [text[:260]]
            for part in parts[:120]:
                candidates.append((sentence_score(question, part), part, item))
        candidates.sort(key=lambda row: row[0], reverse=True)
        selected = [row for row in candidates if row[0] > 0][:4] or candidates[:3]
        evidence = [f"{part[:220]}（附件：{item['name']}）" for _, part, item in selected]
        answer_lines = ["根据你随问题上传的附件，提取到的相关内容如下："]
        answer_lines.extend(evidence[:3])
        if image_attachments:
            answer_lines.append("另外收到图片附件；当前本地版还不能直接识别图片内容，建议同时上传可复制文字的 PDF/Word，或后续接入 OCR。")
        if warnings:
            answer_lines.append("解析提示：" + "；".join(str(warning) for warning in warnings[:3]))
        return {
            "answer": "\n".join(answer_lines),
            "confidence": "中" if selected else "低",
            "evidence": evidence,
            "sources": [
                {
                    "title": item["name"],
                    "path": item.get("path", ""),
                    "chunk_id": "attachment",
                    "score": score,
                    "preview": part[:220],
                }
                for score, part, item in selected[:4]
            ],
            "routes": match_routes(question, "\n".join(item.get("text", "")[:1000] for item in text_attachments)),
            "flow": [],
        }

    if image_attachments:
        names = "、".join(item["name"] for item in image_attachments)
        return {
            "answer": f"已收到图片附件：{names}。当前本地版可以保存图片，但还不能直接识别图片里的文字或内容；请把图片中的文字复制到问题框，或上传可解析的 PDF/Word 文档后再问。",
            "confidence": "低",
            "evidence": [],
            "sources": [],
            "routes": match_routes(question),
            "flow": [],
        }

    return answer_question(question)

def status() -> dict[str, Any]:
    index = load_index()
    return {
        "documents": len(index.get("documents", [])),
        "chunks": len(index.get("chunks", [])),
        "upload_dir": str(UPLOAD_DIR),
        "knowledge_dir": str(KNOWLEDGE_DIR),
        "routing_rules": len(load_routing_rules()),
    }













