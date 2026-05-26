#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

import build_wechat_article_workbench as builder


PLACEHOLDER_RE = re.compile(r"\{\{visual:([a-zA-Z0-9_-]+)\}\}")
TITLE_RE = re.compile(r"^\s*#\s+(.+?)\s*$", re.M)
REFERENCE_HEADING_RE = re.compile(r"^\s*#{1,6}\s*(参考来源|参考资料|参考|references?)\s*$", re.I | re.M)
CHINESE_CHAR_RE = re.compile(r"[\u4e00-\u9fff]")


# 通用视觉信号：只判断“文章修辞功能”，不绑定某一个具体行业或题材。
SIGNAL_PATTERNS: dict[str, re.Pattern[str]] = {
    "problem": re.compile(r"问题|痛点|难点|风险|危机|代价|误区|陷阱|焦虑|压力|冲突|失败|困境|瓶颈|挑战|担心|不安|损失|低效|混乱|被动|淘汰|替代|取代|冲击"),
    "promise": re.compile(r"如何|怎么|方法|步骤|指南|清单|路径|建议|方案|策略|技巧|避坑|提升|解决|做好|学会|掌握|快速|高效"),
    "process": re.compile(r"第一|第二|第三|首先|其次|然后|接着|最后|先|再|下一步|步骤|流程|路径|路线|阶段|环节|闭环|链路"),
    "list": re.compile(r"哪些|几个|清单|盘点|类型|分类|包括|分为|主要有|这几类|维度|因素|原因|场景|环节|模块|要点|关键词"),
    "compare": re.compile(r"以前|过去|现在|不再|不是.+而是|对比|区别|差异|从.+到|传统|新旧|前后|左右|相比|变化|升级|转向|替换"),
    "evidence": re.compile(r"数据|比例|增长|下降|案例|报告|研究|调查|统计|成本|效率|收入|规模|数量|趋势|证据|事实|样本|指标|%|％|倍|亿|万"),
    "mechanism": re.compile(r"本质|核心|关键|原因|因为|机制|逻辑|为什么|意味着|真正|底层|原理|规律|决定|影响"),
    "emotion": re.compile(r"焦虑|恐惧|兴奋|震撼|失落|希望|无奈|愤怒|安心|安全感|压迫|孤独|豁然|共鸣|扎心|残酷|委屈|疲惫|沉默|遗憾|勇气|释然|崩溃|倔强|温柔|清醒"),
    "story": re.compile(r"故事|人物|采访|经历|一天|现场|案例|客户|团队|老板|员工|朋友|普通人|一家|一次|亲历|父母|孩子|年轻人|中年人|夜里|路上|饭桌|办公室|出租屋"),
    "principle": re.compile(r"道理|人生|成长|关系|情绪|选择|告别|和解|成熟|清醒|底气|边界|热爱|困住|松弛|内耗|自洽|命运|生活|普通人"),
}

COMMON_AVOIDS = [
    "不要做成 crowded collage、thumbnail wall、many tiny panels、满屏碎片拼贴。",
    "不要用一张图总结全文；每张图只服务自己的位置和任务。",
    "不要复用上一张图的主体、构图、视觉隐喻或情绪。",
    "不要做 generic wallpaper、空洞科技背景、无意义光效、普通摆拍。",
    "不要做假 UI 截图，不要出现不可读的小字墙。",
    "只有角色明确要求方法图、分析图或证据图时，才允许清晰、克制、可读的信息图；禁止低质量复杂信息图。",
]

EMOTIONAL_VISUAL_ROLES = {
    "inline_tension",
    "inline_scene",
    "inline_metaphor",
    "inline_emotion",
    "inline_silence",
    "inline_symbolic_scene",
    "inline_human_moment",
}

STRUCTURAL_VISUAL_ROLES = {
    "inline_steps",
    "inline_checklist",
    "inline_data_card",
    "inline_evidence",
}

EMOTIONAL_ILLUSTRATION_AVOIDS = [
    "禁止做编号、一二三、步骤图、流程图、箭头路线、清单卡片、信息图、PPT结构页、图标矩阵或假 UI 面板。",
    "禁止把抽象道理直接写成版式文字；画面应通过人物、空间、光线、动作、物件隐喻来表达。",
    "禁止用万能办公桌、抽象科技背景、彩色模块卡片来代替情绪画面。",
]

