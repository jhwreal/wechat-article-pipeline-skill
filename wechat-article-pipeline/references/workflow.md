# Workflow

Use this file for article structure and interaction choices. Use `style-guide.md` for prose style and visual language. Use `publishing.md` only for official WeChat API delivery.

## Default Structure

For ordinary WeChat or Toutiao-style explanatory posts:

1. Open with the reader's concrete confusion, pressure, or gap.
2. State the core claim in plain Chinese.
3. Explain the concept or mechanism with familiar examples.
4. Show why it matters in daily work, life, or decision-making.
5. Give one usable model, comparison, or next action.
6. End with a memorable takeaway, not a slogan.

Default assumptions:

- reader: general Chinese readers, not specialists
- length: about 1000 Chinese characters, under 2000 unless requested
- tone: clear, direct, thoughtful, friend-like
- stance: practical cognition gain, not report prose or empty attitude

## Interaction Rules

- If the user gives only a topic, infer the brief and write.
- Do not ask for a brief-confirmation round by default.
- Ask before continuing only when the missing answer changes the thesis, target reader, risk level, account choice, or delivery destination.
- When editing an existing article package, preserve the existing slug and asset relationship unless the user asks for a new package.
- When the task is title/body/image/package-only, handle only that layer instead of rerunning the whole path.

## Markdown Rules

- Use one `#` title.
- Use `##` headings when the article has real internal turns.
- Use short paragraphs.
- Add visual placeholders only when images are wanted: `cover`, `body-1`, `body-2`, ..., `closing`.
- For technical, tool, coding, workflow, or tutorial articles, wrap concrete names in backticks: project names, repositories, paths, commands, environment variables, API names, scripts, config keys, and literal UI/control names.
- Keep inline-code formatting separate from reading-focus marks.

## Focus Marking

The orchestration script runs `mark_wechat_article_focus.py` unless disabled. It should preserve prose and add only reading aids:

- `**...**` for a core sentence in a focus zone
- `> ...` only when an existing sentence is genuinely quotable
- no duplicated quote sentence
- no automatic pink keyword marking by default
- no focus marks in headings, image placeholders, code fences, inline code, commands, or dense list-only sections

## Execution Choices

- Full package with images: use the default `postprocess_wechat_article.py --plan-only`, generate listed images, then rerun without `--plan-only`.
- Image production: use `image-production.md`; generate one image per slot from `generation_queue[].generation_prompt`, save directly to the final output, and let the user request regeneration if needed.
- No generated images: use `postprocess_wechat_article.py --no-images`.
- No body images + API draft delivery: still provide one cover image and use `postprocess_wechat_article.py --no-images --publish-manifest --cover-image <cover>`.
- Missing images only: use `postprocess_wechat_article.py --missing-only --plan-only`, generate only listed files, then rerun the normal package command.
- Verification: run `verify_wechat_article_package.py <html>` before delivery.
- API draft delivery: run publish dry-run first; add `--create-draft` only after the user explicitly asks for草稿箱. Do not use browser automation.

## Completion

Deliver the local HTML first. Mention markdown, image directory, image jobs, manifest, and API result only when relevant. State any skipped images, missing account fields, API limitations, or unresolved risks plainly.
