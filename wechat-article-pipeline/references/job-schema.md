# Job Schema

```json
{
  "page_title": "标题",
  "storage_key": "wechat-md-workbench-harness-plain-v1",
  "brand_title": "标题工作台",
  "brand_subtitle": "HTML 工作台 · 相对路径配图 · 可继续编辑",
  "theme_color": "#17b394",
  "image_plan": {
    "article_title": "标题",
    "article_summary": "100字内摘要",
    "article_type": "industry-analysis",
    "visual_mode": "analysis_visual",
    "global_visual_style": "高级商业科技感 + 真实工作场景",
    "image_slots": [
      {
        "index": 1,
        "name": "cover",
        "position": "cover",
        "role": "hero_cover",
        "image_type": "cinematic_key_visual",
        "source_context": "title_and_intro",
        "content_focus": "只抓一个最有点击力的核心冲突"
      }
    ]
  },
  "font_size": "16",
  "font_family": "-apple-system, BlinkMacSystemFont, \"PingFang SC\", \"Microsoft YaHei\", sans-serif",
  "defaults": {
    "target_reader": "微信公众号或今日头条的中国普通用户",
    "stance": "理性、有思考、帮助普通人增长认知和能力",
    "length_target": "1000字左右，2000字以内",
    "tone": "像朋友解释，精炼、信息密度高",
    "visual_density": "题图 1 张、尾图 1 张，正文约每200字一张图"
  },
  "article_markdown": "# 标题\n\n![题图]({{visual:cover}})\n\n第一段正文。\n\n![配图1]({{visual:body-1}})\n\n第二段正文。\n\n![配图2]({{visual:body-2}})\n\n结尾段。\n\n![尾图]({{visual:closing}})\n",
  "visuals": {
    "cover": {
      "path": "cover.png",
      "role": "hero_cover",
      "image_type": "cinematic_key_visual",
      "source_context": "title_and_intro"
    },
    "body-1": {
      "mime_type": "image/png",
      "base64": "iVBORw0KGgoAAAANSUhEUg..."
    },
    "closing": {
      "data_uri": "data:image/webp;base64,UklGR..."
    }
  }
}
```

Each `visuals` entry supports one of these source forms:
- `path` - local image file path, relative to the job file or absolute
- `data_uri` - already embedded image payload
- `base64` plus `mime_type` - raw image bytes returned by the generator
- `url` - external image URL; allowed only for the local workbench. Publish-manifest generation rejects non-embedded body and cover images.

Recommended contract:
- the first H1 in `article_markdown` is the sole canonical article title; `page_title`, `brand_title`, image-plan titles, workbench chrome, and publish manifests are derived values and must never override it
- image meaning comes from the finished article, not from a preselected layout name
- visual style and role choices follow `style-guide.md`
- in-body placeholders use `body-1`, `body-2`, `body-3` ...
- local generated files live under `<workspace>/image/<article-slug>/` using placeholder-aligned basenames
- resolved image assets are passed into `visuals`
- the HTML workbench stores relative image paths in editable markdown; the copy button temporarily inlines local images into clipboard HTML

Generation policy:
- when the user gives only a rough idea, infer missing brief fields from the defaults above
- keep the package single-shot by default
- prefer local assets; workbench markdown uses paths relative to the HTML output directory, copy-time clipboard HTML embeds local images, and the publish manifest still embeds images for WeChat API upload

Default orchestration path:

```bash
python3 <skill>/scripts/postprocess_wechat_article.py \
  <workspace>/files/<slug>.md \
  <workspace>/files/<slug>.html \
  --workspace <workspace> \
  --article-slug <slug> \
  --jobs-out <workspace>/files/<slug>.image-jobs.json \
  --plan-only
```

Then execute `generation_queue[]` as single-pass image work, save each bitmap directly under `<workspace>/image/<slug>/` using the canonical slot `output`, and rerun the same command without `--plan-only` to package.

For missing-image repair, use `postprocess_wechat_article.py --missing-only --plan-only`. For no-image formatting, use `postprocess_wechat_article.py --no-images`.