BODY_ROLE_LIBRARY: dict[str, dict[str, str]] = {
    "inline_explanation": {
        "role": "inline_explanation",
        "image_type": "clean_visual_explanation",
        "target_effect": "把这一段的关键机制讲清楚",
        "visual_distance": "中景 / 单焦点",
        "composition": "一个主对象 + 2到3个辅助元素；可用少量箭头、关系线或简洁标注",
        "emotional_tone": "冷静、清楚、可信",
        "abstraction_level": "低到中等抽象",
        "information_density": "中等",
    },
    "inline_scene": {
        "role": "inline_scene",
        "image_type": "specific_scene",
        "target_effect": "把这一段的真实场景、人物处境或使用现场画出来",
        "visual_distance": "中景或中远景 / 有环境信息",
        "composition": "真实场景驱动，必须有明确动作、关系或处境，不要只是静态摆拍",
        "emotional_tone": "有在场感、有代入感",
        "abstraction_level": "低抽象",
        "information_density": "中低",
    },
    "inline_tension": {
        "role": "inline_tension",
        "image_type": "emotional_tension_scene",
        "target_effect": "把这一段的压力、矛盾、风险、选择困难或情绪冲突画出来",
        "visual_distance": "中景 / 人物与压力源或矛盾关系同框",
        "composition": "人物、压力源、后果或选择必须形成一眼可见的关系",
        "emotional_tone": "有张力、有代入、有传播感",
        "abstraction_level": "低到中等抽象",
        "information_density": "中等",
    },
    "inline_contrast": {
        "role": "inline_contrast",
        "image_type": "before_after_or_side_by_side_comparison",
        "target_effect": "把这一段的新旧差异、强弱差异、路线差异或判断差异拉开",
        "visual_distance": "正视角或中景 / 对比式构图",
        "composition": "左右分区、前后对比或上下对照；差异必须一眼看懂",
        "emotional_tone": "理性、有张力",
        "abstraction_level": "中等抽象",
        "information_density": "中等到中高",
    },
    "inline_steps": {
        "role": "inline_steps",
        "image_type": "step_by_step_process_graphic",
        "target_effect": "把这一段的方法、流程、路径或先后顺序画成清楚步骤",
        "visual_distance": "正视角 / 流程视角",
        "composition": "3到5个步骤节点，清晰箭头连接，每步一个短标签或图标",
        "emotional_tone": "清楚、可执行、有掌控感",
        "abstraction_level": "中等抽象",
        "information_density": "中高",
    },
    "inline_checklist": {
        "role": "inline_checklist",
        "image_type": "structured_checklist_or_taxonomy",
        "target_effect": "把这一段的类别、清单、要点、场景或环节归纳成一张图",
        "visual_distance": "正视角 / 分类卡片视角",
        "composition": "3到6个清晰分类卡片或勾选项，每项有图标和极短标签",
        "emotional_tone": "清楚、直接、有收获感",
        "abstraction_level": "中等抽象",
        "information_density": "中高",
    },
    "inline_data_card": {
        "role": "inline_data_card",
        "image_type": "compact_editorial_infographic",
        "target_effect": "用高信息密度但克制的方式，把这一段的结构、判断和结论压缩成一张可读图",
        "visual_distance": "信息卡片视角 / 轻量图解",
        "composition": "一个主结论 + 2到4个信息模块 + 简洁箭头、图标或关系线",
        "emotional_tone": "理性、有洞察、信息量强",
        "abstraction_level": "中等抽象",
        "information_density": "高但可读",
    },
    "inline_evidence": {
        "role": "inline_evidence",
        "image_type": "evidence_or_data_visual",
        "target_effect": "把这一段的数据、案例、证据或趋势画得可信、清楚",
        "visual_distance": "图表与场景结合 / 编辑图解视角",
        "composition": "一个证据中心，例如趋势线、对比柱、案例卡或文件证据；不要伪造复杂数字",
        "emotional_tone": "可信、扎实、有判断依据",
        "abstraction_level": "中等抽象",
        "information_density": "中高",
    },
    "inline_detail": {
        "role": "inline_detail",
        "image_type": "focused_detail",
        "target_effect": "放大这一段里最具体的一个动作、对象、界面、材料或局部细节",
        "visual_distance": "近景 / 特写",
        "composition": "细节放大，背景克制，画面只保留一个核心动作或对象",
        "emotional_tone": "专注、具体、可执行",
        "abstraction_level": "低抽象",
        "information_density": "低到中等",
    },
    "inline_metaphor": {
        "role": "inline_metaphor",
        "image_type": "conceptual_metaphor",
        "target_effect": "用一个克制但明确的隐喻延展这一段判断",
        "visual_distance": "中景或远景 / 明确隐喻中心",
        "composition": "单个隐喻主视觉，不要散乱符号拼贴",
        "emotional_tone": "有想象力，但克制",
        "abstraction_level": "中高抽象",
        "information_density": "低",
    },
    "inline_extension": {
        "role": "inline_extension",
        "image_type": "future_or_next_step_scene",
        "target_effect": "顺着这一段观点往前推一步，画出下一步可能发生的场景",
        "visual_distance": "中远景 / 带纵深",
        "composition": "未来感或延展场景，但仍围绕一个中心动作或变化",
        "emotional_tone": "打开感、前瞻感",
        "abstraction_level": "中等抽象",
        "information_density": "中低",
    },
    "inline_emotion": {
        "role": "inline_emotion",
        "image_type": "emotional_pause_visual",
        "target_effect": "让读者在这一段停一下，感受到情绪或判断的分量",
        "visual_distance": "远景或安静中景",
        "composition": "留白更多，节奏放慢，但必须有明确情绪来源",
        "emotional_tone": "沉静、震撼、豁然或有余味",
        "abstraction_level": "中高抽象",
        "information_density": "低",
    },
    "inline_silence": {
        "role": "inline_silence",
        "image_type": "quiet_editorial_illustration",
        "target_effect": "把这一段的余味、迟疑、孤独、释然或没有说出口的情绪画出来",
        "visual_distance": "远景或安静中景 / 留白明显",
        "composition": "一个人物或一个关键物件处在有情绪的空间里；光线、阴影、距离感承担叙事",
        "emotional_tone": "克制、沉静、有余味",
        "abstraction_level": "中等抽象",
        "information_density": "低",
    },
    "inline_symbolic_scene": {
        "role": "inline_symbolic_scene",
        "image_type": "symbolic_story_illustration",
        "target_effect": "把这一段的道理变成一个有冲击力但不说教的象征性场景",
        "visual_distance": "中远景 / 强主视觉",
        "composition": "一个清晰象征物或空间关系承载判断；不要散乱符号拼贴",
        "emotional_tone": "有冲击力、有隐喻感、符合文章调性",
        "abstraction_level": "中高抽象",
        "information_density": "低到中等",
    },
    "inline_human_moment": {
        "role": "inline_human_moment",
        "image_type": "cinematic_human_moment",
        "target_effect": "把这一段落到一个具体人的瞬间，让读者先代入再理解道理",
        "visual_distance": "中景或近景 / 人物瞬间",
        "composition": "一个具体动作、表情或停顿，配合真实空间和少量关键物件",
        "emotional_tone": "真实、有温度、有故事感",
        "abstraction_level": "低到中等抽象",
        "information_density": "低",
    },
}


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
    match = REFERENCE_HEADING_RE.search(markdown)
    return markdown[: match.start()].rstrip() if match else markdown


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
        "industry-analysis": "高级商业编辑感，重点是判断、结构和变化，不是炫技 collage。",
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
        "method_visual": "当前采用方法图语法：可以使用步骤、箭头、清单、对比、信息卡，但必须服务具体方法。",
        "emotional_illustration": "当前采用情绪插图语法：优先人物处境、空间氛围、光线、动作、物件隐喻和视觉冲击；禁止把正文图做成编号步骤图、流程图、清单卡或信息图。",
        "analysis_visual": "当前采用分析图语法：优先证据、对比、机制和克制隐喻，少用流程图，避免装饰化。",
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
        base_sequence = ["inline_explanation", "inline_contrast", "inline_evidence", "inline_detail", "inline_metaphor", "inline_scene", "inline_emotion"]
        while len(base_sequence) < count:
            base_sequence.extend(["inline_explanation", "inline_contrast", "inline_detail", "inline_metaphor"])
        return base_sequence[:count]

    presets = {
        "emotional_hook": ["inline_tension", "inline_data_card", "inline_contrast", "inline_checklist", "inline_detail", "inline_metaphor", "inline_emotion"],
        "practical_path": ["inline_steps", "inline_detail", "inline_checklist", "inline_scene", "inline_contrast", "inline_data_card", "inline_emotion"],
        "checklist_map": ["inline_checklist", "inline_data_card", "inline_contrast", "inline_explanation", "inline_steps", "inline_detail", "inline_emotion"],
        "contrast": ["inline_contrast", "inline_data_card", "inline_tension", "inline_detail", "inline_checklist", "inline_metaphor", "inline_emotion"],
        "evidence_led": ["inline_evidence", "inline_data_card", "inline_contrast", "inline_explanation", "inline_detail", "inline_checklist", "inline_emotion"],
        "explanatory": ["inline_explanation", "inline_data_card", "inline_detail", "inline_contrast", "inline_checklist", "inline_metaphor", "inline_emotion"],
        "story_scene": ["inline_scene", "inline_detail", "inline_tension", "inline_emotion", "inline_metaphor", "inline_extension", "inline_explanation"],
        "mixed": ["inline_tension", "inline_data_card", "inline_checklist", "inline_contrast", "inline_steps", "inline_detail", "inline_emotion"],
    }
    base_sequence = list(presets.get(visual_intent, presets["mixed"]))
    if count <= len(base_sequence):
        return base_sequence[:count]
    extras = ["inline_data_card", "inline_checklist", "inline_steps", "inline_evidence", "inline_detail", "inline_scene", "inline_metaphor", "inline_contrast", "inline_extension", "inline_emotion"]
    while len(base_sequence) < count:
        base_sequence.append(extras[(len(base_sequence) - len(presets.get(visual_intent, presets["mixed"]))) % len(extras)])
    return base_sequence[:count]


