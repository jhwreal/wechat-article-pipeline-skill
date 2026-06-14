#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
MARK_FOCUS = SCRIPT_DIR / "mark_wechat_article_focus.py"
MAKE_JOBS = SCRIPT_DIR / "make_wechat_article_image_jobs.py"
PACKAGE = SCRIPT_DIR / "package_wechat_article_bundle.py"
VERIFY = SCRIPT_DIR / "verify_wechat_article_package.py"
WORKSPACE = Path.cwd()
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Derive WeChat article image jobs and package the final HTML once images "
            "have been generated directly by Codex's built-in image tool."
        )
    )
    parser.add_argument("article", type=Path, help="Path to the source markdown article.")
    parser.add_argument("out", type=Path, help="Path to the final HTML workbench output.")
    parser.add_argument("--article-slug", help="Optional article slug override.")
    parser.add_argument("--jobs-out", type=Path, help="Optional path for the generated image jobs JSON.")
    parser.add_argument("--images-dir", type=Path, help="Directory containing generated cover/body/closing images.")
    parser.add_argument(
        "--cover-image",
        type=Path,
        help=(
            "Explicit cover image for --no-images draft delivery. "
            "The cover is used for the WeChat thumb_media_id but is not inserted into the article body."
        ),
    )
    parser.add_argument("--job-out", type=Path, help="Optional path for the generated HTML builder job JSON.")
    parser.add_argument("--focused-article-out", type=Path, help="Optional path for the marked article markdown.")
    parser.add_argument("--support-dir", type=Path, help="Optional support file directory.")
    parser.add_argument("--focus-target-chars", type=int, default=300)
    parser.add_argument(
        "--max-bold-per-focus-zone",
        "--max-accent-per-focus-zone",
        dest="max_bold_per_focus_zone",
        type=int,
        default=0,
        help="Deprecated compatibility option. Automatic pink accent term marking is currently disabled.",
    )
    parser.add_argument("--no-focus-marking", action="store_true", help="Skip key-sentence/quote marking.")
    parser.add_argument("--target-body-chars", type=int, default=200)
    parser.add_argument("--min-body-chars", type=int, default=120)
    parser.add_argument("--workspace", type=Path, default=WORKSPACE, help="Workspace root. Defaults to current directory.")
    parser.add_argument("--debug-image-plan", action="store_true", help="Print the generated image-plan table.")
    parser.add_argument(
        "--no-images",
        action="store_true",
        help="Format and package the article without deriving or requiring image jobs.",
    )
    parser.add_argument(
        "--publish-manifest",
        action="store_true",
        help="With --no-images, also write a publish manifest. By default no-image formatting skips it.",
    )
    parser.add_argument(
        "--missing-only",
        action="store_true",
        help="With --plan-only, keep only jobs whose output image is missing from --images-dir.",
    )
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="Only write the image jobs JSON. Use this before direct Codex image generation.",
    )
    return parser.parse_args()


def run(command: list[str]) -> None:
    result = subprocess.run(command)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def infer_article_slug(article: Path) -> str:
    stem = article.stem.strip()
    if stem and stem.lower() != "article":
        return stem
    parent = article.parent.name.strip()
    if parent:
        return parent
    return stem or "wechat-article"


def existing_image(images_dir: Path, name: str) -> Path | None:
    for suffix in IMAGE_SUFFIXES:
        path = images_dir / f"{name}{suffix}"
        if path.exists():
            return path
    return None


def assert_images_ready(jobs_path: Path, images_dir: Path) -> None:
    plan = json.loads(jobs_path.read_text(encoding="utf-8"))
    jobs = plan.get("jobs") or plan.get("image_slots") or []
    missing: list[str] = []
    for job in jobs:
        name = str(job.get("name") or "").strip()
        if name and not existing_image(images_dir, name):
            missing.append(name)
    if missing:
        image_dir_text = str(images_dir)
        names = ", ".join(missing)
        raise SystemExit(
            "Image files are not ready yet. Generate them directly with Codex's built-in image_gen tool, "
            f"save them into {image_dir_text}, then rerun this command. Missing: {names}"
        )


