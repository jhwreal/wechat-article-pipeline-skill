# Job Schema

```json
{
  "page_title": "Harness 到底是什么？给普通人讲明白",
  "storage_key": "wechat-md-workbench-harness-plain-v1",
  "brand_title": "Harness 文章工作台",
  "brand_subtitle": "单文件 HTML · 含正文和配图 · 可继续编辑",
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
- `url` - external image URL; this is allowed but will not be embedded into the final single-file HTML

Recommended policy:
- write the article first
- generate an internal image plan before any actual image call
- count the approximate Chinese characters
- always include one generated cover image and one generated closing image
- place one in-body image beat roughly every 200 characters for method articles, and roughly every 300-450 characters for emotional, story, or principle articles
- classify visual mode before role selection: `method_visual`, `emotional_illustration`, or `analysis_visual`
- never allow `emotional_illustration` body images to become numbered steps, process charts, checklist cards, information cards, UI panels, or icon matrices
- name in-body beats as `body-1`, `body-2`, `body-3` instead of reviving old SVG-oriented placeholder names
- generate images from the nearby paragraph content, but keep `cover` and `closing` aligned to the whole-article meaning
- assign each slot a role and anti-repetition guard so the image set has rhythm instead of five variants of the same theme prompt
- keep local generated files under `<workspace>/image/<article-slug>/` using the same placeholder basenames
- pass the resolved image assets into `visuals`

Generation policy:
- when the user gives only a rough idea, infer missing brief fields from the defaults above
- keep the package single-shot by default
- prefer local assets, `data_uri`, or base64 so the final HTML stays self-contained

Default planning path:

```bash
python3 scripts/make_wechat_article_image_jobs.py article.md output.image-jobs.json --debug-plan
```

Then call Codex's built-in `image_gen` tool directly once per `jobs[]` entry, save the accepted bitmap files under `./image/<article-slug>/`, and package:

```bash
python3 scripts/package_wechat_article_bundle.py article.md output.html \
  --plan-json output.image-jobs.json \
  --images-dir ./image/<article-slug>
```

For image generation, use the current Codex turn's built-in `image_gen` tool. Nested Codex runtimes are not part of this workflow.

Build outputs may also include:
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
  "content_html": "<section>...</section>",
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
