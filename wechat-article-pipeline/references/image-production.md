# Image Production

Use this file after `postprocess_wechat_article.py --plan-only` creates `<slug>.image-jobs.json` and before final packaging.

All generation, avoid, regeneration, and image-influence rules live in [image-rules.json](image-rules.json). Do not duplicate or edit those rules here.

Default execution is single-pass: no A/B candidates and no agent-side image review of any slot, including the cover. The user decides whether any image needs another generation pass.

Execution:

- Use `generation_queue[]` as the execution list. Each item maps to one final file in `jobs[].output`.
- Do not print the full `generation_queue`, `image_rules_markdown`, job-level `review_contract`, or image base64 in the conversation. Show only a compact progress summary.
- Send only the queue item's `generation_prompt` (or the backward-compatible `prompt` copy) to image generation.
- Run image worker subagents in concurrent batches of up to 4. Spawn workers without forking the full thread context; pass only `id`, `slot`, `generation_prompt`, and output path. If there are more than 4 images, keep a queue and start the next worker as soon as any worker finishes. Do not fall back to sequential generation unless the tool/runtime cannot launch multiple workers.
- Each worker saves its result directly to `<workspace>/image/<slug>/<output>`, such as `cover.png`, `body-1.png`, or `closing.png`.
- Do not inspect, compare, rank, or select images by default. This includes no cover check and no spot check. Keep job-level `review_contract` only as metadata for a later user-requested regeneration; do not include it in worker tasks.
- After generation, verify only that every named output file exists before packaging. After packaging, rely on `verify_wechat_article_package.py`; do not open generated images for visual QA unless the user explicitly asks.
- If the user dislikes a generated image, rerun the same `generation_prompt` for only that slot and replace that slot's output.
- Continue packaging only after every final output named in `jobs[].output` exists.