def filter_jobs_for_missing_images(payload: dict, images_dir: Path) -> dict:
    result = copy.deepcopy(payload)
    jobs = [job for job in result.get("jobs", []) if not existing_image(images_dir, str(job.get("name", "")).strip())]
    missing_names = {str(job.get("name", "")).strip() for job in jobs}
    result["jobs"] = jobs
    if isinstance(result.get("image_slots"), list):
        result["image_slots"] = [
            slot
            for slot in result["image_slots"]
            if str(slot.get("name", "")).strip() in missing_names
        ]
    if isinstance(result.get("generation_queue"), list):
        result["generation_queue"] = [
            item
            for item in result["generation_queue"]
            if str(item.get("slot", "")).strip() in missing_names
        ]
    image_plan = result.get("image_plan")
    if isinstance(image_plan, dict) and isinstance(image_plan.get("image_slots"), list):
        image_plan["image_slots"] = [
            slot
            for slot in image_plan["image_slots"]
            if str(slot.get("name", "")).strip() in missing_names
        ]
    return result


def verify_package(out: Path, job_out: Path | None = None) -> None:
    command = [sys.executable, str(VERIFY), str(out)]
    if job_out:
        command.extend(["--job", str(job_out)])
    run(command)


def main() -> None:
    args = parse_args()
    if args.no_images and args.missing_only:
        raise SystemExit("--no-images and --missing-only cannot be used together.")
    if args.no_images and args.publish_manifest and not args.cover_image:
        raise SystemExit(
            "--no-images --publish-manifest requires --cover-image <path> because WeChat draft/add "
            "requires a cover thumb_media_id even when the article body has no images."
        )
    if args.missing_only and not args.plan_only:
        raise SystemExit("--missing-only is only supported with --plan-only. Generate missing images, then rerun without --missing-only to package.")

    source_article = args.article.resolve()
    out = args.out.resolve()
    article_slug = args.article_slug or infer_article_slug(source_article)
    jobs_out = (args.jobs_out or out.with_suffix(".image-jobs.json")).resolve()
    workspace = args.workspace.resolve()
    images_dir = (args.images_dir or (workspace / "image" / article_slug)).resolve()
    focused_article = (
        source_article
        if args.no_focus_marking
        else (args.focused_article_out or source_article.with_suffix(".focused.md")).resolve()
    )

    if not args.no_focus_marking:
        run(
            [
                sys.executable,
                str(MARK_FOCUS),
                str(source_article),
                str(focused_article),
                "--target-chars",
                str(args.focus_target_chars),
                "--max-bold-per-zone",
                str(args.max_bold_per_focus_zone),
            ]
        )

    if args.no_images:
        package_cmd = [
            sys.executable,
            str(PACKAGE),
            str(focused_article),
            str(out),
            "--no-images",
        ]
        if args.cover_image:
            package_cmd.extend(["--cover-image", str(args.cover_image.resolve())])
        if not args.publish_manifest:
            package_cmd.append("--no-publish-manifest")
        if args.job_out:
            package_cmd.extend(["--job-out", str(args.job_out.resolve())])
        if args.support_dir:
            package_cmd.extend(["--support-dir", str(args.support_dir.resolve())])
        run(package_cmd)
        verify_package(out, args.job_out.resolve() if args.job_out else None)
        return

    make_jobs_cmd = [
        sys.executable,
        str(MAKE_JOBS),
        str(focused_article),
        str(jobs_out),
        "--article-slug",
        article_slug,
        "--target-body-chars",
        str(args.target_body_chars),
        "--min-body-chars",
        str(args.min_body_chars),
    ]
    if args.debug_image_plan:
        make_jobs_cmd.append("--debug-plan")
    run(make_jobs_cmd)

    if args.missing_only:
        payload = json.loads(jobs_out.read_text(encoding="utf-8"))
        filtered = filter_jobs_for_missing_images(payload, images_dir)
        jobs_out.write_text(json.dumps(filtered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.plan_only:
        print(f"Wrote image jobs to {jobs_out}")
        print(f"Generate images directly with Codex image_gen and save them under {images_dir}")
        return

    assert_images_ready(jobs_out, images_dir)

    package_cmd = [
        sys.executable,
        str(PACKAGE),
        str(focused_article),
        str(out),
        "--plan-json",
        str(jobs_out),
        "--images-dir",
        str(images_dir),
    ]
    if args.job_out:
        package_cmd.extend(["--job-out", str(args.job_out.resolve())])
    if args.support_dir:
        package_cmd.extend(["--support-dir", str(args.support_dir.resolve())])
    run(package_cmd)
    verify_package(out, args.job_out.resolve() if args.job_out else None)


if __name__ == "__main__":
    main()
