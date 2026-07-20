#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import binascii
import functools
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import build_wechat_article_workbench as builder
from atomic_files import atomic_replace, atomic_write_text, fsync_directory


SAVE_ENDPOINT = "/__wechat_workbench/save"
STATUS_ENDPOINT = "/__wechat_workbench/status"
MAX_REQUEST_BYTES = 8 * 1024 * 1024
SCRIPT_DIR = Path(__file__).resolve().parent
MAKE_MANIFEST = SCRIPT_DIR / "make_wechat_publish_manifest.py"
DEFAULT_ENV_FILE = SCRIPT_DIR.parent / ".env"
DEFAULT_STATE_RE = re.compile(r"const DEFAULT_WORKBENCH_STATE = .*?;", re.S)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SNAPSHOT_RETENTION = 5
MANIFEST_METADATA_READ_CHARS = 64 * 1024
COMPACT_MANIFEST_HEADER_RE = re.compile(
    r'\A\s*\{\s*"schema_version"\s*:\s*\d+\s*,\s*"workbench_refresh"\s*:',
    re.S,
)


@dataclass(frozen=True)
class ManifestRefreshRequest:
    revision: int
    job_snapshot: Path
    manifest_path: Path
    article_slug: str = ""
    env_file: Path | None = None
    account_selector: str | None = None
    author: str = ""
    preview_account: str = ""
    source_state: dict[str, Any] | None = None


def _visual_source_contexts(markdown: str) -> dict[str, str]:
    matches = list(builder.PLACEHOLDER_RE.finditer(markdown or ""))
    contexts: dict[str, str] = {}
    for index, match in enumerate(matches):
        name = match.group(1)
        previous_end = matches[index - 1].end() if index else 0
        next_start = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        if name == "cover":
            source = markdown[: match.start()] + "\n" + markdown[match.end() : next_start]
        else:
            source = markdown[previous_end : match.start()]
        source = builder.PLACEHOLDER_RE.sub(" ", source)
        source = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", source)
        contexts[name] = re.sub(r"\s+", " ", source).strip()
    return contexts


def _visual_asset_fingerprint(spec: Any, job_dir: Path) -> str | None:
    if not isinstance(spec, dict):
        return None
    try:
        if str(spec.get("path", "")).strip():
            raw_path = Path(str(spec["path"]))
            path = raw_path if raw_path.is_absolute() else (job_dir / raw_path).resolve()
            return file_sha256(path) if path.is_file() else None
        if str(spec.get("data_uri", "")).strip():
            payload, _mime_type = builder.decode_data_uri(str(spec["data_uri"]))
            return hashlib.sha256(payload).hexdigest()
        if str(spec.get("base64", "")).strip():
            payload = base64.b64decode(str(spec["base64"]), validate=True)
            return hashlib.sha256(payload).hexdigest() if payload else None
        if str(spec.get("url", "")).strip():
            return hashlib.sha256(("url:" + str(spec["url"]).strip()).encode("utf-8")).hexdigest()
    except (OSError, ValueError, TypeError, binascii.Error):
        return None
    return None


def inspect_visuals(markdown, visuals, *, job_dir, baselines=None):
    baselines = baselines if isinstance(baselines, dict) else {}
    stale: list[str] = []
    missing: list[str] = []
    updated: dict[str, dict[str, str | None]] = {}
    contexts = _visual_source_contexts(str(markdown or ""))
    if not isinstance(visuals, dict):
        return {
            "state": "failed",
            "staleVisuals": [],
            "missingVisuals": [],
            "baselines": {},
            "error": "job visuals must be an object",
        }
    article_fallback = re.sub(r"\s+", " ", str(markdown or "")).strip()
    for raw_name, spec in visuals.items():
        name = str(raw_name)
        source_context = contexts.get(name)
        if source_context is None and name == "cover":
            source_context = article_fallback[:800]
        source = source_context or f"visual:{name}"
        source_fingerprint = hashlib.sha256(source.encode("utf-8")).hexdigest()
        asset_fingerprint = _visual_asset_fingerprint(spec, Path(job_dir))
        old = baselines.get(name, {})
        old = old if isinstance(old, dict) else {}
        if asset_fingerprint is None:
            missing.append(name)
            if old.get("sourceFingerprint") or old.get("assetFingerprint"):
                updated[name] = {
                    "sourceFingerprint": old.get("sourceFingerprint"),
                    "assetFingerprint": old.get("assetFingerprint"),
                }
                continue
        elif (
            old.get("sourceFingerprint")
            and old.get("sourceFingerprint") != source_fingerprint
            and old.get("assetFingerprint") == asset_fingerprint
        ):
            stale.append(name)
            updated[name] = {
                "sourceFingerprint": old.get("sourceFingerprint"),
                "assetFingerprint": old.get("assetFingerprint"),
            }
            continue
        updated[name] = {
            "sourceFingerprint": source_fingerprint,
            "assetFingerprint": asset_fingerprint,
        }
    state = "missing" if missing else ("stale" if stale else "ready")
    return {
        "state": state,
        "staleVisuals": stale,
        "missingVisuals": missing,
        "baselines": updated,
    }


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
    def __init__(self, current_status: dict[str, Any]):
        self.current_status = current_status


