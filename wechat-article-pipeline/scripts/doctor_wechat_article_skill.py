#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
from pathlib import Path
from typing import Any

import release_info


IGNORED_NAMES = {".DS_Store", ".env", ".env.lock"}
IGNORED_SUFFIXES = {".pyc", ".pyo"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check release metadata and Codex installation consistency for the article skill."
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Source skill directory.",
    )
    parser.add_argument(
        "--installed",
        type=Path,
        default=Path.home() / ".codex" / "skills" / "wechat-article-pipeline",
        help="Installed Codex skill directory.",
    )
    parser.add_argument("--skip-installed", action="store_true")
    parser.add_argument("--require-installed-sync", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def should_ignore(path: Path) -> bool:
    return (
        path.name in IGNORED_NAMES
        or path.suffix in IGNORED_SUFFIXES
        or "__pycache__" in path.parts
    )


def tree_digests(root: Path) -> dict[str, str]:
    if not root.is_dir():
        return {}
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or should_ignore(path.relative_to(root)):
            continue
        result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def compare_trees(source: Path, installed: Path) -> dict[str, list[str]]:
    source_files = tree_digests(source)
    installed_files = tree_digests(installed)
    return {
        "missing": sorted(set(source_files) - set(installed_files)),
        "extra": sorted(set(installed_files) - set(source_files)),
        "changed": sorted(
            name
            for name in set(source_files) & set(installed_files)
            if source_files[name] != installed_files[name]
        ),
    }


def env_permission_warning(installed: Path) -> str:
    env_path = installed / ".env"
    if not env_path.is_file():
        return ""
    mode = stat.S_IMODE(env_path.stat().st_mode)
    return "" if mode & 0o077 == 0 else f"{env_path} permissions are {oct(mode)}; prefer 0o600"


def inspect(source: Path, installed: Path | None = None) -> dict[str, Any]:
    source = source.resolve()
    errors: list[str] = []
    warnings: list[str] = []
    version = ""
    try:
        version = (source / "VERSION").read_text(encoding="utf-8").strip()
        if not release_info.SEMVER_RE.fullmatch(version):
            errors.append(f"invalid VERSION: {version!r}")
    except OSError as exc:
        errors.append(f"cannot read VERSION: {exc}")

    repo_root = source.parent
    pyproject_path = repo_root / "pyproject.toml"
    if pyproject_path.is_file():
        match = re.search(
            r'^version\s*=\s*"([^"]+)"$',
            pyproject_path.read_text(encoding="utf-8"),
            re.M,
        )
        if not match:
            errors.append("cannot resolve project version from pyproject.toml")
        elif version and match.group(1) != version:
            errors.append(f"pyproject version {match.group(1)} != skill VERSION {version}")
    readme_path = repo_root / "README.md"
    if readme_path.is_file() and version:
        readme = readme_path.read_text(encoding="utf-8")
        if f"V {version}（当前版本）" not in readme or f"V {version} (current version)" not in readme:
            errors.append("README current-version markers do not match VERSION")

    try:
        release_info.platform_adapters(source / "references" / "platform-adapters.json")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"cannot load platform adapters: {exc}")

    install_report: dict[str, Any] = {"checked": installed is not None, "synced": None}
    if installed is not None:
        installed = installed.resolve()
        install_report["path"] = str(installed)
        if not installed.is_dir():
            install_report.update({"synced": False, "missing_install": True})
        else:
            differences = compare_trees(source, installed)
            synced = not any(differences.values())
            install_report.update({"synced": synced, **differences})
            permission_warning = env_permission_warning(installed)
            if permission_warning:
                warnings.append(permission_warning)

    return {
        "status": "ok" if not errors else "error",
        "version": version,
        "source": str(source),
        "release_metadata_valid": not errors,
        "installed": install_report,
        "errors": errors,
        "warnings": warnings,
    }


def main() -> None:
    args = parse_args()
    installed = None if args.skip_installed else args.installed
    report = inspect(args.source, installed)
    if args.require_installed_sync and not report["installed"].get("synced"):
        report["status"] = "error"
        report["errors"].append("installed Codex skill is not synchronized")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"STATUS={report['status']}")
        print(f"VERSION={report['version']}")
        print(f"SOURCE={report['source']}")
        if report["installed"].get("checked"):
            print(f"INSTALLED_SYNCED={str(report['installed'].get('synced')).lower()}")
        for error in report["errors"]:
            print(f"ERROR={error}")
        for warning in report["warnings"]:
            print(f"WARNING={warning}")
    if report["status"] != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