def choose_body_role_key(local_context: str, fallback_role_key: str, visual_mode: str) -> str:
    """Route each body image by paragraph function, not by article topic."""
    text = local_context or ""
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
            return "inline_explanation"
        return fallback_role_key if fallback_role_key not in {"inline_steps", "inline_checklist"} else "inline_explanation"

    if SIGNAL_PATTERNS["process"].search(text):
        return "inline_steps"
    if SIGNAL_PATTERNS["compare"].search(text):
        return "inline_contrast"
    if SIGNAL_PATTERNS["list"].search(text):
        return "inline_checklist"
    if SIGNAL_PATTERNS["evidence"].search(text):
        return "inline_evidence"
    if SIGNAL_PATTERNS["problem"].search(text) or SIGNAL_PATTERNS["emotion"].search(text):
        return "inline_tension"
    if SIGNAL_PATTERNS["mechanism"].search(text):
        return "inline_data_card"
    if SIGNAL_PATTERNS["story"].search(text):
        return "inline_scene"
    return fallback_role_key


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
    return f"标题优先：{title}。{intent_wording.get(visual_intent, intent_wording['mixed'])}；结合导语线索：{local_focus}"


def build_content_focus(role: str, local_context: str, article_summary: str) -> str:
    if role == "closing_image":
        focus = last_sentence(local_context, 90) or article_summary
    elif role == "hero_cover":
        focus = select_visual_sentence(local_context, 90) or first_sentence(article_summary, 90)
    else:
        focus = select_visual_sentence(local_context, 90) or article_summary

    mapping = {
        "hero_cover": f"只抓标题承诺里最有点击力的冲突、收益或悬念：{focus}",
        "inline_explanation": f"把这一段最关键的机制讲清楚：{focus}",
        "inline_scene": f"把这一段的具体现场、人物处境或使用场景画出来：{focus}",
        "inline_tension": f"把这一段的压力、矛盾、风险或情绪冲突直接画出来：{focus}",
        "inline_contrast": f"把这一段里的差异拉开，画出对比关系：{focus}",
        "inline_steps": f"把这一段拆成清晰步骤、路径或流程：{focus}",
        "inline_checklist": f"把这一段归纳成清晰类别、清单、场景或环节：{focus}",
        "inline_data_card": f"把这一段压缩成高信息密度但可读的结构化信息卡：{focus}",
        "inline_evidence": f"把这一段的数据、案例、证据或趋势画得可信清楚：{focus}",
        "inline_detail": f"放大这一段里最具体的一个动作、对象或局部：{focus}",
        "inline_metaphor": f"用一个克制但明确的隐喻表达这一段判断：{focus}",
        "inline_extension": f"顺着这一段观点往前推一步，画出下一步会发生什么：{focus}",
        "inline_emotion": f"让读者感受到这一段的情绪或判断分量：{focus}",
        "inline_silence": f"把这一段没有直接说出口的情绪、停顿或余味变成安静画面：{focus}",
        "inline_symbolic_scene": f"把这一段的抽象道理转成一个有冲击力的象征性场景：{focus}",
        "inline_human_moment": f"把这一段落到一个具体人的瞬间，先让读者代入：{focus}",
        "closing_image": f"表达读完整篇文章之后留下的感觉，而不是再总结一遍全文：{focus}",
    }
    return mapping.get(role, focus)


