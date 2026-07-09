# Job Schema

```json
{
  "page_title": "Harness 到底是什么？给普通人讲明白",
  "storage_key": "wechat-md-workbench-harness-plain-v1",
  "brand_title": "Harness 文章工作台",
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
- `url` - external image URL; this is allowed and is kept as a direct reference in the workbench

Recommended contract:
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

Then execute `generation_queue[]` as single-pass image work, save each bitmap directly under `<workspace>/image/<slug>/` using `jobs[].output`, and rerun the same command without `--plan-only` to package.

For missing-image repair, use `postprocess_wechat_article.py --missing-only --plan-only`. For no-image formatting, use `postprocess_wechat_article.py --no-images`.

For no-body-image draft delivery, use `postprocess_wechat_article.py --no-images --publish-manifest --cover-image <cover>`. The job may contain `visuals.cover` even when `article_markdown` has no image placeholder; that cover is for WeChat `thumb_media_id` only and is not inserted into the body.

`make_wechat_article_image_jobs.py` also supports direct lightweight planning flags: `--mode no-image|fast|full`, `--max-body-images N`, and `--missing-only --images-dir <dir>`. Prefer `postprocess_wechat_article.py` for the normal workflow, but use these flags when diagnosing or regenerating the image plan directly.

Each `jobs[]` slot includes a short `generation_prompt` for image generation and a separate job-level `review_contract` for later user-requested regeneration. The legacy `prompt` field mirrors `generation_prompt` for compatibility; do not append `review_contract` into it. Each slot also includes a lightweight `generation_task`, and top-level `generation_queue[]` has one task per slot for direct parallel execution. Queue tasks intentionally omit `review_contract`; workers should receive only the prompt and output metadata they need. Image generation rules come from `references/image-rules.json`; generated payloads include `image_execution`, `image_rules`, and `image_rules_markdown`, but normal execution should not print the full rules or queue.

Build outputs may also include:
- `<html-stem>.assets/` — local files materialized from `data_uri` or `base64` visual inputs for clean workbench markdown
- `<html-stem>.clipboard-assets.js` — sidecar local-image data used only when copying rich HTML from the workbench
- `quality-report.json` — records how each visual asset was resolved
- `resolved-assets.json` — records the final URI used for each placeholder
- `image-plan.json` — records the role-based slot plan
- `image-plan.md` — debug-friendly markdown table for the slot plan
- `<html-stem>.publish-manifest.json` — records the WeChat backend draft/preview handoff data

## Publish Manifest

`package_wechat_article_bundle.py` writes a publishing manifest by default. It is used by the optional official WeChat API draft-box workflow in [publishing.md](publishing.md). The manifest only contains fields the official API workflow can use; it does not include original declaration, reward account, or collection fields.

```json
{
  "schema_version": 1,
  "article_slug": "wechat-article",
  "title": "标题",
  "author": "",
  "digest": "摘要",
  "content_html": "<p>...</p><p>...</p>",
  "content_text": "纯文本正文",
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

Access tokens are cached locally in `~/.codex/wechat-article-pipeline/wechat-token-cache.json`, outside the repo.
