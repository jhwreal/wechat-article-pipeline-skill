# Image Production

Use this file after `postprocess_wechat_article.py --plan-only` creates `<slug>.image-jobs.json` and before final packaging.

All generation, avoid, regeneration, and image-influence rules live in [image-rules.json](image-rules.json). Do not duplicate or edit those rules here.

Default execution is single-pass: no A/B candidates and no agent-side image review of any slot, including the cover. Unless the user explicitly requests another ratio, every generated cover, body, and closing image must be strict 3:2 landscape; prefer a native 1536×1024 result. The user decides whether any image needs another generation pass.

Execution:

- Use `generation_queue[]` as the execution list. Each item maps to one final file in the canonical slot's `output`.
- Run at most `min(queue length, currently available worker slots)` image workers; refill a free slot as a worker finishes. Never encode a fixed worker count in the job contract.
- Do not print the full `generation_queue`, `image_rules_markdown`, job-level review details, or image base64 in the conversation. Show only a compact progress summary.
- Send only the queue item's `generation_prompt` (or the backward-compatible `prompt` copy) to image generation. The prompt must explicitly require strict 3:2 landscape output.
- Run image worker subagents up to the runtime's currently available worker capacity. Spawn workers without forking the full thread context; pass only `id`, `slot`, `generation_prompt`, and output path. If the queue is longer than the available capacity, start the next worker as soon as any worker finishes. Do not fall back to sequential generation unless the tool/runtime cannot launch multiple workers.
- Each worker saves its result directly to `<workspace>/image/<slug>/<output>`, such as `cover.png`, `body-1.png`, or `closing.png`.
- Do not inspect, compare, rank, or select images by default. This includes no cover check and no spot check. Keep job-level `review_contract` only as metadata for a later user-requested regeneration; do not include it in worker tasks.
- After generation, verify only that every named output file exists and that its pixel dimensions satisfy width:height = 3:2 with width greater than height. This is metadata validation, not visual review. After packaging, rely on `verify_wechat_article_package.py`; do not open generated images for visual QA unless the user explicitly asks.
- If a generated file is portrait, square, or otherwise not 3:2 landscape, rerun only that slot with the same content prompt plus the strict 3:2 landscape constraint. Do not use scripts to crop, stretch, pad, or deform a wrong-ratio image into compliance.
- If the user dislikes a generated image, rerun the same `generation_prompt` for only that slot and replace that slot's output.
- Continue packaging only after every final output named in `slots[].output` exists.
