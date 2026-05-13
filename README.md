# WeChat Article Pipeline Skill

Codex skill for producing a complete WeChat official account article package:

1. write the article first
2. derive a role-based visual plan from the finished article
3. generate cover/body/closing images directly with Codex's built-in image generation tool
4. package everything into a single editable HTML workbench with images embedded as `data:image` URIs

The installable skill lives in:

```text
wechat-article-pipeline/
```

## Features

- WeChat/公众号 style long-form article workflow
- method, analysis, and emotional/story visual modes
- emotional/story content uses illustration logic instead of step diagrams
- deterministic scripts for image-job planning and HTML packaging
- single-file editable HTML output with embedded images
- no nested `codex exec` runtime

## Install

Copy the skill directory into your Codex skills directory:

```bash
mkdir -p ~/.codex/skills
rsync -a wechat-article-pipeline/ ~/.codex/skills/wechat-article-pipeline/
```

Restart or refresh Codex after installing.

## Basic Workflow

Use the skill from Codex with a topic or article direction. The skill expects Codex itself to call the built-in image generation tool for each planned visual slot.

Manual script flow:

```bash
python3 wechat-article-pipeline/scripts/make_wechat_article_image_jobs.py \
  examples/method-article.md \
  output.image-jobs.json \
  --debug-plan
```

Then generate images directly with Codex's built-in image tool and save them as:

```text
image/<article-slug>/cover.png
image/<article-slug>/body-1.png
image/<article-slug>/body-2.png
image/<article-slug>/closing.png
```

Finally package the editable HTML:

```bash
python3 wechat-article-pipeline/scripts/package_wechat_article_bundle.py \
  examples/method-article.md \
  output.html \
  --plan-json output.image-jobs.json \
  --images-dir image/<article-slug>
```

## Repository Layout

```text
.
├── README.md
├── LICENSE
├── examples/
│   ├── method-article.md
│   └── emotion-article.md
└── wechat-article-pipeline/
    ├── SKILL.md
    ├── agents/openai.yaml
    ├── assets/templates/
    ├── references/
    └── scripts/
```

## Notes

- The skill does not call `codex exec` internally.
- The built-in image tool normally saves generated files under `$CODEX_HOME/generated_images`; copy accepted images into the project image directory before packaging.
- The packager validates that generated HTML contains embedded images and no unresolved `{{visual:*}}` placeholders.
