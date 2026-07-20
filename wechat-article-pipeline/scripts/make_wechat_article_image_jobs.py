#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

import build_wechat_article_workbench as builder
from atomic_files import atomic_write_text
from image_jobs_contract import (
    filter_missing_image_jobs,
    normalize_image_jobs,
    render_image_plan_markdown,
    rules_fingerprint,
)
from image_planning_catalog import (
    BODY_ROLE_LIBRARY,
    EMOTIONAL_VISUAL_ROLES,
    SIGNAL_PATTERNS,
    STRUCTURAL_VISUAL_ROLES,
)


PLACEHOLDER_RE = re.compile(r"\{\{visual:([a-zA-Z0-9_-]+)\}\}")
BODY_PLACEHOLDER_RE = re.compile(r"^body-[1-9][0-9]*$")
TITLE_RE = re.compile(r"^\s*#\s+(.+?)\s*$", re.M)
REFERENCE_HEADING_RE = re.compile(
    r"^\s*#{1,6}\s*(资料参考|参考来源|参考资料|参考信息|信息来源|官方链接|参考|references?)\s*$",
    re.I | re.M,
)
REFERENCE_INTRO_RE = re.compile(
    r"(?m)^(?:\s*-{3,}\s*\n+)?\s*(?:参考信息|参考资料|资料参考|信息来源|官方链接|参考链接|以下信息).*$"
)
CHINESE_CHAR_RE = re.compile(r"[\u4e00-\u9fff]")
RULES_PATH = Path(__file__).resolve().parents[1] / "references" / "image-rules.json"
_IMAGE_RULES_CACHE: dict[str, Any] | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create built-in Codex image generation jobs from a finished WeChat article markdown file."
    )
    parser.add_argument("article", type=Path, help="Path to the article markdown file.")
    parser.add_argument("out", type=Path, help="Path to write the image jobs JSON.")
    parser.add_argument("--article-slug", help="Optional article slug override.")
    parser.add_argument(
        "--target-body-chars",
        type=int,
        default=200,
        help="Target Chinese-character rhythm for each in-body image beat.",
    )
    parser.add_argument(
        "--min-body-chars",
        type=int,
        default=120,
        help="Minimum approximate chars before forcing a new beat.",
    )
    parser.add_argument(
        "--debug-plan",
        action="store_true",
        help="Print the generated markdown image-plan table to stdout.",
    )
    parser.add_argument(
        "--mode",
        choices=("no-image", "fast", "full"),
        default="full",
        help="Image planning mode: no-image writes no jobs, fast limits body images, full uses all placeholders.",
    )
    parser.add_argument(
        "--max-body-images",
        type=int,
        help="Maximum number of body-N image jobs to keep. In fast mode, defaults to 1.",
    )
    parser.add_argument(
        "--missing-only",
        action="store_true",
        help="Keep only jobs whose output file is missing from --images-dir.",
    )
    parser.add_argument(
        "--images-dir",
        type=Path,
        help="Directory containing generated images when --missing-only is used.",
    )
    return parser.parse_args()


def slugify(value: str, fallback: str = "wechat-article") -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
    if slug:
        return slug
    clean = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", value.strip(), flags=re.UNICODE)
    clean = re.sub(r"-+", "-", clean).strip("-_")
    return clean or fallback


def load_image_rules() -> dict[str, Any]:
    global _IMAGE_RULES_CACHE
    if _IMAGE_RULES_CACHE is None:
        _IMAGE_RULES_CACHE = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    return _IMAGE_RULES_CACHE


def slot_kind_for_rules(slot: dict[str, Any]) -> str:
    role = slot.get("role", "")
    if role == "hero_cover":
        return "cover"
    if role == "closing_image":
        return "closing"
    return "body"



def infer_article_slug(article_path: Path, title: str) -> str:
    stem = article_path.stem.strip()
    if stem and stem.lower() != "article":
        return slugify(stem)
    parent = article_path.parent.name.strip()
    if parent:
        return slugify(parent)
    return slugify(title or stem)


def extract_title(markdown: str, fallback: str) -> str:
    match = TITLE_RE.search(markdown)
    return match.group(1).strip() if match else fallback