For no-body-image draft delivery, use `postprocess_wechat_article.py --no-images --publish-manifest --cover-image <cover>`. The job may contain `visuals.cover` even when `article_markdown` has no image placeholder; that cover is for WeChat `thumb_media_id` only and is not inserted into the body.

`make_wechat_article_image_jobs.py` also supports direct lightweight planning flags: `--mode no-image|fast|full`, `--max-body-images N`, and `--missing-only --images-dir <dir>`. Prefer `postprocess_wechat_article.py` for the normal workflow, but use these flags when diagnosing or regenerating the image plan directly.

The canonical image payload is schema v2: `slots[]` stores article-facing placement and visual constraints, while `generation_queue[]` stores only `{slot, output, generation_prompt}` for execution. Shared rules and review defaults live once at the top level. When `--mode fast` or `--max-body-images` intentionally omits body slots, `article.skipped_visuals` records those exact `body-N` names; the packager removes only those declared image placeholders instead of failing later on nonexistent files. Historical v1 payloads (`jobs[]`, `image_slots`, nested `generation_task`, duplicate variants) are normalized on read; new writers must emit v2 only. Queue tasks intentionally omit review details. Image generation rules come from `references/image-rules.json`; normal execution should not print the full rules or queue.

Build outputs may also include:
- `<html-stem>.assets/` — local files materialized from `data_uri` or `base64` visual inputs for clean workbench markdown
- `<html-stem>.clipboard-assets.js` — fallback local-image data loaded lazily only when a direct-file workbench copy cannot fetch local images; it is released after copying
- `quality-report.json` — records how each visual asset was resolved
- `resolved-assets.json` — records the final URI used for each placeholder
- `image-plan.json` — records the role-based slot plan
- `image-plan.md` — debug-friendly markdown table for the slot plan
- `<html-stem>.publish-manifest.json` — optional WeChat backend draft/preview handoff data, created only with `--publish-manifest`
- `<slug>.three-platform-result.json` — resumable aggregate state for explicitly requested WeChat + Toutiao + Xiaohongshu draft sync

Workbench builds also embed release diagnostics in `bootstrap.buildInfo` and the versioned platform adapter registry in `bootstrap.platformAdapters`. Markdown remains the sole content source; platform HTML is derived on demand and is not stored as a fourth editable document.

## Publish Manifest

`package_wechat_article_bundle.py` writes only the local workbench by default. Pass `--publish-manifest` for the optional official WeChat API draft-box workflow in [publishing.md](publishing.md). The manifest embeds every publishable image as `data:image`, rejects external image sources, and contains only fields the official API workflow can use; it does not include original declaration, reward account, or collection fields.

```json
{
  "schema_version": 1,
  "article_slug": "wechat-article",
  "title": "标题",
  "author": "",
  "digest": "摘要",
  "content_html": "<p>...</p><p>...</p>",
  "content_text": "纯文本正文",
  "source_fingerprint": "sha256 of the rendered job plus resolved image bytes",
  "workbench_html": "/absolute/path/output.html",
  "cover": {
    "name": "cover",
    "alt": "题图",
    "src": "data:image/png;base64,..."
  },
  "image_candidates": [],
  "preview": {
    "method": "message/mass/preview",
    "account": ""
  },
  "env_file": ".env",
  "token_cache_path": "~/.codex/wechat-article-pipeline/wechat-token-cache.json",
  "safety": {
    "use_official_api_only": true,
    "avoid_computer_use_on_mp_backend": true,
    "never_click_publish": true,
    "never_call_publish_api_by_default": true
  }
}
```

Author, optional preview account, AppID, and AppSecret are local defaults. Keep them in `.env`, copied from `.env.example`; `.env` is ignored by Git and must never be committed.

New manifests include `source_fingerprint`. Package verification recomputes it from the current job and resolved image bytes, so an old manifest left beside a newly edited article or regenerated image is reported as stale. Historical manifests without this field remain readable.

Access tokens are cached locally in `~/.codex/wechat-article-pipeline/wechat-token-cache.json`, outside the repo. The `.codex` directory name is historical; every agent runtime shares this same local cache path.
