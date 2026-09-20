#!/usr/bin/env python3
"""Loopback HTTP transport for one revisioned article document."""
from __future__ import annotations

import argparse
import functools
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlparse

# Preserve the public helpers previously imported from this CLI module.
from workbench_document import (
    WorkbenchDocument, RevisionConflict, RecoveryRequired, ManifestRefreshRequest,
    SAVE_ENDPOINT, ASSET_ENDPOINT, STATUS_ENDPOINT, MAX_REQUEST_BYTES, MAX_ASSET_REQUEST_BYTES,
    inspect_visuals, validate_pasted_image, is_relative_to, is_allowed_host,
    restore_visual_placeholders, replace_default_workbench_state, load_manifest_refresh_metadata,
    builder, base64, subprocess,
)

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Serve one WeChat article workbench locally and persist browser edits back to its files."
    )
    parser.add_argument("html", type=Path, help="Generated workbench HTML file.")
    parser.add_argument("--workspace", type=Path, help="Workspace root served over HTTP.")
    parser.add_argument("--host", default="127.0.0.1", choices=("127.0.0.1", "localhost"))
    parser.add_argument("--port", type=int, default=0, help="Local port; 0 chooses a free port.")
    return parser.parse_args()


def make_handler(document: WorkbenchDocument):
    class WorkbenchHandler(SimpleHTTPRequestHandler):
        def end_headers(self) -> None:
            request_path = urlparse(self.path).path
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; base-uri 'none'; object-src 'none'; "
                "frame-ancestors 'none'; form-action 'none'; connect-src 'self'; "
                "img-src 'self' data: blob: https:; font-src 'self' data:; "
                "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'",
            )
            self.send_header(
                "Permissions-Policy",
                "camera=(), microphone=(), geolocation=(), payment=()",
            )
            if request_path not in {STATUS_ENDPOINT, SAVE_ENDPOINT, ASSET_ENDPOINT}:
                suffix = Path(request_path).suffix.lower()
                if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg", ".js"}:
                    self.send_header("Cache-Control", "private, max-age=60")
                else:
                    self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def has_valid_host(self) -> bool:
            return is_allowed_host(
                self.headers.get("Host", ""),
                int(self.server.server_address[1]),
            )

        def send_json(self, status: int, payload: dict[str, Any]) -> None:
            encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(encoded)

        def serve_document_or_asset(self, *, head: bool = False) -> None:
            if not self.has_valid_host():
                self.send_json(403, {"error": "invalid host"})
                return
            request_path = unquote(urlparse(self.path).path)
            if request_path == STATUS_ENDPOINT:
                self.send_json(200, document.status())
                return
            target = Path(self.translate_path(self.path)).resolve()
            if target == document.html_path:
                body = document.served_html()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if not head:
                    self.wfile.write(body)
                return
            allowed = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg", ".js"}
            if not is_relative_to(target, document.workspace) or not target.is_file() or target.suffix.lower() not in allowed:
                self.send_json(404, {"error": "this server only edits its bound article"})
                return
            if head:
                super().do_HEAD()
            else:
                super().do_GET()

        def do_GET(self) -> None:
            self.serve_document_or_asset()

        def do_HEAD(self) -> None:
            if not self.has_valid_host():
                self.send_response(403)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.serve_document_or_asset(head=True)

        def do_POST(self) -> None:
            request_path = urlparse(self.path).path
            if request_path not in {SAVE_ENDPOINT, ASSET_ENDPOINT}:
                self.send_json(404, {"saved": False, "error": "not found"})
                return
            try:
                if not self.has_valid_host(): self.send_json(403,{"saved":False,"error":"invalid host"}); return
                origin=self.headers.get('Origin')
                expected=('http://127.0.0.1:'+str(self.server.server_address[1]),'http://localhost:'+str(self.server.server_address[1]))
                if origin not in expected: self.send_json(403,{"saved":False,"error":"invalid origin"}); return
                if self.headers.get('X-Workbench-Token') != document.token: self.send_json(403,{"saved":False,"error":"invalid token"}); return
                if self.headers.get('Content-Type','').split(';')[0].strip() != 'application/json': self.send_json(415,{"saved":False,"error":"content type"}); return
                length = int(self.headers.get("Content-Length", "0"))
                request_limit = MAX_ASSET_REQUEST_BYTES if request_path == ASSET_ENDPOINT else MAX_REQUEST_BYTES
                if length <= 0 or length > request_limit:
                    raise ValueError("invalid request size")
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("request body must be an object")
                if payload.get("documentId") != document.document_id:
                    raise ValueError("request belongs to a different article; reopen the current workbench")
                if request_path == SAVE_ENDPOINT and ("baseRevision" not in payload or "baseFingerprint" not in payload):
                    raise ValueError("save requires the original article revision and fingerprint")
                if request_path == ASSET_ENDPOINT:
                    self.send_json(200, document.upload_asset(payload))
                else:
                    self.send_json(200, document.save(payload))
            except RevisionConflict as exc:
                self.send_json(409, exc.current_status)
            except RecoveryRequired as exc:
                payload = dict(exc.current_status)
                payload.update({"saved": False, "error": "transaction recovery is required"})
                self.send_json(423, payload)
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
