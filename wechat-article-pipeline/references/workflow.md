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

## Reader-Facing Revision Gate

Apply this hard gate whenever the user asks to add, correct, compare, verify, or expand material in an existing article.

- Treat the follow-up message as an editing brief and evidence source, never as publishable article copy.
- Rewrite every insertion so it makes complete sense to a reader who has never seen the assistant-user conversation.
- Remove request narration and editing meta-talk such as `你问到的`, `按你的要求`, `刚才提到`, `我查了一下`, `这里补充一下`, and `回答你的问题`.
- Integrate corrections as facts. Write `腾讯的表中列出的是 Claude Opus 5，并未包含 Claude Fable 5`, not `你问到的 Claude Fable 5，其实不在腾讯这张表里`.
- Direct address to the article reader is allowed when it belongs to the intended voice; references to what the user asked in chat are not.
- First-person language is allowed only for the author's real experience or stance, never for the assistant's research or editing process.
- Read each inserted paragraph in isolation before packaging. If it depends on the conversation or describes the request, rewrite it. Do not deliver until every insertion passes.

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
- Workbench delivery and saving: after every verified HTML workbench build, start `serve_wechat_workbench.py`, keep it running, and deliver its loopback URL first. Do this by default whenever an HTML workbench exists, without waiting for the user to ask to open it. Edits are cached immediately and sent to the server after 3 idle seconds; Save sends immediately. A directly opened HTML file is preview/copy-only and must lock editing. Show saved/saving/error/recovery-required states explicitly.
- No generated images: use `postprocess_wechat_article.py --no-images`.
- No body images + API draft delivery: still provide one cover image and use `postprocess_wechat_article.py --no-images --publish-manifest --cover-image <cover>`.
- Missing images only: use `postprocess_wechat_article.py --missing-only --plan-only`, generate only listed files, then rerun the normal package command.
- Verification: run `verify_wechat_article_package.py <html>` before delivery.
- API draft delivery: run publish dry-run first; add `--create-draft` only after the user explicitly asks for草稿箱. Do not use browser automation.

## Completion

When an HTML workbench was produced, deliver the running loopback workbench URL first and the local HTML path second. Mention markdown, image directory, image jobs, manifest, and API result only when relevant. State any skipped images, missing account fields, API limitations, or unresolved risks plainly.