def build_role_avoids(role: str) -> list[str]:
    specific = {
        "hero_cover": [
            "不要把题图做成复杂信息图。",
            "不要塞满很多小图拼贴。",
            "不要把题图画成和标题承诺无关的普通场景。",
            "不要让导语里的局部动作覆盖标题里的核心冲突或核心收益。",
        ],
        "inline_explanation": [
            "不要重复题图的大主题海报感。",
            "不要做空泛背景；必须解释一个具体机制。",
        ],
        "inline_scene": [
            "不要退化成抽象概念图。",
            "不要只有环境，没有动作、处境或关系。",
        ],
        "inline_tension": [
            "不要把压力画得太温和。",
            "不要只有情绪表情，却看不到压力源或矛盾关系。",
        ],
        "inline_contrast": [
            "不要做成复杂表格。",
            "不要让对比双方看起来差不多。",
        ],
        "inline_steps": [
            "不要把步骤画成散乱图标。",
            "不要超过5个步骤，不要长句堆满画面。",
            "不要省略箭头或先后关系。",
        ],
        "inline_checklist": [
            "不要做成密密麻麻的表格。",
            "不要超过6个分类项。",
            "不要只有装饰图标，没有清晰类别。",
        ],
        "inline_data_card": [
            "不要做成PPT堆料。",
            "不要用一堆假数据和无法阅读的小字。",
            "不要牺牲可读性换信息量。",
        ],
        "inline_evidence": [
            "不要伪造具体数字。",
            "不要堆满无法阅读的图表。",
            "不要把证据画成空洞符号。",
        ],
        "inline_detail": [
            "不要又回到大而全的场景总览。",
            "不要一张图里出现太多主体。",
        ],
        "inline_metaphor": [
            "不要把隐喻做得太满太碎。",
            "不要变成廉价光效海报。",
        ],
        "inline_extension": [
            "不要复述当前段落已经讲过的静态画面。",
            "不要把未来感做成空洞背景。",
        ],
        "inline_emotion": [
            "不要重新解释机制。",
            "不要把低信息密度画面又做成信息图。",
        ],
        "inline_silence": [
            *EMOTIONAL_ILLUSTRATION_AVOIDS,
            "不要把安静画面做成空洞风景照；必须有情绪来源或关键物件。",
            "不要用大段文字解释情绪。",
        ],
        "inline_symbolic_scene": [
            *EMOTIONAL_ILLUSTRATION_AVOIDS,
            "不要堆砌多个隐喻；只保留一个强主视觉。",
            "不要做廉价震撼海报或无意义光效。",
        ],
        "inline_human_moment": [
            *EMOTIONAL_ILLUSTRATION_AVOIDS,
            "不要摆拍式假笑、会议室握手或普通办公桌。",
            "不要只有人物特写而看不到处境。",
        ],
        "closing_image": [
            "不要再做题图式强冲击海报。",
            "不要再解释全文，不要再做信息图。",
            "不要重复正文中间图的场景。",
        ],
    }
    return COMMON_AVOIDS + specific.get(role, [])


