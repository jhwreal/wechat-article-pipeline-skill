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
import hashlib
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

class ManifestRefreshRequest:
    __slots__ = ('revision','job_snapshot','manifest_path','article_slug','env_file','account_selector','source_state','_locked')
    def __init__(self, revision, job_snapshot, manifest_path, article_slug='', env_file=None, account_selector=None, source_state=None):
        object.__setattr__(self,'revision',revision); object.__setattr__(self,'job_snapshot',job_snapshot); object.__setattr__(self,'manifest_path',manifest_path); object.__setattr__(self,'article_slug',article_slug); object.__setattr__(self,'env_file',env_file); object.__setattr__(self,'account_selector',account_selector); object.__setattr__(self,'source_state',source_state); object.__setattr__(self,'_locked',True)
    def __setattr__(self, n, v):
        if getattr(self,'_locked',False): raise AttributeError('immutable')
        object.__setattr__(self,n,v)

def inspect_visuals(markdown, visuals, *, job_dir, baselines=None):
    baselines = baselines or {}; stale=[]; missing=[]; updated={}
    for name, spec in (visuals or {}).items():
        path = Path(str(spec.get('path',''))); path = path if path.is_absolute() else Path(job_dir)/path
        # Fingerprint the source block associated with this visual, so a
        # style-only or unrelated paragraph edit does not stale every asset.
        marker = f"visual:{name}"
        block = ""
        for line in (markdown or '').splitlines():
            if marker in line or str(spec.get('path','')) in line:
                block = line.strip(); break
        src = hashlib.sha256((block or marker).encode()).hexdigest()
        asset = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
        old = baselines.get(name, {})
        if asset is None: missing.append(name)
        elif old.get('sourceFingerprint') and old.get('sourceFingerprint') != src and old.get('assetFingerprint') == asset: stale.append(name)
        # A regenerated asset resolves a prior stale/missing slot.
        updated[name]={'sourceFingerprint':src,'assetFingerprint':asset}
    state='missing' if missing else ('stale' if stale else 'ready')
    return {'state':state,'staleVisuals':stale,'missingVisuals':missing,'baselines':updated}


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
        self.support_dir = self.html_path.parent / "support"
        self.sidecar = self.support_dir / (self.html_path.stem + '.workbench-state.json')
        self.journal = self.support_dir / (self.html_path.stem + '.transaction.json')
        self.token = secrets.token_urlsafe(32)
        self._state = self._load_state()
        self._manifest_thread = None
        self._manifest_pending = None

    def _load_state(self):
        if self.journal.exists():
            try:
                j=json.loads(self.journal.read_text()); entries=j.get('files',[])
                if isinstance(entries,dict): entries=[{'target':p,'staged':p,'hash':h} for p,h in entries.items()]
                if not all(Path(e['staged']).exists() and hashlib.sha256(Path(e['staged']).read_bytes()).hexdigest()==e['hash'] for e in entries):
                    return {"recovery_required":True,"coreRevision":0}
                for e in entries: os.replace(e['staged'], e['target'])
                state = json.loads(self.sidecar.read_text()) if self.sidecar.exists() else {}
                state['coreRevision'] = int(j.get('revision', state.get('coreRevision',0)))
                atomic_write_text(self.sidecar, json.dumps(state, ensure_ascii=False, indent=2))
                self.journal.unlink()
                return state
            except Exception: return {"recovery_required":True,"coreRevision":0}
        if self.sidecar.exists():
            try: return json.loads(self.sidecar.read_text())
            except Exception: return {"recovery_required":True,"coreRevision":0}
        return {"coreRevision":0,"manifest":{"state":"not_configured","targetRevision":0},"assets":{"state":"ready","staleVisuals":[],"missingVisuals":[]}}

    def status(self):
        out=dict(self._state); out.setdefault('coreRevision',0); out['available']=True; out['token']=self.token
        return out

    def _persist(self): atomic_write_text(self.sidecar, json.dumps(self._state,ensure_ascii=False,indent=2))

    def _refresh_manifest(self, req: ManifestRefreshRequest) -> tuple[bool, str]:
        if not req.job_snapshot.exists() or not req.env_file or not req.env_file.exists():
            with self._lock:
                self._state['manifest']={'state':'not_configured','targetRevision':self._state.get('coreRevision',0)}; self._persist()
            return False, "not-configured"
        # Render into a revision-specific candidate; never let an old worker
        # overwrite the public manifest while a newer save is committed.
        candidate = req.manifest_path.with_name(req.manifest_path.name + f".r{req.revision}.candidate")
        command = [
            sys.executable,
            str(MAKE_MANIFEST),
            str(req.job_snapshot), str(candidate),
            "--workbench-html",
            str(self.html_path),
            "--env-file",
            str(req.env_file),
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            with self._lock:
                if req.revision != self._state.get('coreRevision'):
                    candidate.unlink(missing_ok=True)
                    return False, 'stale-candidate'
                try:
                    manifest = json.loads(candidate.read_text(encoding='utf-8'))
                    if req.source_state:
                        ss = dict(req.source_state)
                        ss['manifest_revision'] = req.revision
                        manifest['source_state'] = ss
                        atomic_write_text(candidate, json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
                    os.replace(candidate, req.manifest_path)
                except Exception as exc:
                    candidate.unlink(missing_ok=True)
                    self._state['manifest']={'state':'failed','targetRevision':req.revision,'error':str(exc)[:240]}; self._persist()
                    return False, 'candidate-invalid'
                self._state['manifest']={'state':'ready','targetRevision':req.revision}; self._persist()
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
                self._state['assets'] = inspect_visuals(source_markdown, job.get('visuals',{}), job_dir=self.job_path.parent, baselines=self._state.get('assets',{}).get('baselines',{}))
                self._state['source_state'] = {'core_revision': int(self._state.get('coreRevision',0))+1, 'asset_state': self._state['assets']['state'], 'stale_visuals': self._state['assets'].get('staleVisuals',[]), 'missing_visuals': self._state['assets'].get('missingVisuals',[])}

            files={str(self.html_path):updated_html}
            if job is not None:
                files[str(self.markdown_path)] = source_markdown
                files[str(self.job_path)] = json.dumps(job, ensure_ascii=False, indent=2) + "\n"
            self.support_dir.mkdir(parents=True, exist_ok=True)
            rev=int(self._state.get('coreRevision',0))+1
            txn_dir = self.support_dir / '.txn' / str(rev); txn_dir.mkdir(parents=True, exist_ok=True)
            entries=[]
            for p,v in files.items():
                staged=txn_dir / Path(p).name; atomic_write_text(staged,v)
                with staged.open('rb') as fh: os.fsync(fh.fileno())
                entries.append({'target':p,'staged':str(staged),'hash':hashlib.sha256(v.encode()).hexdigest()})
            atomic_write_text(self.journal, json.dumps({'revision':rev,'files':entries}))
            for e in entries: os.replace(e['staged'], e['target'])
            self._state.update({'coreRevision':rev,'manifest':{'state':'pending','targetRevision':rev},'assets':self._state.get('assets',{'state':'ready','staleVisuals':[],'missingVisuals':[]})})
            self._persist()
            snap=self.support_dir / f"{self.html_path.stem}.job.r{rev}.json"; atomic_write_text(snap, files.get(str(self.job_path), self.job_path.read_text() if self.job_path.exists() else "{}"))
            req=ManifestRefreshRequest(rev,snap,self.manifest_path, self.html_path.stem, DEFAULT_ENV_FILE, source_state=self._state.get('source_state'))
            self._manifest_pending = req
            if not self._manifest_thread or not self._manifest_thread.is_alive():
                def worker():
                    while True:
                        with self._lock:
                            current = self._manifest_pending; self._manifest_pending = None
                        if current is None: break
                        self._refresh_manifest(current)
                self._manifest_thread=threading.Thread(target=worker,daemon=True); self._manifest_thread.start()
            self.journal.unlink(missing_ok=True)

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
                origin=self.headers.get('Origin')
                expected=('http://127.0.0.1:'+str(self.server.server_address[1]),'http://localhost:'+str(self.server.server_address[1]))
                if origin not in expected: self.send_json(403,{"saved":False,"error":"invalid origin"}); return
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
        document.close()
        server.server_close()


if __name__ == "__main__":
    main()
