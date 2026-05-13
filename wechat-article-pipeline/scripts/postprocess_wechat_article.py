#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
MAKE_JOBS = SCRIPT_DIR / "make_wechat_article_image_jobs.py"
PACKAGE = SCRIPT_DIR / "package_wechat_article_bundle.py"
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
    parser.add_argument("--job-out", type=Path, help="Optional path for the generated HTML builder job JSON.")
    parser.add_argument("--support-dir", type=Path, help="Optional support file directory.")
    parser.add_argument("--target-body-chars", type=int, default=200)
    parser.add_argument("--min-body-chars", type=int, default=120)
    parser.add_argument("--workspace", type=Path, default=WORKSPACE, help="Workspace root. Defaults to current directory.")
    parser.add_argument("--debug-image-plan", action="store_true", help="Print the generated image-plan table.")
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


def main() -> None:
    args = parse_args()
    article = args.article.resolve()
    out = args.out.resolve()
    article_slug = args.article_slug or infer_article_slug(article)
    jobs_out = (args.jobs_out or out.with_suffix(".image-jobs.json")).resolve()
    workspace = args.workspace.resolve()
    images_dir = (args.images_dir or (workspace / "image" / article_slug)).resolve()

    make_jobs_cmd = [
        sys.executable,
        str(MAKE_JOBS),
        str(article),
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

    if args.plan_only:
        print(f"Wrote image jobs to {jobs_out}")
        print(f"Generate images directly with Codex image_gen and save them under {images_dir}")
        return

    assert_images_ready(jobs_out, images_dir)

    package_cmd = [
        sys.executable,
        str(PACKAGE),
        str(article),
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


if __name__ == "__main__":
    main()
