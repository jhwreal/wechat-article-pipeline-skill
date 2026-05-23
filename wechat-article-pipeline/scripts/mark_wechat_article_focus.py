#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path


CHINESE_RE = re.compile(r"[\u4e00-\u9fff]")
SENTENCE_RE = re.compile(r"[^。！？!?；;\n]+[。！？!?；;]?")
STRONG_RE = re.compile(r"\*\*([^*]+)\*\*")
INLINE_CODE_RE = re.compile(r"`[^`]+`")

CONCEPT_PATTERNS = [
    "公众号文章生产流水线",
    "公众号写作流水线",
    "内容生产流水线",
    "内容生产系统",
    "真实工作流",
    "HTML 工作台",
    "发布清单",
    "微信公众号官方 API",
    "公众号草稿箱",
    "微信草稿",
    "草稿箱",
    "配图计划",
    "内置图片生成能力",
    "自动化",
    "最后一公里",
    "人的判断",
    "最后确认",
    "重复劳动",
    "内容资产",
    "视觉停顿",
]

KEYWORD_PATTERNS = [
    "选题",
    "成稿",
    "配图",
    "排版",
    "上传",
    "封面图",
    "正文图",
    "尾图",
    "HTML",
    "API",
    "Codex",
    "skill",
    "草稿",
    "确认",
    "发布",
    "可编辑",
    "可检查",
    "可修改",
    "可控",
]

GOLDEN_HINTS = (
    "不是",
    "而是",
    "真正",
    "关键",
    "本质",
    "核心",
    "重要",
    "意味着",
    "对我来说",
    "我觉得",
    "只要",
    "不再",
    "应该",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Mark pull quotes, key terms, and concepts in a WeChat article markdown file."
    )
    parser.add_argument("article", type=Path, help="Source markdown article.")
    parser.add_argument("out", type=Path, help="Output markdown article with focus marks.")
    parser.add_argument("--target-chars", type=int, default=300, help="Target Chinese chars per focus zone.")
    parser.add_argument("--max-bold-per-zone", type=int, default=2, help="Maximum bold marks per focus zone.")
    parser.add_argument("--in-place", action="store_true", help="Write back to the input article path.")
    return parser.parse_args()


def chinese_len(text: str) -> int:
    return len(CHINESE_RE.findall(strip_markdown(text)))


def strip_markdown(text: str) -> str:
    text = INLINE_CODE_RE.sub("", text)
    text = re.sub(r"!\[[^\]]*]\([^)]+\)", "", text)
    text = re.sub(r"\[[^\]]+]\([^)]+\)", "", text)
    text = STRONG_RE.sub(r"\1", text)
    return text


def is_skip_block(block: str) -> bool:
    stripped = block.strip()
    if not stripped:
        return True
    if stripped.startswith(("```", "#", ">", "![", "<")):
        return True
    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    if lines and all(re.match(r"^(-|\*|\+|\d+\.)\s+", line) for line in lines):
        return True
    return False


def split_blocks(markdown: str) -> list[str]:
    return re.split(r"(\n\s*\n)", markdown)


def sentences(text: str) -> list[str]:
    return [match.group(0).strip() for match in SENTENCE_RE.finditer(strip_markdown(text)) if match.group(0).strip()]


def sentence_score(sentence: str) -> int:
    clean = sentence.strip()
    length = chinese_len(clean)
    if length < 18 or length > 70:
        return -100
    has_hint = any(hint in clean for hint in GOLDEN_HINTS)
    has_contrast = "不是" in clean and "而是" in clean
    if not has_hint and not has_contrast:
        return -100
    score = 0
    score += sum(8 for hint in GOLDEN_HINTS if hint in clean)
    score += clean.count("，") * 2
    score += 10 if has_contrast else 0
    score += 8 if "不只是" in clean or "不再" in clean else 0
    score += 5 if clean.endswith(("。", "！", "？")) else 0
    return score + min(length, 45)


def choose_golden_sentence(zone_blocks: list[str]) -> str | None:
    candidates: list[tuple[int, str]] = []
    for block in zone_blocks:
        if is_skip_block(block):
            continue
        for sentence in sentences(block):
            candidates.append((sentence_score(sentence), sentence))
    if not candidates:
        return None
    score, sentence = max(candidates, key=lambda item: item[0])
    if score < 55:
        return None
    return sentence.rstrip("；;，,")


def already_marked(text: str, phrase: str) -> bool:
    return f"**{phrase}**" in text


def protect_marked_spans(text: str) -> tuple[str, list[str]]:
    protected: list[str] = []

    def replace(match: re.Match[str]) -> str:
        protected.append(match.group(0))
        return f"@@PROTECTED{len(protected) - 1}@@"

    text = INLINE_CODE_RE.sub(replace, text)
    text = STRONG_RE.sub(replace, text)
    return text, protected


def restore_marked_spans(text: str, protected: list[str]) -> str:
    for index, value in enumerate(protected):
        text = text.replace(f"@@PROTECTED{index}@@", value)
    return text


def mark_phrase_once(text: str, phrase: str) -> tuple[str, bool]:
    if already_marked(text, phrase):
        return text, False
    protected_text, protected = protect_marked_spans(text)
    if phrase not in protected_text:
        return text, False
    marked = protected_text.replace(phrase, f"**{phrase}**", 1)
    return restore_marked_spans(marked, protected), True


def mark_zone_blocks(zone_blocks: list[str], max_bold: int) -> list[str]:
    marked = list(zone_blocks)
    used = 0
    phrases = sorted(set(CONCEPT_PATTERNS + KEYWORD_PATTERNS), key=len, reverse=True)
    for phrase in phrases:
        if used >= max_bold:
            break
        for index, block in enumerate(marked):
            if used >= max_bold:
                break
            if is_skip_block(block):
                continue
            updated, changed = mark_phrase_once(block, phrase)
            if changed:
                marked[index] = updated
                used += 1
                break
    return marked


def flush_zone(output: list[str], zone_blocks: list[str], target_chars: int, max_bold: int) -> None:
    if not zone_blocks:
        return
    marked = mark_zone_blocks(zone_blocks, max_bold)
    quote = choose_golden_sentence(marked)
    output.extend(marked)
    if quote:
        output.append(f"\n\n> {quote}\n\n")


def mark_article(markdown: str, target_chars: int, max_bold: int) -> str:
    parts = split_blocks(markdown)
    output: list[str] = []
    zone: list[str] = []
    zone_chars = 0
    in_code_fence = False

    for part in parts:
        if not part.strip():
            if zone:
                zone.append(part)
            else:
                output.append(part)
            continue

        stripped = part.strip()
        if stripped.startswith("```"):
            in_code_fence = not in_code_fence

        block_chars = 0 if in_code_fence or is_skip_block(part) else chinese_len(part)
        zone.append(part)
        zone_chars += block_chars

        if zone_chars >= target_chars:
            flush_zone(output, zone, target_chars, max_bold)
            zone = []
            zone_chars = 0

    flush_zone(output, zone, target_chars, max_bold)
    return re.sub(r"\n{4,}", "\n\n\n", "".join(output)).strip() + "\n"


def main() -> None:
    args = parse_args()
    article = args.article.resolve()
    out = article if args.in_place else args.out.resolve()
    markdown = article.read_text(encoding="utf-8")
    marked = mark_article(markdown, args.target_chars, args.max_bold_per_zone)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(marked, encoding="utf-8")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