def build_must_include(slot: dict[str, Any]) -> list[str]:
    role = slot.get("role", "")
    includes: list[str] = []
    if role == "hero_cover":
        includes.extend([
            "必须从标题里抽出一个明确主视觉：人物、对象、场景、矛盾、收益或结果，不能只画泛泛背景。",
            "必须让读者3秒内感受到标题承诺：冲突、方法、清单、对比、证据、故事或机制中的至少一种。",
            "画面要有一个清晰视觉中心，不要平均铺满。",
        ])
    elif role == "inline_tension":
        includes.extend([
            "必须同框呈现处境主体和压力源/矛盾关系。",
            "情绪或张力必须明确，不能是平静普通场景。",
        ])
    elif role == "inline_steps":
        includes.extend([
            "必须有清晰的1-2-3或3到5步流程节点。",
            "必须有箭头、编号或明确先后顺序。",
        ])
    elif role == "inline_checklist":
        includes.extend([
            "必须有3到6个清晰分类、勾选项、场景项或要点。",
            "每个分类必须对应局部上下文里的一个具体对象、因素或环节。",
        ])
    elif role == "inline_data_card":
        includes.extend([
            "必须有一个主结论区和2到4个信息模块。",
            "必须信息密度高但可读，不要假装复杂。",
        ])
    elif role == "inline_evidence":
        includes.extend([
            "必须有明确证据中心：趋势、案例、文件、对比、样本或事实依据。",
            "不能编造过于具体的数据；可用抽象图表表达趋势。",
        ])
    elif role == "inline_contrast":
        includes.extend([
            "必须有清晰的新旧、前后、左右或选择对比关系。",
            "对比双方的差异必须一眼可见。",
        ])
    elif role == "inline_explanation":
        includes.append("必须画出因果、结构、机制或关系中的一个，不要只画装饰场景。")
    elif role == "inline_scene":
        includes.append("必须有具体人物、对象或动作，能对应局部上下文。")
    elif role == "inline_silence":
        includes.extend([
            "必须通过空间、光线、距离感或关键物件表达情绪，不靠文字说明。",
            "必须保留足够留白，让画面像一次阅读停顿。",
        ])
    elif role == "inline_symbolic_scene":
        includes.extend([
            "必须有一个清晰象征物或空间关系承载这段道理。",
            "必须让读者先感受到冲击或余味，再理解观点。",
        ])
    elif role == "inline_human_moment":
        includes.extend([
            "必须有一个具体人物瞬间：动作、表情、停顿或选择。",
            "必须用环境和物件说明处境，而不是用标签文字说明。",
        ])
    elif role == "closing_image":
        includes.append("必须收束到一个余味画面：开放、沉静、启发或提醒，而不是重复解释。")
    return includes


