#!/usr/bin/env python3
from __future__ import annotations

import argparse
import functools
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import secrets
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import build_wechat_article_workbench as builder


SAVE_ENDPOINT = "/__wechat_workbench/save"
STATUS_ENDPOINT = "/__wechat_workbench/status"
MAX_REQUEST_BYTES = 8 * 1024 * 1024
SCRIPT_DIR = Path(__file__).resolve().parent
MAKE_MANIFEST = SCRIPT_DIR / "make_wechat_publish_manifest.py"
DEFAULT_ENV_FILE = SCRIPT_DIR.parent / ".env"
DEFAULT_STATE_RE = re.compile(r"const DEFAULT_WORKBENCH_STATE = .*?;", re.S)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Serve one WeChat article workbench locally and persist browser edits back to its files."
    )
    parser.add_argument("html", type=Path, help="Generated workbench HTML file.")
    parser.add_argument("--workspace", type=Path, help="Workspace root served over HTTP.")
    parser.add_argument("--host", default="127.0.0.1", choices=("127.0.0.1", "localhost"))
    parser.add_argument("--port", type=int, default=0, help="Local port; 0 chooses a free port.")
    return parser.parse_args()


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(text)
        temp_path = Path(handle.name)
    os.replace(temp_path, path)


def restore_visual_placeholders(markdown: str, job: dict[str, Any], html_path: Path) -> str:
    restored = markdown
    html_path = html_path.resolve()
    for name, spec in (job.get("visuals") or {}).items():
        if not isinstance(spec, dict) or not str(spec.get("path", "")).strip():
            continue
        raw_path = Path(str(spec["path"]))
        asset_path = (raw_path if raw_path.is_absolute() else (html_path.parent / raw_path)).resolve()
        relative_path = Path(os.path.relpath(asset_path, start=html_path.parent)).as_posix()
        candidates = {relative_path, str(asset_path), asset_path.as_uri()}
        placeholder = f"{{{{visual:{name}}}}}"
        for candidate in candidates:
            restored = restored.replace(f"]({candidate})", f"]({placeholder})")
            restored = restored.replace(f"](<{candidate}>)", f"]({placeholder})")
    return restored


def replace_default_workbench_state(html_text: str, state: dict[str, str]) -> str:
    payload = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
    replacement = f"const DEFAULT_WORKBENCH_STATE = {payload};"
    if DEFAULT_STATE_RE.search(html_text):
        return DEFAULT_STATE_RE.sub(replacement, html_text, count=1)
    return html_text


class RevisionConflict(Exception):
    def __init__(self, current_status): self.current_status=current_status

