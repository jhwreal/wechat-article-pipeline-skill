#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from atomic_files import atomic_write_text
from image_jobs_contract import normalize_image_jobs, filter_missing_image_jobs as contract_filter


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
        help="Also write a WeChat API publish manifest. Local packaging skips it by default.",
    )
    parser.add_argument("--publish-manifest-out", type=Path, help="Optional publish manifest output path.")
    parser.add_argument("--publisher-config", type=Path, help="Local publisher config path.")
    parser.add_argument("--publisher-env-file", type=Path, help="Local .env with account defaults.")
    parser.add_argument("--publisher-account", help="Official Account selector used for signature and manifest defaults.")
    parser.add_argument("--author", help="Author override for the publish manifest.")
    parser.add_argument("--preview-account", help="Preview account override for the publish manifest.")
    parser.add_argument("--signature-author", help="Visible signature author shown below the cover.")
    parser.add_argument("--original-issue", type=int, help="Visible original article issue number.")
    parser.add_argument(
        "--remember-publisher-config",
        action="store_true",
        help="Persist supplied author/preview values when building a publish manifest.",
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


def validate_article_slug(value: str) -> str:
    slug = value.strip()
    path = Path(slug)
    if (
        not slug
        or path.is_absolute()
        or path.name != slug
        or "/" in slug
        or "\\" in slug
        or slug in {".", ".."}
        or any(ord(char) < 32 for char in slug)
        or any(char in '<>:"|?*' for char in slug)
        or slug.casefold() in {
            "con",
            "prn",
            "aux",
            "nul",
            *(f"com{index}" for index in range(1, 10)),
            *(f"lpt{index}" for index in range(1, 10)),
        }
    ):
        raise SystemExit("--article-slug must be one portable directory name without path separators.")
    return slug


def existing_image(images_dir: Path, name: str) -> Path | None:
    exact = images_dir / name
    if Path(name).suffix:
        return exact if exact.is_file() else None
    for suffix in IMAGE_SUFFIXES:
        path = images_dir / f"{name}{suffix}"
        if path.is_file():
            return path
    return None


def assert_images_ready(jobs_path: Path, images_dir: Path) -> None:
    plan = json.loads(jobs_path.read_text(encoding="utf-8"))
    plan = normalize_image_jobs(plan)
    jobs = plan.get("slots", [])
    missing: list[str] = []
    for job in jobs:
        output = str(job.get("output") or "").strip()
        if output and not existing_image(images_dir, output):
            missing.append(output)
    if missing:
        image_dir_text = str(images_dir)
        names = ", ".join(missing)
        raise SystemExit(
            "Image files are not ready yet. Generate them directly with Codex's built-in image_gen tool, "
            f"save them into {image_dir_text}, then rerun this command. Missing: {names}"
        )


def filter_jobs_for_missing_images(payload: dict, images_dir: Path) -> dict:
    return contract_filter(
        payload,
        lambda output: existing_image(images_dir, output) is not None,
    )


def extend_package_command(
    command: list[str], args: argparse.Namespace, publish_manifest: bool
) -> None:
    if publish_manifest:
        command.append("--publish-manifest")
    path_options = (
        ("--publish-manifest-out", args.publish_manifest_out),
        ("--publisher-config", args.publisher_config),
        ("--publisher-env-file", args.publisher_env_file),
    )
    for flag, value in path_options:
        if value:
            command.extend([flag, str(value.expanduser().resolve())])
    text_options = (
        ("--publisher-account", args.publisher_account),
        ("--author", args.author),
        ("--preview-account", args.preview_account),
        ("--signature-author", args.signature_author),
    )
    for flag, value in text_options:
        if value is not None:
            command.extend([flag, str(value)])
    if args.original_issue is not None:
        command.extend(["--original-issue", str(args.original_issue)])
    if args.remember_publisher_config:
        command.append("--remember-publisher-config")


def verify_package(
    out: Path,
    job_out: Path | None = None,
    manifest_out: Path | None = None,
) -> None:
    command = [sys.executable, str(VERIFY), str(out)]
    if job_out:
        command.extend(["--job", str(job_out)])
    if manifest_out:
        command.extend(["--manifest", str(manifest_out), "--require-manifest"])
    run(command)


def main() -> None:
    args = parse_args()
    publish_manifest = bool(args.publish_manifest or args.publish_manifest_out)
    if args.no_images and args.missing_only:
        raise SystemExit("--no-images and --missing-only cannot be used together.")
    if args.no_images and publish_manifest and not args.cover_image:
        raise SystemExit(
            "--no-images --publish-manifest requires --cover-image <path> because WeChat draft/add "
            "requires a cover thumb_media_id even when the article body has no images."
        )
    if args.missing_only and not args.plan_only:
        raise SystemExit("--missing-only is only supported with --plan-only. Generate missing images, then rerun without --missing-only to package.")

    source_article = args.article.resolve()
    out = args.out.resolve()
    article_slug = validate_article_slug(args.article_slug or infer_article_slug(source_article))
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
        if args.job_out:
            package_cmd.extend(["--job-out", str(args.job_out.resolve())])
        if args.support_dir:
            package_cmd.extend(["--support-dir", str(args.support_dir.resolve())])
        extend_package_command(package_cmd, args, publish_manifest)
        run(package_cmd)
        manifest_out = (
            (args.publish_manifest_out or out.with_suffix(".publish-manifest.json")).resolve()
            if publish_manifest
            else None
        )
        verify_package(out, args.job_out.resolve() if args.job_out else None, manifest_out)
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
        atomic_write_text(jobs_out, json.dumps(filtered, ensure_ascii=False, indent=2) + "\n")

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
    extend_package_command(package_cmd, args, publish_manifest)
    run(package_cmd)
    manifest_out = (
        (args.publish_manifest_out or out.with_suffix(".publish-manifest.json")).resolve()
        if publish_manifest
        else None
    )
    verify_package(out, args.job_out.resolve() if args.job_out else None, manifest_out)


if __name__ == "__main__":
    main()
