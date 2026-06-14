# Image Production

Use this file after `postprocess_wechat_article.py --plan-only` creates `<slug>.image-jobs.json` and before final packaging.

All generation, avoid, selection, and image-influence rules live in [image-rules.json](image-rules.json). Do not duplicate or edit those rules here.

Before the first image call, print `image_rules_markdown` from `<slug>.image-jobs.json` in the conversation so the user can adjust the skill if a rule looks wrong.

Execution:

- Use `generation_queue[]` as the execution list.
- Send only `generation_prompt` (or the backward-compatible `prompt` copy) to image generation.
- Keep `review_contract` for selection and regeneration decisions.
- Save candidates under `<workspace>/image/<slug>/candidates/` using `candidate_output`.
- Show all candidates in the conversation grouped by slot and id after generation finishes.
- If the user selects, use the user's selection. If the user does not intervene, choose the better candidate and state the choice briefly.
- Copy or rename selected candidates to final outputs: `cover.png`, `body-1.png`, `body-2.png`, ..., `closing.png`.
- Continue packaging only after every final output named in `jobs[].output` exists.