class RecoveryRequired(Exception):
    def __init__(self, current_status: dict[str, Any]):
        self.current_status = current_status


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def is_allowed_host(host: str, port: int) -> bool:
    normalized = host.strip().lower()
    return normalized in (f"localhost:{port}", f"127.0.0.1:{port}")


def manifest_refresh_metadata(manifest: dict[str, Any]) -> dict[str, Any]:
    compact = manifest.get("workbench_refresh")
    source = compact if isinstance(compact, dict) else manifest
    metadata: dict[str, Any] = {}
    for key in ("article_slug", "author", "env_file"):
        if key in source:
            metadata[key] = source[key]
    account = source.get("account")
    if isinstance(account, dict):
        metadata["account"] = {
            key: account[key]
            for key in ("selector", "alias", "name")
            if key in account
        }
    preview = source.get("preview")
    if isinstance(preview, dict) and "account" in preview:
        metadata["preview"] = {"account": preview["account"]}
    return metadata


def load_manifest_refresh_metadata(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        prefix = handle.read(MANIFEST_METADATA_READ_CHARS)
    match = COMPACT_MANIFEST_HEADER_RE.match(prefix)
    if match:
        try:
            compact, _end = json.JSONDecoder().raw_decode(prefix[match.end() :].lstrip())
        except json.JSONDecodeError:
            compact = None
        if isinstance(compact, dict):
            return manifest_refresh_metadata({"workbench_refresh": compact})
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("publish manifest must be a JSON object")
    return manifest_refresh_metadata(manifest)


class WorkbenchDocument:
    def __init__(self, html_path: Path, workspace: Path):
        self.workspace = workspace.resolve()
        self.html_path = html_path.resolve()
        if not is_relative_to(self.html_path, self.workspace):
            raise ValueError("Workbench HTML must be inside the workspace.")
        if not self.html_path.exists():
            raise ValueError(f"Workbench HTML does not exist: {self.html_path}")
        self.markdown_path = self.html_path.with_suffix(".md").resolve()
        self.job_path = self.html_path.with_suffix(".job.json").resolve()
        self.manifest_path = self.html_path.with_suffix(".publish-manifest.json").resolve()
        for path in (self.markdown_path, self.job_path, self.manifest_path):
            if not is_relative_to(path, self.workspace):
                raise ValueError(f"Workbench companion path escapes the workspace: {path}")
        self.support_dir = (self.html_path.parent / "support").resolve()
        if not is_relative_to(self.support_dir, self.workspace):
            raise ValueError("Workbench support directory must be inside the workspace.")
        self.transaction_root = (self.support_dir / ".txn").resolve()
        if not is_relative_to(self.transaction_root, self.support_dir):
            raise ValueError("Workbench transaction directory must be inside support/.")
        self.sidecar = self.support_dir / (self.html_path.stem + ".workbench-state.json")
        self.journal = self.support_dir / (self.html_path.stem + ".transaction.json")
        self._allowed_transaction_targets = frozenset(
            (self.html_path, self.markdown_path, self.job_path)
        )
        self._manifest_enabled = self.manifest_path.exists()
        self._manifest_meta: dict[str, Any] = {}
        if self._manifest_enabled:
            try:
                self._manifest_meta = load_manifest_refresh_metadata(self.manifest_path)
            except (OSError, ValueError, json.JSONDecodeError):
                self._manifest_meta = {}
        self._lock = threading.Lock()
        self.token = secrets.token_urlsafe(32)
        self._manifest_thread = None
        self._manifest_pending = None
        self._closed = False
        self._state = self._load_state()
        self._prune_job_snapshots()
        self._refresh_assets_from_job()
        self._resume_pending_manifest_refresh()

    def _default_state(self) -> dict[str, Any]:
        manifest_state = "ready" if self._manifest_enabled else "not_configured"
        return {
            "coreRevision": 0,
            "manifest": {"state": manifest_state, "targetRevision": 0},
            "assets": {
                "state": "ready",
                "staleVisuals": [],
                "missingVisuals": [],
                "baselines": {},
            },
        }

    def _normalize_state(self, state: dict[str, Any]) -> dict[str, Any]:
        normalized = self._default_state()
        normalized.update(state)
        core_revision = normalized.get("coreRevision", 0)
        if isinstance(core_revision, bool):
            raise ValueError("coreRevision must be a non-negative integer")
        normalized["coreRevision"] = int(core_revision)
        if normalized["coreRevision"] < 0:
            raise ValueError("coreRevision must be a non-negative integer")

        manifest = normalized.get("manifest")
        manifest = dict(manifest) if isinstance(manifest, dict) else {}
        manifest["state"] = str(
            manifest.get("state")
            or ("ready" if self._manifest_enabled else "not_configured")
        )
        if not self._manifest_enabled:
            manifest["state"] = "not_configured"
        try:
            manifest["targetRevision"] = int(
                manifest.get("targetRevision", normalized["coreRevision"])
            )
        except (TypeError, ValueError):
            manifest["targetRevision"] = normalized["coreRevision"]
        normalized["manifest"] = manifest

        assets = normalized.get("assets")
        assets = dict(assets) if isinstance(assets, dict) else {}
        assets["state"] = str(assets.get("state") or "ready")
        for key in ("staleVisuals", "missingVisuals"):
            values = assets.get(key, [])
            assets[key] = [str(value) for value in values] if isinstance(values, list) else []
        if not isinstance(assets.get("baselines"), dict):
            assets["baselines"] = {}
        normalized["assets"] = assets
        return normalized

    def _read_sidecar(self) -> dict[str, Any]:
        if not self.sidecar.exists():
            return self._default_state()
        data = json.loads(self.sidecar.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("workbench state must be a JSON object")
        return self._normalize_state(data)

    def _write_state(self, state: dict[str, Any]) -> None:
        atomic_write_text(
            self.sidecar,
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        )

    def _recovery_state(self, error: Exception | str) -> dict[str, Any]:
        try:
            state = self._read_sidecar()
        except (OSError, ValueError, json.JSONDecodeError):
            state = self._default_state()
        state["recovery_required"] = True
        state["recovery_error"] = str(error)[:300]
        return state

    def _validate_journal_entries(
        self, raw_entries: Any
    ) -> list[tuple[Path, Path, str]]:
        if not isinstance(raw_entries, list) or not raw_entries:
            raise ValueError("transaction journal has no file entries")
        validated: list[tuple[Path, Path, str]] = []
        seen_targets: set[Path] = set()
        for entry in raw_entries:
            if not isinstance(entry, dict):
                raise ValueError("transaction entry must be an object")
            if set(entry) != {"target", "staged", "hash"}:
                raise ValueError("transaction entry keys must be target/staged/hash")
            raw_target = entry.get("target")
            raw_staged = entry.get("staged")
            expected_hash = entry.get("hash")
            if not all(isinstance(value, str) for value in (raw_target, raw_staged, expected_hash)):
                raise ValueError("transaction entry fields must be strings")
            if not Path(raw_target).is_absolute() or not Path(raw_staged).is_absolute():
                raise ValueError("transaction paths must be absolute")
            target = Path(raw_target).resolve()
            staged = Path(raw_staged).resolve()
            if target not in self._allowed_transaction_targets:
                raise ValueError(f"transaction target is not allowed: {target}")
            if target in seen_targets:
                raise ValueError(f"duplicate transaction target: {target}")
            if not is_relative_to(staged, self.transaction_root) or staged == self.transaction_root:
                raise ValueError("staged transaction file escapes support/.txn")
            if staged.name != target.name:
                raise ValueError("staged transaction filename does not match its target")
            if not SHA256_RE.fullmatch(expected_hash):
                raise ValueError("transaction hash must be lowercase SHA-256")
            seen_targets.add(target)
            validated.append((target, staged, expected_hash))
        target_set = frozenset(seen_targets)
        valid_target_sets = {
            frozenset({self.html_path}),
            frozenset({self.html_path, self.markdown_path, self.job_path}),
        }
        if target_set not in valid_target_sets:
            raise ValueError("transaction target set is incomplete or unsupported")
        return validated

    def _cleanup_empty_transaction_dirs(self, paths: list[Path]) -> None:
        for path in sorted({item.parent for item in paths}, key=lambda item: len(item.parts), reverse=True):
            current = path
            while is_relative_to(current, self.transaction_root):
                try:
                    current.rmdir()
                except OSError:
                    break
                if current == self.transaction_root:
                    break
                current = current.parent

    def _load_state(self) -> dict[str, Any]:
        if not self.journal.exists():
            try:
                return self._read_sidecar()
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                return self._recovery_state(exc)

        try:
            journal_data = json.loads(self.journal.read_text(encoding="utf-8"))
            if not isinstance(journal_data, dict):
                raise ValueError("transaction journal must be a JSON object")
            if set(journal_data) != {"version", "revision", "files"}:
                raise ValueError("transaction journal keys must be version/revision/files")
            if journal_data.get("version") != 1:
                raise ValueError("unsupported transaction journal version")
            entries = self._validate_journal_entries(journal_data.get("files"))
            raw_revision = journal_data.get("revision")
            if isinstance(raw_revision, bool) or not isinstance(raw_revision, int):
                raise ValueError("transaction revision must be an integer")
            revision = raw_revision
            if revision < 1:
                raise ValueError("transaction revision must be positive")

            sidecar_valid = self.sidecar.exists()
            try:
                state = self._read_sidecar()
            except (OSError, ValueError, json.JSONDecodeError):
                state = self._default_state()
                sidecar_valid = False
            current_revision = int(state.get("coreRevision", 0))
            if sidecar_valid and revision not in {current_revision, current_revision + 1}:
                raise ValueError(
                    "transaction revision is stale or skips the current workbench revision"
                )
            if sidecar_valid and revision == current_revision:
                for target, _staged, expected_hash in entries:
                    if not target.is_file() or file_sha256(target) != expected_hash:
                        raise ValueError(
                            "recorded transaction revision does not match committed files"
                        )

            for target, staged, expected_hash in entries:
                if target.is_file() and file_sha256(target) == expected_hash:
                    if staged.exists():
                        staged.unlink()
                    continue
                if not staged.is_file():
                    raise ValueError(f"staged transaction file is missing: {staged}")
                if file_sha256(staged) != expected_hash:
                    raise ValueError(f"staged transaction hash mismatch: {staged}")
                atomic_replace(staged, target, preserve_target_mode=True)

            # The journal is authoritative for the committed file set and can
            # rebuild a damaged status sidecar after every file hash is checked.
            state["coreRevision"] = revision
            state.pop("recovery_required", None)
            state.pop("recovery_error", None)
            state["manifest"] = {
                "state": "pending" if self._manifest_enabled else "not_configured",
                "targetRevision": revision,
            }
            self._write_state(state)
            self.journal.unlink()
            fsync_directory(self.support_dir)
            self._cleanup_empty_transaction_dirs([entry[1] for entry in entries])
            return state
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            return self._recovery_state(exc)

    def status(self) -> dict[str, Any]:
        out = dict(self._state)
        out.setdefault("coreRevision", 0)
        out["available"] = True
        out["token"] = self.token
        return out

    def _persist(self) -> None:
        self._write_state(self._state)

    def _prune_job_snapshots(self) -> None:
        snapshots: list[tuple[int, Path]] = []
        pattern = re.compile(rf"^{re.escape(self.html_path.stem)}\.job\.r(\d+)\.json$")
        if not self.support_dir.exists():
            return
        for path in self.support_dir.glob(f"{self.html_path.stem}.job.r*.json"):
            match = pattern.fullmatch(path.name)
            if match:
                snapshots.append((int(match.group(1)), path))
        snapshots.sort(reverse=True)
        for _, path in snapshots[SNAPSHOT_RETENTION:]:
            path.unlink(missing_ok=True)

    def _refresh_assets_from_job(self) -> None:
        if self._state.get("recovery_required") or not self.job_path.is_file():
            return
        try:
            job = json.loads(self.job_path.read_text(encoding="utf-8"))
            if not isinstance(job, dict):
                raise ValueError("rendered job must be a JSON object")
            markdown = str(job.get("article_markdown", ""))
            assets = inspect_visuals(
                markdown,
                job.get("visuals", {}),
                job_dir=self.job_path.parent,
                baselines=(self._state.get("assets") or {}).get("baselines", {}),
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            assets = {
                "state": "failed",
                "staleVisuals": [],
                "missingVisuals": [],
                "baselines": {},
                "error": str(exc)[:240],
            }
        self._state["assets"] = assets
        source_state = self._state.get("source_state")
        source_state = dict(source_state) if isinstance(source_state, dict) else {}
        source_state.update(
            {
                "core_revision": int(self._state.get("coreRevision", 0)),
                "asset_state": assets["state"],
                "stale_visuals": assets.get("staleVisuals", []),
                "missing_visuals": assets.get("missingVisuals", []),
            }
        )
        self._state["source_state"] = source_state
        self._persist()

    def _manifest_snapshot_text(self, job_text: str) -> str:
        job = json.loads(job_text)
        if not isinstance(job, dict):
            raise ValueError("rendered job must be a JSON object")
        visuals = job.get("visuals", {}) or {}
        if not isinstance(visuals, dict):
            raise ValueError("rendered job visuals must be an object")
        for spec in visuals.values():
            if not isinstance(spec, dict) or not str(spec.get("path", "")).strip():
                continue
            raw_path = Path(str(spec["path"]))
            if not raw_path.is_absolute():
                spec["path"] = str((self.job_path.parent / raw_path).resolve())
        return json.dumps(job, ensure_ascii=False, indent=2) + "\n"

    def _manifest_refresh_request(
        self,
        revision: int,
        snapshot: Path,
        source_state: dict[str, Any] | None,
    ) -> ManifestRefreshRequest:
        meta = self._manifest_meta
        env_file = Path(str(meta.get("env_file") or DEFAULT_ENV_FILE)).expanduser()
        if not env_file.is_absolute():
            env_file = (self.html_path.parent / env_file).resolve()
        account_meta = meta.get("account") if isinstance(meta.get("account"), dict) else None
        account: str | None = None
        if account_meta is not None:
            account = str(account_meta.get("selector") or account_meta.get("alias") or "default")
        preview_meta = meta.get("preview") if isinstance(meta.get("preview"), dict) else {}
        return ManifestRefreshRequest(
            revision=revision,
            job_snapshot=snapshot,
            manifest_path=self.manifest_path,
            article_slug=str(meta.get("article_slug") or self.html_path.stem),
            env_file=env_file,
            account_selector=account,
            author=str(meta.get("author") or "").strip(),
            preview_account=str(preview_meta.get("account") or "").strip(),
            source_state=source_state,
        )

    def _resume_pending_manifest_refresh(self) -> None:
        manifest = self._state.get("manifest")
        if (
            not self._manifest_enabled
            or not isinstance(manifest, dict)
            or manifest.get("state") != "pending"
        ):
            return
        revision = int(self._state.get("coreRevision", 0))
        if revision < 1 or not self.job_path.is_file():
            manifest.update(
                {
                    "state": "failed",
                    "targetRevision": revision,
                    "error": "cannot resume manifest refresh without a committed rendered job",
                }
            )
            self._persist()
            return
        self.support_dir.mkdir(parents=True, exist_ok=True)
        snapshot = self.support_dir / f"{self.html_path.stem}.job.r{revision}.json"
        try:
            atomic_write_text(
                snapshot,
                self._manifest_snapshot_text(
                    self.job_path.read_text(encoding="utf-8")
                ),
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            manifest.update(
                {
                    "state": "failed",
                    "targetRevision": revision,
                    "error": f"cannot prepare manifest snapshot: {exc}"[:240],
                }
            )
            self._persist()
            return
        request = self._manifest_refresh_request(
            revision,
            snapshot,
            self._state.get("source_state"),
        )
        with self._lock:
            self._queue_manifest_refresh(request)

    def _refresh_manifest(self, req: ManifestRefreshRequest) -> tuple[bool, str]:
        if self._closed: return False, 'closed'
        if not req.job_snapshot.exists() or not req.env_file:
            with self._lock:
                if req.revision != self._state.get("coreRevision"):
                    return False, "stale-candidate"
                self._state['manifest']={
                    'state':'failed',
                    'targetRevision':req.revision,
                    'error':'manifest refresh input is missing',
                }
                self._persist()
            return False, "missing-input"
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
        if req.article_slug: command += ["--article-slug", req.article_slug]
        if req.account_selector: command += ["--account", req.account_selector]
        if req.author: command += ["--author", req.author]
        if req.preview_account: command += ["--preview-account", req.preview_account]
        if req.source_state:
            source_state = dict(req.source_state)
            source_state["manifest_revision"] = req.revision
            command += [
                "--source-state-json",
                json.dumps(source_state, ensure_ascii=False, separators=(",", ":")),
            ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            with self._lock:
                if self._closed or req.revision != self._state.get('coreRevision'):
                    candidate.unlink(missing_ok=True)
                    return False, 'stale-candidate'
                try:
                    if not candidate.is_file() or candidate.stat().st_size <= 0:
                        raise ValueError("manifest helper did not produce a candidate")
                    atomic_replace(
                        candidate,
                        req.manifest_path,
                        preserve_target_mode=True,
                    )
                except Exception as exc:
                    candidate.unlink(missing_ok=True)
                    self._state['manifest']={'state':'failed','targetRevision':req.revision,'error':str(exc)[:240]}; self._persist()
                    return False, 'candidate-invalid'
                self._state['manifest']={'state':'ready','targetRevision':req.revision}; self._persist()
            return True, "ok"
        candidate.unlink(missing_ok=True)
        message = (result.stderr or result.stdout or "manifest refresh failed").strip().splitlines()[-1]
        with self._lock:
            if req.revision != self._state.get("coreRevision"):
                return False, "stale-candidate"
            self._state['manifest']={'state':'failed','targetRevision':req.revision,'error':message[:240]}; self._persist()
        return False, message[:240]

    def _queue_manifest_refresh(self, request: ManifestRefreshRequest) -> None:
        """Queue the newest manifest refresh. Caller must hold ``self._lock``."""
        self._manifest_pending = request
        if self._manifest_thread is not None:
            return

        def worker() -> None:
            while True:
                with self._lock:
                    current = self._manifest_pending
                    self._manifest_pending = None
                    if current is None:
                        self._manifest_thread = None
                        break
                try:
                    self._refresh_manifest(current)
                except Exception as exc:
                    # A timeout or local process failure must not strand the
                    # worker handle and prevent future saves from retrying.
                    current.manifest_path.with_name(
                        current.manifest_path.name + f".r{current.revision}.candidate"
                    ).unlink(missing_ok=True)
                    with self._lock:
                        if (
                            not self._closed
                            and current.revision == self._state.get("coreRevision")
                        ):
                            self._state["manifest"] = {
                                "state": "failed",
                                "targetRevision": current.revision,
                                "error": f"{type(exc).__name__}: {exc}"[:240],
                            }
                            try:
                                self._persist()
                            except OSError:
                                pass
            self._prune_job_snapshots()

        self._manifest_thread = threading.Thread(target=worker, daemon=True)
        self._manifest_thread.start()

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
            if self._state.get("recovery_required"):
                raise RecoveryRequired(self.status())
            current_revision = int(self._state.get("coreRevision", 0))
            base = payload.get("baseRevision", current_revision)
            if int(base) != current_revision:
                raise RevisionConflict(self.status())
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
            assets = self._state.get("assets", self._default_state()["assets"])
            source_state = self._state.get("source_state")
            if self.job_path.exists():
                job = json.loads(self.job_path.read_text(encoding="utf-8"))
                if not isinstance(job, dict):
                    raise ValueError("rendered job must be a JSON object")
                source_markdown = restore_visual_placeholders(markdown, job, self.html_path)
                job["article_markdown"] = source_markdown
                job["theme_color"] = state["themeColor"]
                assets = inspect_visuals(
                    source_markdown,
                    job.get("visuals", {}),
                    job_dir=self.job_path.parent,
                    baselines=assets.get("baselines", {}),
                )
                source_state = {
                    "core_revision": current_revision + 1,
                    "asset_state": assets["state"],
                    "stale_visuals": assets.get("staleVisuals", []),
                    "missing_visuals": assets.get("missingVisuals", []),
                }

            files: dict[Path, str] = {self.html_path: updated_html}
            if job is not None:
                files[self.markdown_path] = source_markdown
                files[self.job_path] = json.dumps(job, ensure_ascii=False, indent=2) + "\n"
            self.support_dir.mkdir(parents=True, exist_ok=True)
            revision = current_revision + 1
            transaction_dir = (self.transaction_root / str(revision)).resolve()
            if not is_relative_to(transaction_dir, self.transaction_root):
                raise ValueError("transaction directory escapes support/.txn")
            transaction_dir.mkdir(parents=True, exist_ok=True)
            entries: list[dict[str, str]] = []
            staged_paths: list[Path] = []
            journal_written = False
            try:
                for target, value in files.items():
                    staged = (transaction_dir / target.name).resolve()
                    if not is_relative_to(staged, self.transaction_root):
                        raise ValueError("staged file escapes support/.txn")
                    atomic_write_text(staged, value)
                    staged_paths.append(staged)
                    entries.append(
                        {
                            "target": str(target),
                            "staged": str(staged),
                            "hash": hashlib.sha256(value.encode("utf-8")).hexdigest(),
                        }
                    )
                atomic_write_text(
                    self.journal,
                    json.dumps(
                        {"version": 1, "revision": revision, "files": entries},
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n",
                )
                journal_written = True
                for entry in entries:
                    atomic_replace(
                        Path(entry["staged"]),
                        Path(entry["target"]),
                        preserve_target_mode=True,
                    )

                if self._manifest_enabled and job is None:
                    manifest_state: dict[str, Any] = {
                        "state": "failed",
                        "targetRevision": revision,
                        "error": "rendered job is missing",
                    }
                else:
                    manifest_state = {
                        "state": "pending" if self._manifest_enabled else "not_configured",
                        "targetRevision": revision,
                    }
                next_state = dict(self._state)
                next_state.update(
                    {
                        "coreRevision": revision,
                        "manifest": manifest_state,
                        "assets": assets,
                    }
                )
                if source_state is not None:
                    next_state["source_state"] = source_state
                next_state.pop("recovery_required", None)
                next_state.pop("recovery_error", None)
                self._state = self._normalize_state(next_state)
                self._persist()
                self.journal.unlink()
                fsync_directory(self.support_dir)
                self._cleanup_empty_transaction_dirs(staged_paths)
            except Exception as exc:
                if journal_written:
                    self._state["recovery_required"] = True
                    self._state["recovery_error"] = str(exc)[:300]
                else:
                    for staged in staged_paths:
                        staged.unlink(missing_ok=True)
                    self._cleanup_empty_transaction_dirs(staged_paths)
                raise

            if self._manifest_enabled and job is not None:
                try:
                    snapshot = self.support_dir / f"{self.html_path.stem}.job.r{revision}.json"
                    atomic_write_text(
                        snapshot,
                        self._manifest_snapshot_text(files[self.job_path]),
                    )
                    self._queue_manifest_refresh(
                        self._manifest_refresh_request(revision, snapshot, source_state)
                    )
                except OSError as exc:
                    self._state["manifest"] = {
                        "state": "failed",
                        "targetRevision": revision,
                        "error": str(exc)[:240],
                    }
                    self._persist()

        return {
            "saved": True,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "html": str(self.html_path),
            "markdown": str(self.markdown_path) if job is not None else "",
            "job": str(self.job_path) if job is not None else "",
            "revision": revision,
            "clientMutationId": payload.get("clientMutationId"),
            "manifest": self._state["manifest"],
            "assets": self._state["assets"],
        }

    def close(self):
        with self._lock:
            self._closed = True
            self._manifest_pending = None
            thread = self._manifest_thread
        if thread and thread.is_alive():
            thread.join(timeout=1)


def make_handler(document: WorkbenchDocument):
    class WorkbenchHandler(SimpleHTTPRequestHandler):
        def end_headers(self) -> None:
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
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

        def do_GET(self) -> None:
            if not self.has_valid_host():
                self.send_json(403, {"error": "invalid host"})
                return
            if urlparse(self.path).path == STATUS_ENDPOINT:
                self.send_json(200, document.status())
                return
            super().do_GET()

        def do_HEAD(self) -> None:
            if not self.has_valid_host():
                self.send_response(403)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            super().do_HEAD()

        def do_POST(self) -> None:
            if urlparse(self.path).path != SAVE_ENDPOINT:
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
                if length <= 0 or length > MAX_REQUEST_BYTES:
                    raise ValueError("invalid request size")
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("request body must be an object")
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
