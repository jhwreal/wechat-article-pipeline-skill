# Task 2 report

## RED

`node --test tests/workbench_save_behavior.test.mjs` initially failed because `assets/workbench-save-controller.js` did not exist (ENOENT).

## GREEN

`node --test tests/workbench_save_behavior.test.mjs` → 3 passed.

`python3 -m unittest wechat-article-pipeline/tests/test_serve_wechat_workbench.py -v` → 4 passed.

## Changes

- Added dependency-injected save controller with immediate local cache, 3000 ms debounce, manual save cancellation, and single-flight handling.
- Added safe bootstrap JSON helpers and generated bootstrap node; server uses bootstrap replacement with legacy fallback.
- Added controller behavior tests executed against production source.

## Self-review / risks

The template still contains compatibility constants sourced from bootstrap. Full browser smoke coverage and expanded status wiring remain for follow-up integration. Commit: `22b931e9e336979859ca8341c8bb9f47e9dab874`.

## Review follow-up

Removed stray markdown literal, inlined the production controller through the builder, added Save toolbar/status elements, wired bootstrap signature/storage key, and guarded initialization from scheduling. Follow-up commit: `86eddfd`.