def build_quality_gate(slot: dict[str, Any]) -> list[str]:
    role = slot.get("role", "")
    base = [
        "生成前先自检：这张图必须推动阅读，不能只是填空位。",
        "至少满足以下三项之一：情绪强 / 信息强 / 过程强。",
        "如果看图3秒内猜不出标题或该段大意，应改成更直接的构图。",
        "如果画面退化为普通摆拍、普通桌面、普通背景图，应主动改图。",
    ]
    role_gate = {
        "hero_cover": "题图优先拉点击：必须抓住标题承诺，不被首段细节带偏。",
        "inline_tension": "本图优先情绪强：主体、压力源和关系必须清楚。",
        "inline_steps": "本图优先过程强：步骤和箭头要清楚。",
        "inline_checklist": "本图优先信息强：类别和清单要清楚。",
        "inline_data_card": "本图优先信息强：主结论和模块关系要清楚。",
        "inline_evidence": "本图优先可信：证据中心和趋势关系要清楚。",
        "inline_contrast": "本图优先差异强：对比关系要拉开。",
        "inline_silence": "本图优先余味强：留白、情绪来源和关键物件必须清楚。",
        "inline_symbolic_scene": "本图优先隐喻强：用一个象征性画面承载道理，不许变成结构图。",
        "inline_human_moment": "本图优先代入强：具体人物瞬间和处境必须清楚。",
        "closing_image": "尾图优先余味：收束而不是重复解释。",
    }
    if role in role_gate:
        base.append(role_gate[role])
    return base


def build_variation_note(previous_slots: list[dict[str, Any]], slot: dict[str, Any]) -> str:
    if not previous_slots:
        return "作为首图，聚焦一个主画面，不要试图总结全文的全部细节。"

    last = previous_slots[-1]
    prior_focuses = "；".join(
        f"{prev['name']}={truncate_text(prev.get('content_focus', ''), 24)}" for prev in previous_slots[-2:]
    )
    return (
        f"与上一张 {last['name']} 拉开差异：上一张是 {last.get('image_type', '')} / {last.get('visual_distance', '')} / {last.get('emotional_tone', '')}，"
        f"这一张改成 {slot.get('image_type', '')} / {slot.get('visual_distance', '')} / {slot.get('emotional_tone', '')}。"
        "至少在角色、场景、景别、构图、情绪、抽象程度、信息密度这 7 个维度里拉开 3 个以上差异。"
        + (f" 不要重复这些前序画面重点：{prior_focuses}。" if prior_focuses else "")
    )


def format_bullets(lines: list[str]) -> str:
    return "\n".join(f"- {line}" for line in lines if line)


def build_cover_prompt(slot: dict[str, Any], article_summary: str, article_essence: str) -> str:
    return (
        f"为中文公众号文章《{slot['article_title']}》生成题图。\n"
        f"视觉意图：{slot['visual_intent']}\n"
        f"图片角色：{slot['role']}\n"
        f"图片类型：{slot['image_type']}\n"
        f"目标效果：{slot['target_effect']}\n"
        f"整体视觉风格：{slot['global_visual_style']}\n"
        f"全文摘要：{article_summary}\n"
        f"全文主旨线索：{article_essence}\n"
        f"开场局部上下文：{slot['local_context']}\n"
        f"这张图具体要画：{slot['content_focus']}\n"
        f"建议景别：{slot['visual_distance']}\n"
        f"构图方式：{slot['composition']}\n"
        f"情绪：{slot['emotional_tone']}\n"
        f"抽象程度：{slot['abstraction_level']}\n"
        f"信息密度：{slot['information_density']}\n\n"
        "题图必须标题优先：先看标题给读者的承诺，再看导语补充的细节。"
        "不要被首段里的一个局部动作带偏。"
        "这张题图要像导演分镜里的开场主视觉：抓人、建立气质、聚焦一个最有传播性的冲突、收益、问题或悬念。"
        "不要把全文知识点全塞进去，不要嵌长字，不要复杂信息图，不要很多小图片拼贴。\n\n"
        "必须包含：\n"
        f"{format_bullets(slot.get('must_include', []))}\n\n"
        "质量门槛：\n"
        f"{format_bullets(slot.get('quality_gate', []))}\n\n"
        "反重复规则：\n"
        f"{format_bullets([slot['variation_note']])}\n\n"
        "必须避免：\n"
        f"{format_bullets(slot['must_avoid'])}"
    )