def strip_markdown(text: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = PLACEHOLDER_RE.sub(" ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"==([^=\n]+)==", r"\1", text)
    text = re.sub(r"[`>*_#-]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def approx_chars(text: str) -> int:
    chinese = len(CHINESE_CHAR_RE.findall(text))
    if chinese:
        return chinese
    return len(re.sub(r"\s+", "", text))


def truncate_text(text: str, max_chars: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""
    if approx_chars(text) <= max_chars:
        return text

    units = 0.0
    chars: list[str] = []
    for ch in text:
        if ch.isspace():
            step = 0.0
        elif CHINESE_CHAR_RE.fullmatch(ch):
            step = 1.0
        else:
            step = 0.5
        if units + step > max_chars:
            break
        chars.append(ch)
        units += step
    return "".join(chars).rstrip(" ，。；、,:;-") + "…"


def split_sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    parts = re.split(r"(?<=[。！？!?；;])", text)
    return [part.strip() for part in parts if part.strip()]


def first_sentence(text: str, max_chars: int = 80) -> str:
    sentences = split_sentences(text)
    candidate = sentences[0] if sentences else text
    return truncate_text(candidate, max_chars)


def last_sentence(text: str, max_chars: int = 90) -> str:
    sentences = split_sentences(text)
    candidate = sentences[-1] if sentences else text
    return truncate_text(candidate, max_chars)


def signal_score(text: str, signal: str) -> int:
    pattern = SIGNAL_PATTERNS[signal]
    return len(pattern.findall(text or ""))


def dominant_signals(text: str) -> list[str]:
    scores = [(name, signal_score(text, name)) for name in SIGNAL_PATTERNS]
    scores.sort(key=lambda item: item[1], reverse=True)
    return [name for name, score in scores if score > 0]


def select_visual_sentence(text: str, max_chars: int = 90) -> str:
    sentences = split_sentences(text)
    if not sentences:
        return truncate_text(text, max_chars)

    scored: list[tuple[int, int, str]] = []
    for index, sentence in enumerate(sentences):
        compact = re.sub(r"\s+", "", sentence)
        score = 0
        # 通用修辞信号，而非具体题材词：冲突、方法、清单、对比、证据、机制、情绪。
        for signal, weight in {
            "problem": 5,
            "promise": 4,
            "process": 4,
            "list": 4,
            "compare": 4,
            "evidence": 3,
            "mechanism": 3,
            "emotion": 4,
            "story": 2,
        }.items():
            if SIGNAL_PATTERNS[signal].search(sentence):
                score += weight
        if 14 <= len(compact) <= 80:
            score += 2
        elif len(compact) > 80:
            score += 1
        score += min(index, 2)
        scored.append((score, index, sentence))

    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return truncate_text(scored[0][2], max_chars)


def parse_placeholders(markdown: str) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for match in PLACEHOLDER_RE.finditer(markdown):
        name = match.group(1)
        if name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


def body_placeholder_key(name: str) -> tuple[int, str]:
    suffix = name.split("body-", 1)[1]
    return (int(suffix) if suffix.isdigit() else 10**9, name)


def trim_reference_section(markdown: str) -> str:
    starts: list[int] = []
    for pattern in (REFERENCE_HEADING_RE, REFERENCE_INTRO_RE):
        match = pattern.search(markdown)
        if match:
            starts.append(match.start())
    return markdown[: min(starts)].rstrip() if starts else markdown


def parse_article_entries(markdown: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    body = trim_reference_section(markdown)
    ordinal = 0
    for raw in body.split("\n\n"):
        block = raw.strip()
        if not block:
            continue
        if re.fullmatch(r"\s*#\s+.+", block):
            continue
        cleaned = strip_markdown(block)
        if cleaned:
            ordinal += 1
            entries.append({"kind": "text", "text": cleaned, "ordinal": ordinal})
        for match in PLACEHOLDER_RE.finditer(block):
            entries.append({"kind": "placeholder", "name": match.group(1), "ordinal": ordinal})
    return entries


def join_entries(entries: list[dict[str, Any]]) -> str:
    return "\n".join(entry["text"] for entry in entries if entry.get("text")).strip()


def take_recent_entries(history: list[dict[str, Any]], target_chars: int, min_chars: int) -> tuple[str, int | None, int | None]:
    if not history:
        return "", None, None
    selected: list[dict[str, Any]] = []
    total = 0
    for entry in reversed(history):
        selected.insert(0, entry)
        total += approx_chars(entry["text"])
        if total >= target_chars and total >= min_chars:
            break
    return join_entries(selected), selected[0]["ordinal"], selected[-1]["ordinal"]


def take_first_entries(entries: list[dict[str, Any]], target_chars: int, min_chars: int) -> tuple[str, int | None, int | None]:
    if not entries:
        return "", None, None
    selected: list[dict[str, Any]] = []
    total = 0
    for entry in entries:
        selected.append(entry)
        total += approx_chars(entry["text"])
        if total >= target_chars and total >= min_chars:
            break
    return join_entries(selected), selected[0]["ordinal"], selected[-1]["ordinal"]


def unique_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        clean = value.strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        result.append(clean)
    return result


def build_article_summary(title: str, text_entries: list[dict[str, Any]], max_chars: int = 72) -> str:
    intro, _, _ = take_first_entries(text_entries, target_chars=130, min_chars=70)
    closing, _, _ = take_recent_entries(text_entries, target_chars=90, min_chars=50)
    parts = unique_preserve_order([
        first_sentence(intro, 40),
        first_sentence(closing, 28),
    ])
    summary = "；".join(parts)
    return truncate_text(summary or title, max_chars)


def build_article_essence(title: str, text_entries: list[dict[str, Any]], max_chars: int = 520) -> str:
    intro, _, _ = take_first_entries(text_entries, target_chars=180, min_chars=90)
    closing, _, _ = take_recent_entries(text_entries, target_chars=150, min_chars=80)
    middle = text_entries[len(text_entries) // 2]["text"] if text_entries else ""
    essence = "\n".join(unique_preserve_order([title, intro, first_sentence(middle, 90), closing]))
    return truncate_text(essence, max_chars)


def detect_article_type(title: str, text_entries: list[dict[str, Any]]) -> str:
    text = f"{title}\n" + "\n".join(entry["text"] for entry in text_entries[:5])
    method_score = signal_score(text, "promise") + signal_score(text, "process") * 2 + signal_score(text, "list")
    emotional_score = signal_score(text, "emotion") * 2 + signal_score(text, "story") * 2 + signal_score(text, "principle") * 2
    if emotional_score >= method_score and emotional_score > 0:
        if SIGNAL_PATTERNS["story"].search(text):
            return "feature-story"
        return "viewpoint-commentary"
    if method_score > emotional_score:
        return "practical-how-to"
    if SIGNAL_PATTERNS["story"].search(text):
        return "feature-story"
    if re.search(r"我认为|我更|别再|不要再|应该|判断|观点|评论|看法", text):
        return "viewpoint-commentary"
    if re.search(r"为什么|到底|是什么|发生了什么|意味着|解释|看懂", text):
        return "news-explanation"
    return "industry-analysis"


def detect_visual_intent(title: str, text_entries: list[dict[str, Any]]) -> str:
    """Detect what the visual system should do for this article.

    This is deliberately topic-agnostic. It does not care whether the topic is AI,
    food, parenting, finance, travel, hardware, or policy. It only detects the
    article's visual function: emotional hook, process, checklist, contrast,
    evidence, story, or mixed.
    """
    text = f"{title}\n" + "\n".join(entry["text"] for entry in text_entries[:8])
    title_boost = {
        "problem": 3,
        "promise": 3,
        "process": 4,
        "list": 4,
        "compare": 4,
        "evidence": 3,
        "emotion": 3,
        "story": 3,
        "mechanism": 2,
    }
    scores: dict[str, int] = {}
    for signal in SIGNAL_PATTERNS:
        scores[signal] = signal_score(text, signal) + (title_boost.get(signal, 0) if SIGNAL_PATTERNS[signal].search(title) else 0)

    mapped = {
        "emotional_hook": scores["problem"] + scores["emotion"],
        "practical_path": scores["process"] + scores["promise"],
        "checklist_map": scores["list"],
        "contrast": scores["compare"],
        "evidence_led": scores["evidence"],
        "explanatory": scores["mechanism"],
        "story_scene": scores["story"],
    }
    active = [name for name, score in mapped.items() if score >= 4]
    if len(active) >= 2:
        return "mixed"
    if active:
        return active[0]
    return max(mapped.items(), key=lambda item: item[1])[0] if max(mapped.values()) > 0 else "mixed"


def detect_visual_mode(title: str, text_entries: list[dict[str, Any]], article_type: str, visual_intent: str) -> str:
    """Choose the visual grammar before selecting per-slot roles.

    Method content can use steps, checklists, process nodes, and information cards.
    Emotional/story/principle content should use illustration logic: human moments,
    atmosphere, symbolic scenes, silence, tension, and metaphor.
    """
    text = f"{title}\n" + "\n".join(entry["text"] for entry in text_entries[:8])
    method_score = (
        signal_score(text, "process") * 2
        + signal_score(text, "promise") * 2
        + signal_score(text, "list")
    )
    emotional_score = (
        signal_score(text, "emotion") * 2
        + signal_score(text, "story") * 2
        + signal_score(text, "principle") * 2
        + signal_score(text, "problem")
    )
    analysis_score = (
        signal_score(text, "mechanism") * 2
        + signal_score(text, "evidence") * 2
        + signal_score(text, "compare")
    )

    if article_type == "practical-how-to" and method_score >= emotional_score:
        return "method_visual"
    if visual_intent in {"story_scene", "emotional_hook"} and emotional_score >= method_score:
        return "emotional_illustration"
    if article_type in {"feature-story", "viewpoint-commentary"} and emotional_score >= method_score:
        return "emotional_illustration"
    if emotional_score >= method_score + 2 and emotional_score >= analysis_score:
        return "emotional_illustration"
    if method_score >= max(emotional_score, analysis_score):
        return "method_visual"
    return "analysis_visual"


def select_global_visual_style(article_type: str, visual_intent: str, visual_mode: str) -> str:
    base_mapping = {
        "news-explanation": "clean newsroom / blueprint 风格，理性、证据感强、构图克制。",
        "viewpoint-commentary": "高级商业评论感，题图可以更像海报，正文要真实、克制、有观点推进。",
        "practical-how-to": "清楚的流程场景、干净构图、步骤关系明确。",
        "feature-story": "更有现场感和人物在场感，光线和情绪自然。",
        "industry-analysis": "高级商业编辑感，重点是判断、结构和变化。",
    }
    intent_mapping = {
        "emotional_hook": "题图和关键正文图要有情绪钩子：压力、冲突、悬念、代入感要明确。",
        "practical_path": "正文图优先表达路径和方法：步骤、箭头、节点、前后关系要清楚。",
        "checklist_map": "正文图优先做清单和分类：类别、要点、场景、环节要一眼可读。",
        "contrast": "正文图优先表达差异：新旧对比、前后变化、选择分岔要拉开。",
        "evidence_led": "正文图优先表达证据：数据、案例、趋势、事实依据要可信可读。",
        "explanatory": "正文图优先解释机制：因果、关系、结构、底层逻辑要清楚。",
        "story_scene": "正文图优先还原现场：人物、处境、动作、氛围要具体。",
        "mixed": "题图负责抓人，正文图按段落分别使用情绪、步骤、清单、对比、证据或机制图。",
    }
    mode_mapping = {
        "method_visual": "当前采用轻量方法图语法：可以使用步骤、箭头、清单、对比和短标签，但正文图默认优先用一个场景加少量结构解释一个点。",
        "emotional_illustration": "当前采用有信息量的情绪插图语法：优先人物处境、空间氛围、光线、动作、物件隐喻和视觉冲击。",
        "analysis_visual": "当前采用轻量分析图语法：优先证据、对比、机制和克制隐喻；正文图默认一图只解释一个判断。",
    }
    if visual_mode == "emotional_illustration":
        return (
            f"{base_mapping.get(article_type, base_mapping['viewpoint-commentary'])} "
            "正文图优先表达共鸣、处境、故事张力和情绪余味。 "
            f"{mode_mapping['emotional_illustration']}"
        )
    return (
        f"{base_mapping.get(article_type, base_mapping['industry-analysis'])} "
        f"{intent_mapping.get(visual_intent, intent_mapping['mixed'])} "
        f"{mode_mapping.get(visual_mode, mode_mapping['analysis_visual'])}"
    )


def select_body_role_keys(count: int, article_type: str, visual_intent: str, visual_mode: str) -> list[str]:
    if visual_mode == "emotional_illustration":
        base_sequence = [
            "inline_human_moment",
            "inline_tension",
            "inline_symbolic_scene",
            "inline_silence",
            "inline_scene",
            "inline_metaphor",
            "inline_emotion",
        ]
        while len(base_sequence) < count:
            base_sequence.extend(["inline_human_moment", "inline_symbolic_scene", "inline_silence", "inline_metaphor"])
        return base_sequence[:count]
    if visual_mode == "analysis_visual":
        base_sequence = ["inline_light_explainer", "inline_contrast", "inline_evidence", "inline_explanation", "inline_detail", "inline_metaphor", "inline_scene"]
        while len(base_sequence) < count:
            base_sequence.extend(["inline_light_explainer", "inline_contrast", "inline_explanation", "inline_detail"])
        return base_sequence[:count]

    presets = {
        "emotional_hook": ["inline_tension", "inline_light_explainer", "inline_contrast", "inline_detail", "inline_symbolic_scene", "inline_metaphor", "inline_emotion"],
        "practical_path": ["inline_light_explainer", "inline_steps", "inline_detail", "inline_checklist", "inline_contrast", "inline_data_card", "inline_scene"],
        "checklist_map": ["inline_light_explainer", "inline_checklist", "inline_contrast", "inline_explanation", "inline_steps", "inline_detail", "inline_scene"],
        "contrast": ["inline_contrast", "inline_light_explainer", "inline_tension", "inline_detail", "inline_checklist", "inline_metaphor", "inline_scene"],
        "evidence_led": ["inline_light_explainer", "inline_evidence", "inline_contrast", "inline_explanation", "inline_detail", "inline_checklist", "inline_scene"],
        "explanatory": ["inline_light_explainer", "inline_explanation", "inline_detail", "inline_contrast", "inline_checklist", "inline_metaphor", "inline_scene"],
        "story_scene": ["inline_scene", "inline_detail", "inline_tension", "inline_emotion", "inline_metaphor", "inline_extension", "inline_explanation"],
        "mixed": ["inline_light_explainer", "inline_tension", "inline_checklist", "inline_contrast", "inline_steps", "inline_detail", "inline_scene"],
    }
    base_sequence = list(presets.get(visual_intent, presets["mixed"]))
    if count <= len(base_sequence):
        return base_sequence[:count]
    extras = ["inline_light_explainer", "inline_data_card", "inline_checklist", "inline_steps", "inline_evidence", "inline_detail", "inline_scene", "inline_metaphor", "inline_contrast", "inline_extension"]
    while len(base_sequence) < count:
        base_sequence.append(extras[(len(base_sequence) - len(presets.get(visual_intent, presets["mixed"]))) % len(extras)])
    return base_sequence[:count]


def choose_body_role_key(local_context: str, fallback_role_key: str, visual_mode: str) -> str:
    """Route each body image by paragraph function, not by article topic."""
    text = local_context or ""
    explicit_process = bool(re.search(r"第一|第二|第三|步骤|流程|然后|接着|最后|下一步|→|->", text))
    process_count = signal_score(text, "process")
    list_count = signal_score(text, "list")
    if visual_mode == "emotional_illustration":
        if SIGNAL_PATTERNS["story"].search(text):
            return "inline_human_moment"
        if SIGNAL_PATTERNS["problem"].search(text) or SIGNAL_PATTERNS["emotion"].search(text):
            return "inline_tension"
        if SIGNAL_PATTERNS["principle"].search(text) or SIGNAL_PATTERNS["mechanism"].search(text):
            return "inline_symbolic_scene"
        if SIGNAL_PATTERNS["compare"].search(text):
            return "inline_metaphor"
        return fallback_role_key if fallback_role_key in EMOTIONAL_VISUAL_ROLES else "inline_emotion"

    if visual_mode == "analysis_visual":
        if SIGNAL_PATTERNS["evidence"].search(text):
            return "inline_evidence"
        if SIGNAL_PATTERNS["compare"].search(text):
            return "inline_contrast"
        if SIGNAL_PATTERNS["problem"].search(text) or SIGNAL_PATTERNS["emotion"].search(text):
            return "inline_tension"
        if SIGNAL_PATTERNS["mechanism"].search(text):
            return "inline_light_explainer"
        return fallback_role_key if fallback_role_key not in {"inline_steps", "inline_checklist"} else "inline_light_explainer"

    if SIGNAL_PATTERNS["process"].search(text) and (explicit_process or process_count >= 2):
        return "inline_steps"
    if SIGNAL_PATTERNS["compare"].search(text):
        return "inline_contrast"
    if SIGNAL_PATTERNS["list"].search(text) and list_count >= 2:
        return "inline_checklist"
    if SIGNAL_PATTERNS["evidence"].search(text):
        return "inline_evidence"
    if SIGNAL_PATTERNS["problem"].search(text) or SIGNAL_PATTERNS["emotion"].search(text):
        return "inline_tension"
    if SIGNAL_PATTERNS["mechanism"].search(text):
        return "inline_light_explainer"
    if SIGNAL_PATTERNS["story"].search(text):
        return "inline_scene"
    return fallback_role_key if fallback_role_key not in {"inline_steps", "inline_checklist"} else "inline_light_explainer"


def compact_segment(entries: list[dict[str, Any]], target_chars: int) -> tuple[str, int | None, int | None]:
    if not entries:
        return "", None, None

    total = sum(approx_chars(entry["text"]) for entry in entries)
    if total <= target_chars * 1.4:
        selected = entries
    else:
        selected = []
        running = 0
        for entry in reversed(entries):
            selected.insert(0, entry)
            running += approx_chars(entry["text"])
            if running >= target_chars:
                break

    return join_entries(selected), selected[0]["ordinal"], selected[-1]["ordinal"]


def build_body_context_map(
    entries: list[dict[str, Any]],
    target_chars: int,
    min_chars: int,
) -> dict[str, dict[str, Any]]:
    contexts: dict[str, dict[str, Any]] = {}
    segment_since_last_visual: list[dict[str, Any]] = []
    last_text: list[dict[str, Any]] = []

    for entry in entries:
        if entry["kind"] == "text":
            segment_since_last_visual.append(entry)
            last_text.append(entry)
            if len(last_text) > 3:
                last_text = last_text[-3:]
            continue

        name = entry["name"]
        if name.startswith("body-"):
            source_entries = segment_since_last_visual or last_text[-1:]
            local_context, start_ord, end_ord = compact_segment(source_entries, target_chars=target_chars)
            contexts[name] = {
                "local_context": local_context,
                "start_ordinal": start_ord,
                "end_ordinal": end_ord,
                "source_policy": "since_previous_visual_placeholder",
            }

        segment_since_last_visual = []

    return contexts


def build_cover_focus(title: str, local_context: str, article_summary: str, visual_intent: str) -> str:
    local_focus = select_visual_sentence(local_context, 90) or first_sentence(article_summary, 90)
    intent_wording = {
        "emotional_hook": "画面优先呈现标题里的压力、冲突、悬念或读者代入感",
        "practical_path": "画面优先呈现从困惑到结果的路径感、方法感和可执行感",
        "checklist_map": "画面优先呈现这篇文章会给出清单、分类、地图或结构化答案",
        "contrast": "画面优先呈现新旧、前后、左右或选择之间的差异",
        "evidence_led": "画面优先呈现可信证据、案例、趋势或事实依据",
        "explanatory": "画面优先呈现一个机制、结构或因果关系",
        "story_scene": "画面优先呈现人物处境、现场感和故事张力",
        "mixed": "画面优先抓住标题承诺中最有传播力的冲突、收益或悬念",
    }
    return f"标题承诺优先：{intent_wording.get(visual_intent, intent_wording['mixed'])}；结合导语线索：{local_focus}"


def build_content_focus(role: str, local_context: str, article_summary: str) -> str:
    if role == "closing_image":
        focus = last_sentence(local_context, 90) or article_summary
    elif role == "hero_cover":
        focus = select_visual_sentence(local_context, 90) or first_sentence(article_summary, 90)
    else:
        focus = select_visual_sentence(local_context, 90) or article_summary

    mapping = {
        "hero_cover": f"只抓标题承诺里最有点击力的冲突、收益或悬念：{focus}",
        "inline_light_explainer": f"用轻量解释型插图讲清这一段的一个具体判断：{focus}",
        "inline_explanation": f"把这一段最关键的机制讲清楚：{focus}",
        "inline_scene": f"把这一段的具体现场、人物处境或使用场景画出来：{focus}",
        "inline_tension": f"把这一段的压力、矛盾、风险或情绪冲突直接画出来：{focus}",
        "inline_contrast": f"把这一段里的差异拉开，画出对比关系：{focus}",
        "inline_steps": f"把这一段拆成清晰步骤、路径或流程：{focus}",
        "inline_checklist": f"把这一段归纳成清晰类别、清单、场景或环节：{focus}",
        "inline_data_card": f"把这一段转成克制的概念解释图：{focus}",
        "inline_evidence": f"把这一段的数据、案例、证据或趋势画得可信清楚：{focus}",
        "inline_detail": f"放大这一段里最具体的一个动作、对象或局部：{focus}",
        "inline_metaphor": f"用一个克制但明确的隐喻表达这一段判断：{focus}",
        "inline_extension": f"顺着这一段观点往前推一步，画出下一步会发生什么：{focus}",
        "inline_emotion": f"让读者感受到这一段的情绪或判断分量：{focus}",
        "inline_silence": f"把这一段没有直接说出口的情绪、停顿或余味变成安静画面：{focus}",
        "inline_symbolic_scene": f"把这一段的抽象道理转成一个有冲击力的象征性场景：{focus}",
        "inline_human_moment": f"把这一段落到一个具体人的瞬间，先让读者代入：{focus}",
        "closing_image": f"收束全文：做余韵画面或象征画面，不做总结卡：{focus}",
    }
    return mapping.get(role, focus)


def build_role_avoids(role: str) -> list[str]:
    return list(load_image_rules().get("avoid_rules", []))


def visual_type_key_for_slot(slot: dict[str, Any]) -> str:
    role = str(slot.get("role", ""))
    if role == "closing_image":
        return "poetic_closing"
    if role in {"inline_steps", "inline_checklist"}:
        return "operation_map"
    if role in {"inline_light_explainer", "inline_explanation", "inline_contrast", "inline_data_card", "inline_evidence"}:
        return "concept_explainer"
    return "editorial_scene"


def text_budget_key_for_slot(slot: dict[str, Any]) -> str:
    role = str(slot.get("role", ""))
    if role in {"hero_cover", "closing_image"}:
        return "no_text"
    if role in EMOTIONAL_VISUAL_ROLES or role in {"inline_scene", "inline_detail", "inline_metaphor", "inline_extension"}:
        return "no_text"
    if role in {"inline_steps", "inline_checklist"}:
        return "compact_explainer"
    return "micro_labels"


def rule_text(section: str, key: str) -> str:
    value = load_image_rules().get(section, {}).get(key, "")
    return str(value).strip()


def build_prompt_constraints(slot: dict[str, Any]) -> list[str]:
    rules = load_image_rules()
    visual_type = rule_text("visual_type_rules", str(slot.get("visual_type", "")))
    text_budget = rule_text("text_budget_rules", str(slot.get("text_budget", "")))
    quality_floor = list(rules.get("quality_floor_rules", []))
    guardrails = list(rules.get("prompt_guardrails", []))
    hard_limits = list(rules.get("prompt_hard_limits", []))
    lines = [
        f"视觉类型：{visual_type}" if visual_type else "",
        f"文字预算：{text_budget}" if text_budget else "",
        "质感要求：" + "；".join(quality_floor) if quality_floor else "",
        "硬性限制：" + "；".join([*guardrails, *hard_limits]) if guardrails or hard_limits else "",
    ]
    return [line for line in lines if line]


def prompt_style_for_slot(slot: dict[str, Any]) -> str:
    role = str(slot.get("role", ""))
    if role == "hero_cover":
        return "题图优先一个强主视觉、干净留白和第一屏冲击力；画面要有编辑插图质感。"
    if role == "closing_image":
        return "安静、有留白、收束感强；优先远景、自然光、物件隐喻或空间关系，不做流程总结。"
    return str(slot.get("global_visual_style", "")).strip()


def build_must_include(slot: dict[str, Any]) -> list[str]:
    role = str(slot.get("role", ""))
    includes = [
        f"必须采用视觉类型：{rule_text('visual_type_rules', str(slot.get('visual_type', '')))}",
        f"必须遵守文字预算：{rule_text('text_budget_rules', str(slot.get('text_budget', '')))}",
    ]
    if role == "hero_cover":
        includes.extend([
            "必须有一个清晰主视觉，不能平均铺满多个信息块。",
            "必须让标题承诺通过人物、物件、空间关系或冲突被感受到，而不是写进图里。",
        ])
    elif role == "closing_image":
        includes.extend([
            "必须收束成一个有余味的画面，不做总结卡、步骤卡或收藏卡。",
            "必须通过留白、远景、物件或空间隐喻表达结论。",
        ])
    elif role in {"inline_steps", "inline_checklist"}:
        includes.extend([
            "必须只表达当前位置的流程或分类，不总结全文。",
            "必须控制在 3 到 4 个节点内，标签极短。",
        ])
    elif role in {"inline_light_explainer", "inline_explanation", "inline_contrast", "inline_data_card", "inline_evidence"}:
        includes.extend([
            "必须用一个主场景或主物件承载判断，少量结构只做辅助。",
            "必须让关系、差异或后果一眼能看出，不能靠长文字解释。",
        ])
    else:
        includes.append("必须用具体人物、动作、物件、光线或空间关系表达局部上下文。")
    return [line for line in includes if line.strip()]


def build_quality_gate(slot: dict[str, Any]) -> list[str]:
    return [
        "按手机公众号正文宽度自检：缩小后仍要有质感，不能像 PPT 截图。",
        "如果画面主要靠标题、长句、按钮或清单传达信息，应改成更图像化的表达。",
        "如果信息超过文字预算，应删减文字或改用物件、箭头、距离、光线表达。",
        "如果看起来像营销海报、课件页、深色卡片堆叠或假 UI，应重新生成。",
    ]


def build_variation_note(previous_slots: list[dict[str, Any]], slot: dict[str, Any]) -> str:
    if not previous_slots:
        return "作为首图，聚焦一个主画面。"

    last = previous_slots[-1]
    prior_focuses = "；".join(
        f"{prev['name']}={truncate_text(prev.get('content_focus', ''), 24)}" for prev in previous_slots[-2:]
    )
    return (
        f"与上一张 {last['name']} 拉开差异：上一张是 {last.get('image_type', '')} / {last.get('visual_distance', '')} / {last.get('emotional_tone', '')}，"
        f"这一张改成 {slot.get('image_type', '')} / {slot.get('visual_distance', '')} / {slot.get('emotional_tone', '')}。"
        "至少在角色、场景、景别、构图、情绪、抽象程度、信息密度这 7 个维度里拉开 3 个以上差异。"
        + (f" 前序画面重点：{prior_focuses}。" if prior_focuses else "")
    )


def prompt_line(label: str, value: str, max_chars: int) -> str:
    clean = truncate_text(value, max_chars)
    return f"{label}：{clean}" if clean else ""


def compact_prompt(lines: list[str]) -> str:
    return "\n".join(line for line in lines if line).strip()


def is_method_or_collectible(slot: dict[str, Any]) -> bool:
    return slot.get("visual_mode") == "method_visual" or slot.get("article_type") == "practical-how-to" or slot.get("visual_intent") in {
        "practical_path",
        "checklist_map",
        "explanatory",
    }


def build_selection_criteria(slot: dict[str, Any]) -> list[str]:
    rules = load_image_rules()
    criteria = rules.get("selection_criteria", {})
    return list(criteria.get(slot_kind_for_rules(slot), []))


def build_review_contract(slot: dict[str, Any]) -> dict[str, Any]:
    return {
        "slot": slot.get("name", ""),
        "role": slot.get("role", ""),
        "purpose": slot.get("purpose", ""),
        "local_context": slot.get("local_context", ""),
        "content_focus": slot.get("content_focus", ""),
        "visual_type": slot.get("visual_type", ""),
        "text_budget": slot.get("text_budget", ""),
        "quality_floor": list(load_image_rules().get("quality_floor_rules", [])),
        "selection_criteria": build_selection_criteria(slot),
        "must_include": slot.get("must_include", []),
        "quality_gate": slot.get("quality_gate", []),
        "must_avoid": slot.get("must_avoid", []),
        "variation_note": slot.get("variation_note", ""),
    }


def build_cover_prompt(slot: dict[str, Any], article_summary: str, article_essence: str, route: str = "A") -> str:
    objective = load_image_rules()["slot_objectives"]["cover"]
    if route == "B":
        route_title = objective["route_b_title"]
        route_goal = objective["route_b_goal"]
        route_frame = objective["route_b_frame"]
    else:
        route_title = objective["route_a_title"]
        route_goal = objective["route_a_goal"]
        route_frame = objective["route_a_frame"]
    return compact_prompt([
        route_title,
        f"为中文公众号文章《{slot['article_title']}》生成首页题图。",
        f"目标：{route_goal}",
        prompt_line("画面核心", slot.get("content_focus", ""), 72),
        prompt_line("标题线索", article_summary or article_essence, 44),
        prompt_line("风格", prompt_style_for_slot(slot), 48),
        f"构图：{route_frame} 画面干净，公众号头图质感。",
        *build_prompt_constraints(slot),
    ])


def build_body_prompt(slot: dict[str, Any], article_summary: str, target_body_chars: int, route: str = "A") -> str:
    objective = load_image_rules()["slot_objectives"]["body"]
    if route == "B":
        route_title = objective["route_b_title"]
        route_goal = objective["route_b_goal"]
        route_frame = objective["route_b_frame"]
    else:
        route_title = objective["route_a_title"]
        route_goal = objective["route_a_goal"]
        route_frame = objective["route_a_frame"]
    return compact_prompt([
        route_title,
        f"为中文公众号文章《{slot['article_title']}》生成正文配图 {slot['name']}。",
        f"目标：{route_goal}",
        prompt_line("当前段落", slot.get("local_context", ""), min(target_body_chars, 96)),
        prompt_line("画面核心", slot.get("content_focus", ""), 72),
        prompt_line("风格", prompt_style_for_slot(slot), 36),
        f"构图：{route_frame} 从读者理解和阅读节奏出发。",
        *build_prompt_constraints(slot),
    ])


def build_closing_prompt(slot: dict[str, Any], article_summary: str, article_essence: str, route: str = "A") -> str:
    objective = load_image_rules()["slot_objectives"]["closing"]
    method_like = is_method_or_collectible(slot)
    if route == "B" and method_like:
        route_title = objective["route_b_method_title"]
        route_goal = objective["route_b_method_goal"]
        route_frame = objective["route_b_method_frame"]
    elif route == "B":
        route_title = objective["route_b_symbolic_title"]
        route_goal = objective["route_b_symbolic_goal"]
        route_frame = objective["route_b_symbolic_frame"]
    else:
        route_title = objective["route_a_title"]
        route_goal = objective["route_a_goal"]
        route_frame = objective["route_a_frame"]
    return compact_prompt([
        route_title,
        f"为中文公众号文章《{slot['article_title']}》生成尾图。",
        f"目标：{route_goal}",
        prompt_line("结尾线索", slot.get("local_context", "") or article_summary, 84),
        prompt_line("全文主旨", article_essence or article_summary, 56),
        prompt_line("画面核心", slot.get("content_focus", ""), 64),
        prompt_line("风格", prompt_style_for_slot(slot), 48),
        f"构图：{route_frame}",
        *build_prompt_constraints(slot),
    ])


def empty_image_payload(article_path: Path, article_slug: str, markdown: str) -> dict[str, Any]:
    title = extract_title(markdown, article_path.stem)
    entries = parse_article_entries(markdown)
    text_entries = [entry for entry in entries if entry["kind"] == "text"]
    article_summary = build_article_summary(title, text_entries) if text_entries else ""
    rules = load_image_rules()
    return {
        "kind": "wechat-image-jobs",
        "schema_version": 2,
        "article": {
            "slug": article_slug,
            "title": title,
            "type": detect_article_type(title, text_entries) if text_entries else "general",
            "visual_mode": "no_image",
            "visual_intent": "none",
            "summary": article_summary,
            "essence": build_article_essence(title, text_entries) if text_entries else "",
            "source": str(article_path.resolve()),
            "planning_mode": "no-image",
            "skipped_visuals": [],
        },
        "rules": {"version": rules.get("version"), "sha256": rules_fingerprint(rules)},
        "review_defaults": {
            "must_avoid": list(rules.get("avoid_rules", [])),
            "quality_floor": list(rules.get("quality_floor_rules", [])),
        },
        "slots": [],
        "generation_queue": [],
    }


def build_jobs(
    article_path: Path,
    article_slug: str,
    markdown: str,
    target_body_chars: int,
    min_body_chars: int,
    mode: str = "full",
    max_body_images: int | None = None,
) -> dict[str, Any]:
    if target_body_chars < 1:
        raise SystemExit("--target-body-chars must be a positive integer.")
    if min_body_chars < 1:
        raise SystemExit("--min-body-chars must be a positive integer.")
    if max_body_images is not None and max_body_images < 0:
        raise SystemExit("--max-body-images must be zero or greater.")
    if mode == "no-image":
        return empty_image_payload(article_path, article_slug, markdown)
    if mode not in {"fast", "full"}:
        raise SystemExit(f"Unknown image planning mode: {mode}")
    if mode == "fast" and max_body_images is None:
        max_body_images = 1

    placeholders = parse_placeholders(markdown)
    if not placeholders:
        raise SystemExit(
            "Article markdown is missing {{visual:name}} placeholders. "
            "Write the article with cover/body/closing placeholders before generating images."
        )

    unsupported_placeholders = [
        name
        for name in placeholders
        if name not in {"cover", "closing"} and not BODY_PLACEHOLDER_RE.fullmatch(name)
    ]
    if unsupported_placeholders:
        raise SystemExit(
            "Unsupported visual placeholders: "
            + ", ".join(unsupported_placeholders)
            + ". Use cover, body-N (starting at body-1), or closing."
        )

    all_body_placeholders = sorted(
        [name for name in placeholders if BODY_PLACEHOLDER_RE.fullmatch(name)],
        key=body_placeholder_key,
    )
    body_placeholders = list(all_body_placeholders)
    if max_body_images is not None:
        body_placeholders = body_placeholders[:max_body_images]
    skipped_visuals = [
        name for name in all_body_placeholders if name not in set(body_placeholders)
    ]
    has_cover = "cover" in placeholders
    has_closing = "closing" in placeholders
    if not has_cover or not has_closing:
        raise SystemExit(
            "Article markdown must include both {{visual:cover}} and {{visual:closing}} placeholders before image generation."
        )
    if not body_placeholders and mode == "full" and max_body_images is None:
        raise SystemExit(
            "Article markdown must include at least one {{visual:body-N}} placeholder before image generation."
        )

    title = extract_title(markdown, article_path.stem)
    entries = parse_article_entries(markdown)
    text_entries = [entry for entry in entries if entry["kind"] == "text"]
    if not text_entries:
        raise SystemExit("Article markdown has no usable text blocks for image planning")

    article_type = detect_article_type(title, text_entries)
    visual_intent = detect_visual_intent(title, text_entries)
    visual_mode = detect_visual_mode(title, text_entries, article_type, visual_intent)
    article_summary = build_article_summary(title, text_entries)
    article_essence = build_article_essence(title, text_entries)
    global_visual_style = select_global_visual_style(article_type, visual_intent, visual_mode)
    rules = load_image_rules()

    intro_context, intro_start, intro_end = take_first_entries(text_entries, target_chars=220, min_chars=120)
    closing_context, closing_start, closing_end = take_recent_entries(
        text_entries,
        target_chars=max(220, target_body_chars),
        min_chars=max(120, min_body_chars),
    )
    body_contexts = build_body_context_map(entries, target_chars=target_body_chars, min_chars=min_body_chars)
    fallback_body_role_keys = select_body_role_keys(len(body_placeholders), article_type, visual_intent, visual_mode)

    slots: list[dict[str, Any]] = []

    cover_slot = {
        "index": 1,
        "name": "cover",
        "output": "cover.png",
        "position": "cover",
        "role": "hero_cover",
        "image_type": "cinematic_editorial_key_visual",
        "target_effect": "抓人、建立文章气质、表达标题最吸引人的核心冲突、收益、问题或悬念",
        "article_title": title,
        "article_type": article_type,
        "visual_mode": visual_mode,
        "visual_intent": visual_intent,
        "article_summary": article_summary,
        "article_essence": article_essence,
        "global_visual_style": global_visual_style,
        "local_context": intro_context,
        "content_focus": build_cover_focus(title, intro_context or article_summary, article_summary, visual_intent),
        "visual_distance": "中远景 / 强主视觉",
        "composition": "单一核心主视觉 + 明确视觉重心；主体、关系、后果或收益必须清楚",
        "emotional_tone": "有张力、抓眼、明确；情绪强度由文章标题决定",
        "abstraction_level": "中等抽象",
        "information_density": "中等",
        "source_context": "title_and_intro",
        "purpose": "题图，抓人并建立全文气质",
    }
    cover_slot["must_avoid"] = build_role_avoids(cover_slot["role"])
    cover_slot["visual_type"] = visual_type_key_for_slot(cover_slot)
    cover_slot["text_budget"] = text_budget_key_for_slot(cover_slot)
    cover_slot["must_include"] = build_must_include(cover_slot)
    cover_slot["quality_gate"] = build_quality_gate(cover_slot)
    cover_slot["selection_criteria"] = build_selection_criteria(cover_slot)
    cover_slot["variation_note"] = build_variation_note(slots, cover_slot)
    cover_slot["beat_summary"] = truncate_text(intro_context or article_summary, 180)
    cover_slot["review_contract"] = build_review_contract(cover_slot)
    cover_slot["generation_prompt"] = build_cover_prompt(cover_slot, article_summary, article_essence)
    cover_slot["prompt"] = cover_slot["generation_prompt"]
    slots.append(cover_slot)

    for offset, placeholder in enumerate(body_placeholders, start=1):
        fallback_role_key = fallback_body_role_keys[offset - 1]
        context_info = body_contexts.get(placeholder, {})
        local_context = context_info.get("local_context") or intro_context or article_summary
        role_key = choose_body_role_key(local_context, fallback_role_key, visual_mode)
        if visual_mode == "emotional_illustration" and role_key in STRUCTURAL_VISUAL_ROLES:
            role_key = "inline_symbolic_scene"
        template = BODY_ROLE_LIBRARY[role_key]
        start_ord = context_info.get("start_ordinal")
        end_ord = context_info.get("end_ordinal")
        slot = {
            "index": len(slots) + 1,
            "name": placeholder,
            "output": f"{placeholder}.png",
            "position": f"after_paragraph_{end_ord}" if end_ord else f"body_slot_{offset}",
            "article_title": title,
            "article_type": article_type,
            "visual_mode": visual_mode,
            "visual_intent": visual_intent,
            "article_summary": article_summary,
            "article_essence": article_essence,
            "global_visual_style": global_visual_style,
            "local_context": local_context,
            "target_body_chars": target_body_chars,
            "source_context": (
                f"paragraph_{start_ord}_to_{end_ord}; since_previous_visual_placeholder"
                if start_ord and end_ord
                else "since_previous_visual_placeholder"
            ),
            "purpose": f"正文第 {offset} 张配图，服务当前位置的局部叙事",
            **template,
        }
        slot["content_focus"] = build_content_focus(slot["role"], local_context, article_summary)
        slot["must_avoid"] = build_role_avoids(slot["role"])
        slot["visual_type"] = visual_type_key_for_slot(slot)
        slot["text_budget"] = text_budget_key_for_slot(slot)
        slot["must_include"] = build_must_include(slot)
        slot["quality_gate"] = build_quality_gate(slot)
        slot["selection_criteria"] = build_selection_criteria(slot)
        slot["variation_note"] = build_variation_note(slots, slot)
        slot["beat_summary"] = truncate_text(local_context, 180)
        slot["review_contract"] = build_review_contract(slot)
        slot["generation_prompt"] = build_body_prompt(slot, article_summary, target_body_chars)
        slot["prompt"] = slot["generation_prompt"]
        slots.append(slot)

    closing_slot = {
        "index": len(slots) + 1,
        "name": "closing",
        "output": "closing.png",
        "position": "ending",
        "role": "closing_image",
        "image_type": "poetic_closing_visual",
        "target_effect": "收束全文，留下余味、余韵和转发冲动",
        "article_title": title,
        "article_type": article_type,
        "visual_mode": visual_mode,
        "visual_intent": visual_intent,
        "article_summary": article_summary,
        "article_essence": article_essence,
        "global_visual_style": global_visual_style,
        "local_context": closing_context,
        "content_focus": build_content_focus("closing_image", closing_context or article_summary, article_summary),
        "visual_distance": "远景或安静的中景",
        "composition": "留白更多，收束而不拥挤；可以用一个隐喻画面表达最终判断",
        "emotional_tone": "沉静、开放、有余味",
        "abstraction_level": "中高抽象",
        "information_density": "低",
        "source_context": "conclusion",
        "purpose": "尾图，收束文章结论并留下情绪余味",
    }
    closing_slot["must_avoid"] = build_role_avoids(closing_slot["role"])
    closing_slot["visual_type"] = visual_type_key_for_slot(closing_slot)
    closing_slot["text_budget"] = text_budget_key_for_slot(closing_slot)
    closing_slot["must_include"] = build_must_include(closing_slot)
    closing_slot["quality_gate"] = build_quality_gate(closing_slot)
    closing_slot["selection_criteria"] = build_selection_criteria(closing_slot)
    closing_slot["variation_note"] = build_variation_note(slots, closing_slot)
    closing_slot["beat_summary"] = truncate_text(closing_context or article_summary, 180)
    closing_slot["review_contract"] = build_review_contract(closing_slot)
    closing_slot["generation_prompt"] = build_closing_prompt(closing_slot, article_summary, article_essence)
    closing_slot["prompt"] = closing_slot["generation_prompt"]
    slots.append(closing_slot)

    # Canonical v2 contract: compatibility copies are intentionally omitted.
    article_record = {
        "slug": article_slug,
        "title": title,
        "type": article_type,
        "visual_mode": visual_mode,
        "visual_intent": visual_intent,
        "summary": article_summary,
        "essence": article_essence,
        "global_visual_style": global_visual_style,
        "source": str(article_path.resolve()),
        "planning_mode": mode,
        "skipped_visuals": skipped_visuals,
    }
    canonical_slots: list[dict[str, Any]] = []
    generation_queue: list[dict[str, str]] = []
    for slot in slots:
        item = {key: slot[key] for key in ("index", "name") if key in slot}
        item["output"] = slot.get("output") or f"{slot['name']}.png"
        for key in (
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
        ):
            if key in slot:
                item[key] = slot[key]
        canonical_slots.append(item)
        generation_queue.append(
            {
                "slot": item["name"],
                "output": item["output"],
                "generation_prompt": str(
                    slot.get("generation_prompt") or slot.get("prompt") or ""
                ).strip(),
            }
        )
    return normalize_image_jobs(
        {
            "kind": "wechat-image-jobs",
            "schema_version": 2,
            "article": article_record,
            "rules": {
                "version": rules.get("version"),
                "sha256": rules_fingerprint(rules),
            },
            "review_defaults": {
                "must_avoid": list(rules.get("avoid_rules", [])),
                "quality_floor": list(rules.get("quality_floor_rules", [])),
            },
            "slots": canonical_slots,
            "generation_queue": generation_queue,
        }
    )


def existing_image(images_dir: Path, name: str) -> bool:
    exact = images_dir / name
    if exact.exists():
        return True
    if Path(name).suffix:
        return False
    for suffix in (".png", ".jpg", ".jpeg", ".webp"):
        if (images_dir / f"{name}{suffix}").exists():
            return True
    return False


def filter_missing_jobs(payload: dict[str, Any], images_dir: Path) -> dict[str, Any]:
    return filter_missing_image_jobs(normalize_image_jobs(payload), lambda output: existing_image(images_dir, output))


def main() -> None:
    args = parse_args()
    if args.missing_only and not args.images_dir:
        raise SystemExit("--missing-only requires --images-dir.")
    article = args.article.resolve()
    markdown, _article_metadata = builder.split_front_matter(article.read_text(encoding="utf-8"))
    title = extract_title(markdown, article.stem)
    article_slug = args.article_slug or infer_article_slug(article, title)
    payload = build_jobs(
        article_path=article,
        article_slug=article_slug,
        markdown=markdown,
        target_body_chars=args.target_body_chars,
        min_body_chars=args.min_body_chars,
        mode=args.mode,
        max_body_images=args.max_body_images,
    )
    if args.missing_only:
        payload = filter_missing_jobs(payload, args.images_dir.resolve())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(args.out, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(f"Wrote {args.out.resolve()}")
    if args.debug_plan:
        print(render_image_plan_markdown(payload))


if __name__ == "__main__":
    main()
