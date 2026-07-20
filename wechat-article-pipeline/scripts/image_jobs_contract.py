#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable, Mapping


SLOT_KEYS = (
    "index",
    "name",
    "output",
    "position",
    "role",
    "image_type",
    "target_effect",
    "local_context",
    "source_context",
    "content_focus",
    "visual_distance",
    "composition",
    "emotional_tone",
    "abstraction_level",
    "information_density",
    "visual_type",
    "text_budget",
    "purpose",
    "must_avoid",
    "must_include",
    "quality_gate",
    "beat_summary",
    "variation_note",
    "selection_criteria",
)
ARTICLE_KEYS = (
    "slug",
    "title",
    "type",
    "visual_mode",
    "visual_intent",
    "summary",
    "essence",
    "global_visual_style",
    "source",
    "planning_mode",
    "skipped_visuals",
)
QUEUE_KEYS = {"slot", "output", "generation_prompt"}
SLOT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
BODY_SLOT_NAME_RE = re.compile(r"^body-[1-9][0-9]*$")
OUTPUT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.(?:png|jpe?g|webp)$", re.I)
OUTPUT_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
WINDOWS_RESERVED_STEMS = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}


def _safe_slot_name(value: Any) -> str:
    name = str(value or "").strip()
    if not SLOT_NAME_RE.fullmatch(name):
        raise ValueError(f"invalid slot name: {name!r}")
    return name


def _safe_output(value: Any) -> str:
    output = str(value or "").strip()
    path = Path(output)
    if (
        not output
        or path.is_absolute()
        or path.name != output
        or "/" in output
        or "\\" in output
        or output in {".", ".."}
        or not OUTPUT_NAME_RE.fullmatch(output)
        or path.suffix.lower() not in OUTPUT_SUFFIXES
        or path.stem.casefold() in WINDOWS_RESERVED_STEMS
    ):
        raise ValueError(
            f"unsafe output: {output!r}; use one image filename ending in "
            + ", ".join(sorted(OUTPUT_SUFFIXES))
        )
    return output