def build_body_prompt(slot: dict[str, Any], article_summary: str, target_body_chars: int) -> str:
    if slot.get("visual_mode") == "emotional_illustration":
        mode_instruction = (
            "这篇文章当前走情绪插图逻辑。把抽象判断转成一个具体画面：谁在什么空间里，"
            "处于什么情绪，画面里有什么关键物件、光线、距离或冲突。"
            "不要解释道理本身，要让读者先感受到这个道理。"
            "严禁编号、一二三、箭头、流程图、清单卡、信息图、UI面板、图标矩阵和文字版式。"
        )
    elif slot.get("visual_mode") == "method_visual":
        mode_instruction = (
            "这篇文章当前走方法图逻辑。如果这一段确实在讲方法、步骤、清单、证据或对比，"
            "可以使用清晰克制的图解方式；不要因为追求氛围而牺牲可执行性。"
        )
    else:
        mode_instruction = (
            "这篇文章当前走分析图逻辑。优先表达机制、证据、对比或具体场景；少用流程图，"
            "只有局部上下文真的在讲步骤时才使用步骤结构。"
        )
    return (
        f"为中文公众号文章《{slot['article_title']}》生成第 {slot['index']} 张正文配图。\n"
        f"视觉模式：{slot['visual_mode']}\n"
        f"视觉意图：{slot['visual_intent']}\n"
        f"图片角色：{slot['role']}\n"
        f"图片类型：{slot['image_type']}\n"
        f"目标效果：{slot['target_effect']}\n"
        f"整体视觉风格：{slot['global_visual_style']}\n"
        f"全文摘要（只用于保持整体气质一致）：{article_summary}\n"
        f"这张图只服务于占位符前约 {target_body_chars} 个中文字符的正文，不允许改写成题图或尾图。\n"
        f"局部上下文：{slot['local_context']}\n"
        f"这张图具体要画：{slot['content_focus']}\n"
        f"建议景别：{slot['visual_distance']}\n"
        f"构图方式：{slot['composition']}\n"
        f"情绪：{slot['emotional_tone']}\n"
        f"抽象程度：{slot['abstraction_level']}\n"
        f"信息密度：{slot['information_density']}\n\n"
        "像导演分镜一样处理这张图：只表达当前位置的一个画面重点，帮助理解、停顿或推进阅读。"
        "不要把整篇文章再讲一遍。"
        f"{mode_instruction}\n\n"
        "必须包含：\n"
        f"{format_bullets(slot.get('must_include', []))}\n\n"
        "质量门槛：\n"
        f"{format_bullets(slot.get('quality_gate', []))}\n\n"
        "反重复规则：\n"
        f"{format_bullets([slot['variation_note']])}\n\n"
        "必须避免：\n"
        f"{format_bullets(slot['must_avoid'])}"
    )


def build_closing_prompt(slot: dict[str, Any], article_summary: str, article_essence: str) -> str:
    return (
        f"为中文公众号文章《{slot['article_title']}》生成尾图。\n"
        f"视觉意图：{slot['visual_intent']}\n"
        f"图片角色：{slot['role']}\n"
        f"图片类型：{slot['image_type']}\n"
        f"目标效果：{slot['target_effect']}\n"
        f"整体视觉风格：{slot['global_visual_style']}\n"
        f"全文摘要：{article_summary}\n"
        f"全文主旨线索：{article_essence}\n"
        f"结尾局部上下文：{slot['local_context']}\n"
        f"这张图具体要画：{slot['content_focus']}\n"
        f"建议景别：{slot['visual_distance']}\n"
        f"构图方式：{slot['composition']}\n"
        f"情绪：{slot['emotional_tone']}\n"
        f"抽象程度：{slot['abstraction_level']}\n"
        f"信息密度：{slot['information_density']}\n\n"
        "这张尾图要负责收束全文、留下余味，不要再像题图一样强冲击，也不要再像正文图一样解释机制。"
        "不要嵌长字，不要信息图，不要重复前面的场景。\n\n"
        "必须包含：\n"
        f"{format_bullets(slot.get('must_include', []))}\n\n"
        "质量门槛：\n"
        f"{format_bullets(slot.get('quality_gate', []))}\n\n"
        "反重复规则：\n"
        f"{format_bullets([slot['variation_note']])}\n\n"
        "必须避免：\n"
        f"{format_bullets(slot['must_avoid'])}"
    )


