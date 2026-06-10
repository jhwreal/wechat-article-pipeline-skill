#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import re
from pathlib import Path


ACCOUNT_FIELD_RE = re.compile(
    r"^WECHAT_ACCOUNT_([A-Z0-9_]+?)_(SIGNATURE_AUTHOR|ORIGINAL_ISSUE|PREVIEW_ACCOUNT|APPSECRET|APPID|AUTHOR|NAME)$"
)


def read_env_file(path: Path | None) -> dict[str, str]:
    if not path:
        return {}
    path = path.expanduser()
    if not path.exists():
        return {}
    env: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            env[key] = value
    return env


def write_env_value(path: Path, key: str, value: str) -> None:
    path = path.expanduser()
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    output: list[str] = []
    replaced = False
    for line in lines:
        if line.strip().startswith(f"{key}="):
            output.append(f"{key}={value}")
            replaced = True
        else:
            output.append(line)
    if not replaced:
        if output and output[-1].strip():
            output.append("")
        output.append(f"{key}={value}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(output) + "\n", encoding="utf-8")


def normalize_account_alias(alias: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", alias.strip()).strip("_").upper()


def collect_account_profiles(env: dict[str, str]) -> dict[str, dict[str, str]]:
    groups: dict[str, dict[str, str]] = {}
    for key, value in env.items():
        match = ACCOUNT_FIELD_RE.match(key)
        if not match:
            continue
        alias, field = match.groups()
        groups.setdefault(alias, {})[field.lower()] = value.strip()
    return groups


def default_account_profile(env: dict[str, str]) -> dict[str, str]:
    return {
        "selector": "",
        "alias": "",
        "name": env.get("WECHAT_ACCOUNT_NAME", "").strip(),
        "appid": env.get("WECHAT_APPID", "").strip(),
        "appsecret": env.get("WECHAT_APPSECRET", "").strip(),
        "author": env.get("WECHAT_AUTHOR", "").strip(),
        "signature_author": env.get("WECHAT_SIGNATURE_AUTHOR", "").strip(),
        "original_issue": env.get("WECHAT_ORIGINAL_ISSUE", "").strip(),
        "preview_account": env.get("WECHAT_PREVIEW_ACCOUNT", "").strip(),
    }


def normalize_profile(alias: str, profile: dict[str, str], selector: str = "") -> dict[str, str]:
    return {
        "selector": selector,
        "alias": alias,
        "name": profile.get("name", "").strip(),
        "appid": profile.get("appid", "").strip(),
        "appsecret": profile.get("appsecret", "").strip(),
        "author": profile.get("author", "").strip(),
        "signature_author": profile.get("signature_author", "").strip(),
        "original_issue": profile.get("original_issue", "").strip(),
        "preview_account": profile.get("preview_account", "").strip(),
    }


def account_label(alias: str, profile: dict[str, str]) -> str:
    return f"{profile.get('name', '').strip() or alias} ({alias})"


def find_account_profile(
    env: dict[str, str],
    selector: str | None,
    *,
    include_credentials: bool = False,
    include_signature: bool = False,
) -> dict[str, str]:
    groups = collect_account_profiles(env)

    if not selector:
        if include_credentials:
            credential_groups = {
                alias: profile for alias, profile in groups.items() if profile.get("appid") or profile.get("appsecret")
            }
            if len(credential_groups) == 1:
                alias, profile = next(iter(credential_groups.items()))
                return normalize_profile(alias, profile)
            if len(credential_groups) > 1:
                available = sorted(account_label(alias, profile) for alias, profile in credential_groups.items())
                raise SystemExit(
                    "Multiple WeChat accounts are configured. Ask the user which account to use, then pass --account. "
                    f"Available accounts: {', '.join(available)}."
                )
        if include_signature:
            signature_groups = {
                alias: profile
                for alias, profile in groups.items()
                if profile.get("signature_author") or profile.get("original_issue")
            }
            if len(signature_groups) == 1:
                alias, profile = next(iter(signature_groups.items()))
                return normalize_profile(alias, profile)
        return default_account_profile(env)

    selector = selector.strip()
    selector_alias = normalize_account_alias(selector)
    matches: list[tuple[str, dict[str, str]]] = []
    for alias, profile in groups.items():
        if profile.get("name") == selector or (selector_alias and alias == selector_alias):
            matches.append((alias, profile))

    if not matches:
        profiles = groups.items()
        if include_credentials:
            profiles = ((alias, profile) for alias, profile in groups.items() if profile.get("appid") or profile.get("appsecret"))
        available = sorted(account_label(alias, profile) for alias, profile in profiles)
        suffix = f" Available accounts: {', '.join(available)}." if available else ""
        credential_hint = " plus APPID/APPSECRET" if include_credentials else ""
        raise SystemExit(
            f"Unknown WeChat account selector: {selector}. Set WECHAT_ACCOUNT_<ALIAS>_NAME{credential_hint} in .env."
            + suffix
        )
    if len(matches) > 1:
        aliases = ", ".join(alias for alias, _ in matches)
        raise SystemExit(f"WeChat account selector {selector} matches multiple aliases: {aliases}. Use the alias explicitly.")

    alias, profile = matches[0]
    return normalize_profile(alias, profile, selector)


def account_token_cache_path(default_path: Path, profile: dict[str, str]) -> Path:
    path = default_path.expanduser()
    if not profile.get("alias"):
        return path
    label = profile.get("name") or profile["alias"]
    digest = hashlib.sha1(label.encode("utf-8")).hexdigest()[:10]
    return path.with_name(f"{path.stem}-{profile['alias'].lower()}-{digest}{path.suffix}")