def rules_fingerprint(rules: Mapping[str, Any]) -> str:
    payload = json.dumps(
        dict(rules), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _mapping_list(value: Any, field: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError(f"{field} entries must be objects")
        result.append(dict(item))
    return result


def normalize_image_jobs(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ValueError("image jobs payload must be an object")
    version = payload.get("schema_version", 1)
    if version not in (1, 2):
        raise ValueError(f"unknown schema version: {version}")

    if version == 2:
        slots = _mapping_list(payload.get("slots", []), "slots")
        queue = _mapping_list(payload.get("generation_queue", []), "generation_queue")
        normalized = {
            "kind": "wechat-image-jobs",
            "schema_version": 2,
            "article": dict(payload.get("article") or {}),
            "rules": dict(payload.get("rules") or {}),
            "review_defaults": dict(payload.get("review_defaults") or {}),
            "slots": [
                {key: slot[key] for key in SLOT_KEYS if key in slot}
                for slot in slots
            ],
            "generation_queue": queue,
        }
        return validate_image_jobs(normalized)

    raw_slots = (
        payload.get("jobs")
        or payload.get("slots")
        or payload.get("image_slots")
        or (payload.get("image_plan") or {}).get("image_slots")
        or []
    )
    slots_input = _mapping_list(raw_slots, "legacy slots")
    queue_input = _mapping_list(payload.get("generation_queue") or [], "generation_queue")
    queue_by_name = {
        str(item.get("slot") or item.get("name") or "").strip(): item
        for item in queue_input
    }

    slots: list[dict[str, Any]] = []
    prompts: dict[str, Any] = {}
    for index, source in enumerate(slots_input, start=1):
        item = dict(source)
        variants = item.get("variants") or item.get("candidates") or []
        if isinstance(variants, list) and variants and isinstance(variants[0], Mapping):
            merged = dict(variants[0])
            merged.update(item)
            item = merged
        name = str(item.get("name") or item.get("slot") or "").strip()
        queued = queue_by_name.get(name) or {}
        output = (
            item.get("output")
            or item.get("final_output")
            or queued.get("output")
            or f"{name}.png"
        )
        generation_task = item.get("generation_task")
        generation_task = generation_task if isinstance(generation_task, Mapping) else {}
        prompt = (
            item.get("generation_prompt")
            or item.get("prompt")
            or queued.get("generation_prompt")
            or queued.get("prompt")
            or generation_task.get("generation_prompt")
            or generation_task.get("prompt")
            or ""
        )
        slot = {
            "index": item.get("index", index),
            "name": name,
            "output": _safe_output(output),
        }
        for key in SLOT_KEYS:
            if key not in {"index", "name", "output"} and key in item:
                slot[key] = item[key]
        slots.append(slot)
        prompts[name] = prompt

    source_article = payload.get("article") or payload.get("article_meta") or {}
    source_article = source_article if isinstance(source_article, Mapping) else {}
    article_values = {
        "slug": payload.get("article_slug") or source_article.get("slug"),
        "title": payload.get("article_title") or source_article.get("title"),
        "type": payload.get("article_type") or source_article.get("type"),
        "visual_mode": payload.get("visual_mode") or source_article.get("visual_mode"),
        "visual_intent": payload.get("visual_intent") or source_article.get("visual_intent"),
        "summary": payload.get("article_summary") or source_article.get("summary"),
        "essence": payload.get("article_essence") or source_article.get("essence"),
        "global_visual_style": payload.get("global_visual_style")
        or source_article.get("global_visual_style"),
        "source": payload.get("source_article") or source_article.get("source"),
        "planning_mode": payload.get("planning_mode")
        or source_article.get("planning_mode"),
        "skipped_visuals": payload.get("skipped_visuals")
        if payload.get("skipped_visuals") is not None
        else source_article.get("skipped_visuals"),
    }
    article = {key: value for key, value in article_values.items() if value is not None}
    source_rules = payload.get("image_rules") or payload.get("rules") or {}
    source_rules = source_rules if isinstance(source_rules, Mapping) else {}
    rules = {
        "version": source_rules.get("version", "1"),
        "sha256": str(source_rules.get("sha256") or rules_fingerprint(source_rules)),
    }
    review_defaults = {
        "must_avoid": list(
            payload.get("must_avoid") or source_rules.get("avoid_rules") or []
        ),
        "quality_floor": list(
            payload.get("quality_floor") or source_rules.get("quality_floor_rules") or []
        ),
    }
    return validate_image_jobs(
        {
            "kind": "wechat-image-jobs",
            "schema_version": 2,
            "article": article,
            "rules": rules,
            "review_defaults": review_defaults,
            "slots": slots,
            "generation_queue": [
                {
                    "slot": slot["name"],
                    "output": slot["output"],
                    "generation_prompt": prompts.get(slot["name"], ""),
                }
                for slot in slots
            ],
        }
    )


def validate_image_jobs(payload: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get("kind") != "wechat-image-jobs" or payload.get("schema_version") != 2:
        raise ValueError("invalid image jobs kind/schema")
    if not isinstance(payload.get("article", {}), Mapping):
        raise ValueError("article must be an object")
    article = payload.get("article", {})
    skipped_visuals = article.get("skipped_visuals", [])
    if not isinstance(skipped_visuals, list) or any(
        not isinstance(name, str) or not BODY_SLOT_NAME_RE.fullmatch(name)
        for name in skipped_visuals
    ):
        raise ValueError("article.skipped_visuals must be a list of body-N slot names")
    if len(set(skipped_visuals)) != len(skipped_visuals):
        raise ValueError("article.skipped_visuals must be unique")
    rules = payload.get("rules", {})
    if not isinstance(rules, Mapping):
        raise ValueError("rules must be an object")
    rules_sha = str(rules.get("sha256", "")).strip()
    if rules_sha and not re.fullmatch(r"[0-9a-f]{64}", rules_sha):
        raise ValueError("rules.sha256 must be a lowercase SHA-256 digest")
    review_defaults = payload.get("review_defaults", {})
    if not isinstance(review_defaults, Mapping):
        raise ValueError("review_defaults must be an object")
    for field in ("must_avoid", "quality_floor"):
        values = review_defaults.get(field, [])
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            raise ValueError(f"review_defaults.{field} must be a list of strings")
    slots = _mapping_list(payload.get("slots", []), "slots")
    queue = _mapping_list(payload.get("generation_queue", []), "generation_queue")

    names: list[str] = []
    outputs: list[str] = []
    indices: list[int] = []
    for slot in slots:
        slot["name"] = _safe_slot_name(slot.get("name"))
        slot["output"] = _safe_output(slot.get("output"))
        names.append(slot["name"])
        outputs.append(slot["output"])
        if "index" in slot:
            index = slot["index"]
            if isinstance(index, bool) or not isinstance(index, int) or index < 1:
                raise ValueError("slot index must be a positive integer")
            indices.append(index)
    if len(set(names)) != len(names):
        raise ValueError("slot names must be unique")
    overlap = set(names).intersection(skipped_visuals)
    if overlap:
        raise ValueError(
            "article.skipped_visuals cannot also appear in slots: "
            + ", ".join(sorted(overlap))
        )
    if len({output.casefold() for output in outputs}) != len(outputs):
        raise ValueError("slot outputs must be unique, including case-insensitively")
    if len(set(indices)) != len(indices):
        raise ValueError("slot indices must be unique")
    if len(queue) != len(slots):
        raise ValueError("generation_queue must contain exactly one task per slot")

    queue_names: list[str] = []
    for index, task in enumerate(queue):
        if set(task) != QUEUE_KEYS:
            raise ValueError("queue keys must be exactly slot/output/generation_prompt")
        queue_name = _safe_slot_name(task.get("slot"))
        queue_output = _safe_output(task.get("output"))
        task["slot"] = queue_name
        task["output"] = queue_output
        prompt = task.get("generation_prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError(f"generation prompt is empty for slot {queue_name!r}")
        if queue_name != names[index] or queue_output != outputs[index]:
            raise ValueError("generation_queue order/output must match slots exactly")
        queue_names.append(queue_name)
    if len(set(queue_names)) != len(queue_names):
        raise ValueError("generation_queue slot names must be unique")

    result = dict(payload)
    result["slots"] = slots
    result["generation_queue"] = queue
    return result


def filter_missing_image_jobs(
    payload: Mapping[str, Any], exists: Callable[[str], bool]
) -> dict[str, Any]:
    normalized = normalize_image_jobs(payload)
    kept_slots = [slot for slot in normalized["slots"] if not exists(slot["output"])]
    kept_names = {slot["name"] for slot in kept_slots}
    normalized["slots"] = kept_slots
    normalized["generation_queue"] = [
        task
        for task in normalized["generation_queue"]
        if task["slot"] in kept_names
    ]
    return validate_image_jobs(normalized)


def slots_by_name(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {slot["name"]: slot for slot in normalize_image_jobs(payload)["slots"]}


def derive_image_plan(payload: Mapping[str, Any]) -> dict[str, Any]:
    normalized = normalize_image_jobs(payload)
    article = normalized["article"]
    return {
        "article_title": article.get("title", ""),
        "article_summary": article.get("summary", ""),
        "article_type": article.get("type", ""),
        "visual_mode": article.get("visual_mode", ""),
        "visual_intent": article.get("visual_intent", ""),
        "global_visual_style": article.get("global_visual_style", ""),
        "planning_mode": article.get("planning_mode", ""),
        "skipped_visuals": article.get("skipped_visuals", []),
        "image_slots": normalized["slots"],
    }


def _markdown_cell(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def render_image_plan_markdown(payload: Mapping[str, Any]) -> str:
    normalized = normalize_image_jobs(payload)
    rows = ["| name | output | role |", "|---|---|---|"]
    rows.extend(
        f"| {_markdown_cell(slot['name'])} | {_markdown_cell(slot['output'])} | {_markdown_cell(slot.get('role'))} |"
        for slot in normalized["slots"]
    )
    return "\n".join(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate and normalize a WeChat image-jobs JSON file.")
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    try:
        normalize_image_jobs(json.loads(args.input.read_text(encoding="utf-8")))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f"{args.input}: {exc}") from exc


if __name__ == "__main__":
    main()