class WorkbenchDocument:
    def __init__(self, html_path: Path, workspace: Path):
        self.workspace = workspace.resolve()
        self.html_path = html_path.resolve()
        if not is_relative_to(self.html_path, self.workspace):
            raise ValueError("Workbench HTML must be inside the workspace.")
        if not self.html_path.exists():
            raise ValueError(f"Workbench HTML does not exist: {self.html_path}")
        self.markdown_path = self.html_path.with_suffix(".md")
        self.job_path = self.html_path.with_suffix(".job.json")
        self.manifest_path = self.html_path.with_suffix(".publish-manifest.json")
        self._lock = threading.Lock()
        self.sidecar = self.html_path.with_suffix('.workbench-state.json')
        self.token = secrets.token_urlsafe(32)
        self._state = self._load_state()
        self._manifest_thread = None

    def _load_state(self):
        if self.sidecar.exists():
            try: return json.loads(self.sidecar.read_text())
            except Exception: return {"recovery_required":True,"coreRevision":0}
        return {"coreRevision":0,"manifest":{"state":"not_configured","targetRevision":0},"assets":{"state":"ready","staleVisuals":[],"missingVisuals":[]}}

    def status(self):
        out=dict(self._state); out.setdefault('coreRevision',0); out['available']=True; out['token']=self.token
        return out

    def _persist(self): atomic_write_text(self.sidecar, json.dumps(self._state,ensure_ascii=False,indent=2))

    def _refresh_manifest(self) -> tuple[bool, str]:
        if not self.job_path.exists() or not self.manifest_path.exists() or not DEFAULT_ENV_FILE.exists():
            with self._lock:
                self._state['manifest']={'state':'not_configured','targetRevision':self._state.get('coreRevision',0)}; self._persist()
            return False, "not-configured"
        command = [
            sys.executable,
            str(MAKE_MANIFEST),
            str(self.job_path),
            str(self.manifest_path),
            "--workbench-html",
            str(self.html_path),
            "--env-file",
            str(DEFAULT_ENV_FILE),
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            with self._lock:
                self._state['manifest']={'state':'ready','targetRevision':self._state.get('coreRevision',0)}; self._persist()
            return True, "ok"
        message = (result.stderr or result.stdout or "manifest refresh failed").strip().splitlines()[-1]
        with self._lock:
            self._state['manifest']={'state':'failed','targetRevision':self._state.get('coreRevision',0),'error':message[:240]}; self._persist()
        return False, message[:240]

    def save(self, payload: dict[str, Any]) -> dict[str, Any]:
        markdown = payload.get("markdown")
        if not isinstance(markdown, str):
            raise ValueError("markdown must be a string")
        if len(markdown.encode("utf-8")) > MAX_REQUEST_BYTES:
            raise ValueError("markdown is too large")
        state = {
            "themeColor": str(payload.get("themeColor") or "#17b394"),
            "fontSize": str(payload.get("fontSize") or "16"),
            "fontFamily": str(payload.get("fontFamily") or "-apple-system, BlinkMacSystemFont, sans-serif"),
        }

        with self._lock:
            base = payload.get('baseRevision', self._state.get('coreRevision',0))
            if int(base) != int(self._state.get('coreRevision',0)): raise RevisionConflict(self.status())
            html_text = self.html_path.read_text(encoding="utf-8")
            try:
                updated_html = builder.replace_bootstrap(html_text, {"markdown": markdown, "workbenchState": state})
                if updated_html == html_text:
                    updated_html = builder.replace_default_markdown(html_text, markdown)
                    updated_html = replace_default_workbench_state(updated_html, state)
            except (ValueError, json.JSONDecodeError):
                updated_html = builder.replace_default_markdown(html_text, markdown)
                updated_html = replace_default_workbench_state(updated_html, state)

            source_markdown = markdown
            job: dict[str, Any] | None = None
            if self.job_path.exists():
                job = json.loads(self.job_path.read_text(encoding="utf-8"))
                source_markdown = restore_visual_placeholders(markdown, job, self.html_path)
                job["article_markdown"] = source_markdown
                job["theme_color"] = state["themeColor"]

            atomic_write_text(self.html_path, updated_html)
            if job is not None:
                atomic_write_text(self.markdown_path, source_markdown)
                atomic_write_text(self.job_path, json.dumps(job, ensure_ascii=False, indent=2) + "\n")

            rev=int(self._state.get('coreRevision',0))+1
            self._state.update({'coreRevision':rev,'manifest':{'state':'pending','targetRevision':rev},'assets':self._state.get('assets',{'state':'ready','staleVisuals':[],'missingVisuals':[]})})
            self._persist()
            self._manifest_thread=threading.Thread(target=self._refresh_manifest,daemon=True); self._manifest_thread.start()

        return {
            "saved": True,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "html": str(self.html_path),
            "markdown": str(self.markdown_path) if job is not None else "",
            "job": str(self.job_path) if job is not None else "",
            "revision": rev, "clientMutationId": payload.get('clientMutationId'),
            "manifest": self._state['manifest'], "assets": self._state['assets'],
        }

    def close(self):
        if self._manifest_thread and self._manifest_thread.is_alive(): self._manifest_thread.join(timeout=1)


def make_handler(document: WorkbenchDocument):
    class WorkbenchHandler(SimpleHTTPRequestHandler):
        def send_json(self, status: int, payload: dict[str, Any]) -> None:
            encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self) -> None:
            if urlparse(self.path).path == STATUS_ENDPOINT:
                self.send_json(200, document.status())
                return
            super().do_GET()

        def do_POST(self) -> None:
            if urlparse(self.path).path != SAVE_ENDPOINT:
                self.send_json(404, {"saved": False, "error": "not found"})
                return
            try:
                host=self.headers.get('Host','')
                if not (host.startswith('127.0.0.1:') or host.startswith('localhost:')): self.send_json(403,{"saved":False,"error":"invalid host"}); return
                if self.headers.get('Origin') and self.headers.get('Origin') not in ('http://127.0.0.1:'+str(self.server.server_address[1]),'http://localhost:'+str(self.server.server_address[1])): self.send_json(403,{"saved":False,"error":"invalid origin"}); return
                if self.headers.get('X-Workbench-Token') != document.token: self.send_json(403,{"saved":False,"error":"invalid token"}); return
                if self.headers.get('Content-Type','').split(';')[0].strip() != 'application/json': self.send_json(415,{"saved":False,"error":"content type"}); return
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > MAX_REQUEST_BYTES:
                    raise ValueError("invalid request size")
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("request body must be an object")
                self.send_json(200, document.save(payload))
            except RevisionConflict as exc:
                self.send_json(409, exc.current_status)
            except (ValueError, json.JSONDecodeError) as exc:
                self.send_json(400, {"saved": False, "error": str(exc)})
            except Exception as exc:
                self.send_json(500, {"saved": False, "error": f"save failed: {type(exc).__name__}"})

        def log_message(self, _format: str, *_args: Any) -> None:
            return

    return WorkbenchHandler


def main() -> None:
    args = parse_args()
    html_path = args.html.resolve()
    workspace = (args.workspace or html_path.parent.parent).resolve()
    document = WorkbenchDocument(html_path=html_path, workspace=workspace)
    handler = functools.partial(make_handler(document), directory=str(workspace))
    server = ThreadingHTTPServer((args.host, args.port), handler)
    port = int(server.server_address[1])
    relative_url = quote(document.html_path.relative_to(workspace).as_posix(), safe="/")
    url = f"http://{args.host}:{port}/{relative_url}"
    print(f"WORKBENCH_URL={url}", flush=True)
    print(f"HTML_PATH={document.html_path}", flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