def build_plan_markdown(article_summary: str, global_visual_style: str, visual_intent: str, visual_mode: str, slots: list[dict[str, Any]]) -> str:
    def main_content(slot: dict[str, Any]) -> str:
        focus = str(slot.get("content_focus", "")).strip()
        if "：" in focus:
            focus = focus.split("：", 1)[1].strip()
        return truncate_text(focus or str(slot.get("target_effect", "")), 34)

    def plan_avoids(slot: dict[str, Any]) -> str:
        slot_specific = slot["must_avoid"][len(COMMON_AVOIDS) :]
        chosen = slot_specific[:2] if slot_specific else slot["must_avoid"][:2]
        return truncate_text("；".join(chosen), 30)

    lines = [
        "## 图片策划表",
        "",
        f"- 文章摘要：{article_summary}",
        f"- 视觉模式：{visual_mode}",
        f"- 视觉意图：{visual_intent}",
        f"- 整体视觉风格：{global_visual_style}",
        "",
        "| 序号 | 位置 | 角色 | 图片类型 | 主要内容 | 避免事项 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for slot in slots:
        lines.append(
            f"| {slot['index']} | {slot['position']} | {slot['role']} | {slot['image_type']} | {main_content(slot)} | {plan_avoids(slot)} |"
        )
    return "\n".join(lines)


def build_jobs(article_path: Path, article_slug: str, markdown: str, target_body_chars: int, min_body_chars: int) -> dict[str, Any]:
    placeholders = parse_placeholders(markdown)
    if not placeholders:
        raise SystemExit(
            "Article markdown is missing {{visual:name}} placeholders. "
            "Write the article with cover/body/closing placeholders before generating images."
        )

    body_placeholders = sorted(
        [name for name in placeholders if name.startswith("body-")],
        key=body_placeholder_key,
    )
    has_cover = "cover" in placeholders
    has_closing = "closing" in placeholders
    if not has_cover or not has_closing:
        raise SystemExit(
            "Article markdown must include both {{visual:cover}} and {{visual:closing}} placeholders before image generation."
        )
    if not body_placeholders:
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
    cover_slot["must_include"] = build_must_include(cover_slot)
    cover_slot["quality_gate"] = build_quality_gate(cover_slot)
    cover_slot["variation_note"] = build_variation_note(slots, cover_slot)
    cover_slot["beat_summary"] = truncate_text(intro_context or article_summary, 180)
    cover_slot["prompt"] = build_cover_prompt(cover_slot, article_summary, article_essence)
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
            "global_visual_style": global_visual_style,
            "local_context": local_context,
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
        slot["must_include"] = build_must_include(slot)
        slot["quality_gate"] = build_quality_gate(slot)
        slot["variation_note"] = build_variation_note(slots, slot)
        slot["beat_summary"] = truncate_text(local_context, 180)
        slot["prompt"] = build_body_prompt(slot, article_summary, target_body_chars)
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
    closing_slot["must_include"] = build_must_include(closing_slot)
    closing_slot["quality_gate"] = build_quality_gate(closing_slot)
    closing_slot["variation_note"] = build_variation_note(slots, closing_slot)
    closing_slot["beat_summary"] = truncate_text(closing_context or article_summary, 180)
    closing_slot["prompt"] = build_closing_prompt(closing_slot, article_summary, article_essence)
    slots.append(closing_slot)

    image_plan = {
        "article_title": title,
        "article_summary": article_summary,
        "article_type": article_type,
        "visual_mode": visual_mode,
        "visual_intent": visual_intent,
        "global_visual_style": global_visual_style,
        "image_slots": [
            {
                "index": slot["index"],
                "name": slot["name"],
                "position": slot["position"],
                "role": slot["role"],
                "visual_mode": slot.get("visual_mode", visual_mode),
                "target_effect": slot["target_effect"],
                "local_context": slot["local_context"],
                "source_context": slot["source_context"],
                "image_type": slot["image_type"],
                "content_focus": slot["content_focus"],
                "must_include": slot.get("must_include", []),
                "quality_gate": slot.get("quality_gate", []),
                "must_avoid": slot["must_avoid"],
            }
            for slot in slots
        ],
    }
    image_plan_markdown = build_plan_markdown(article_summary, global_visual_style, visual_intent, visual_mode, slots)

    return {
        "article_slug": article_slug,
        "article_title": title,
        "article_type": article_type,
        "visual_mode": visual_mode,
        "visual_intent": visual_intent,
        "article_summary": article_summary,
        "article_essence": article_essence,
        "global_visual_style": global_visual_style,
        "source_article": str(article_path.resolve()),
        "image_plan": image_plan,
        "image_plan_markdown": image_plan_markdown,
        "image_slots": image_plan["image_slots"],
        "jobs": slots,
    }


def main() -> None:
    args = parse_args()
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
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {args.out.resolve()}")
    if args.debug_plan and payload.get("image_plan_markdown"):
        print(payload["image_plan_markdown"])


if __name__ == "__main__":
    main()
