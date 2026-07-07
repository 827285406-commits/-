from __future__ import annotations

import cgi
import json
import mimetypes
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from suda_policy_agent.crawler import crawl_official_policies
from suda_policy_agent.core import (
    ROOT,
    UPLOAD_DIR,
    answer_question,
    answer_question_with_attachments,
    extract_document,
    ensure_dirs,
    ingest_default_locations,
    ingest_paths,
    status,
)


HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8765"))
STATIC_DIR = ROOT / "static"
DOCS_DIR = ROOT / "docs"
LOGO_PATH = ROOT / "output" / "cali-round-logo-clean.png"
QUESTION_UPLOAD_DIR = ROOT / "data" / "question_uploads"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}


def safe_filename(name: str) -> str:
    name = Path(name).name
    name = re.sub(r"[^\w.\-\u4e00-\u9fff]+", "_", name, flags=re.UNICODE)
    return name or "uploaded_document"


class AgentHandler(BaseHTTPRequestHandler):
    server_version = "SudaPolicyAgent/0.2"

    def log_message(self, format: str, *args: object) -> None:
        return

    def send_json(self, payload: dict, status_code: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path: Path, content_type: str | None = None) -> None:
        if not path.exists() or not path.is_file():
            self.send_error(404)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
        elif parsed.path == "/api/status":
            self.send_json(status())
        elif parsed.path == "/assets/logo.png":
            self.send_file(LOGO_PATH)
        elif parsed.path in {"/docs", "/docs/"}:
            self.send_file(DOCS_DIR / "index.html", "text/html; charset=utf-8")
        elif parsed.path.startswith("/docs/"):
            target = (DOCS_DIR / parsed.path.removeprefix("/docs/")).resolve()
            if not str(target).startswith(str(DOCS_DIR.resolve())):
                self.send_error(403)
                return
            self.send_file(target)
        elif parsed.path.startswith("/static/"):
            target = (STATIC_DIR / parsed.path.removeprefix("/static/")).resolve()
            if not str(target).startswith(str(STATIC_DIR.resolve())):
                self.send_error(403)
                return
            self.send_file(target)
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/ask":
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            question = str(payload.get("question", "")).strip()
            if not question:
                self.send_json({"error": "问题不能为空。"}, 400)
                return
            self.send_json(answer_question(question))
            return

        if parsed.path == "/api/ask-with-files":
            ensure_dirs()
            QUESTION_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
            form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={"REQUEST_METHOD": "POST"})
            question = str(form.getfirst("question", "")).strip()
            files = form["files"] if "files" in form else []
            if not isinstance(files, list):
                files = [files]
            attachments = []
            for field in files:
                if not getattr(field, "filename", None):
                    continue
                filename = safe_filename(field.filename)
                target = QUESTION_UPLOAD_DIR / filename
                counter = 1
                while target.exists():
                    target = QUESTION_UPLOAD_DIR / f"{Path(filename).stem}_{counter}{Path(filename).suffix}"
                    counter += 1
                target.write_bytes(field.file.read())
                suffix = target.suffix.lower()
                if suffix in IMAGE_SUFFIXES:
                    attachments.append({"name": target.name, "path": str(target), "kind": "image"})
                    continue
                extracted, warning = extract_document(target)
                attachments.append({
                    "name": target.name,
                    "path": str(target),
                    "kind": "document",
                    "text": extracted,
                    "warning": warning if warning else (None if extracted else "该附件没有提取到可用文字。"),
                })
            if not question and not attachments:
                self.send_json({"error": "问题或附件不能为空。"}, 400)
                return
            self.send_json(answer_question_with_attachments(question or "请分析我上传的附件", attachments))
            return
        if parsed.path == "/api/ingest":
            self.send_json(ingest_default_locations())
            return

        if parsed.path == "/api/crawl-official":
            self.send_json(crawl_official_policies())
            return

        if parsed.path == "/api/upload":
            ensure_dirs()
            form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={"REQUEST_METHOD": "POST"})
            files = form["files"] if "files" in form else []
            if not isinstance(files, list):
                files = [files]
            saved_paths = []
            for field in files:
                if not getattr(field, "filename", None):
                    continue
                filename = safe_filename(field.filename)
                target = UPLOAD_DIR / filename
                counter = 1
                while target.exists():
                    target = UPLOAD_DIR / f"{Path(filename).stem}_{counter}{Path(filename).suffix}"
                    counter += 1
                target.write_bytes(field.file.read())
                saved_paths.append(target)
            report = ingest_paths(saved_paths)
            self.send_json({"saved": [path.name for path in saved_paths], "ingest": report, "status": status()})
            return

        self.send_error(404)


def main() -> None:
    ensure_dirs()
    ingest_default_locations()
    server = ThreadingHTTPServer((HOST, PORT), AgentHandler)
    print(f"苏大制度政策 Agent 已启动：http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()






