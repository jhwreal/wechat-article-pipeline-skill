# WeChat Pipeline Reliability Refactor Design

## Goal

Rebuild the internal architecture behind WeChat draft delivery, the editable HTML workbench, and image-job execution so that the common workflow remains simple while failures become explicit and recoverable.

The user's established workflow is the product contract:

- every edit is cached locally immediately;
- three seconds without editing triggers a server save;
- the Save button immediately persists the newest state and cancels that edit cycle's pending autosave;
- a later edit starts a new three-second autosave cycle;
- existing commands, article paths, and old article packages remain usable;
- no account, credential, `.env`, or remote draft is changed during local refactoring and tests.

## Compatibility Boundary

The refactor may replace internal modules and JSON layouts, but it must preserve:

- the existing CLI entry points;
- `<slug>.md`, `<slug>.html`, `<slug>.job.json`, `<slug>.image-jobs.json`, and `<slug>.publish-manifest.json` locations;
- direct `file://` workbench use with `localStorage`;
- current dry-run behavior for `publish_wechat_api.py`;
- legacy image-jobs reading when `schema_version` is absent;
- existing successful result fields such as `draft_media_id`, `draft_verification`, `preview`, and `original_issue_increment`.

New writers emit the new contracts. Compatibility readers normalize old contracts at their boundaries; internal code does not carry parallel v1 and v2 branches.

## Architecture

### Shared atomic persistence

`scripts/atomic_files.py` owns durable local writes. A write uses a temporary file in the destination directory, flushes and `fsync`s it, preserves the requested or existing mode, then replaces the destination with `os.replace`. JSON writers serialize before touching the destination. This helper is used for publish receipts, workbench state, article files, and account counter updates.

### Draft-delivery state machine

`scripts/publish_run_state.py` owns the additive result journal used by `publish_wechat_api.py`.

The journal contains:

```json
{
  "status": "success | partial_success | failed | unknown",
  "operation_state": {
    "draft_add": {"state": "pending | in_progress | succeeded | failed | unknown"},
    "increment_original_issue": {"requested": true, "state": "pending"},
    "verify_draft": {"requested": true, "state": "pending"},
    "send_preview": {"requested": true, "state": "pending"}
  },
  "last_error": null
}
```

Each irreversible or externally visible operation is checkpointed before and after the call. Immediately after `draft/add` returns a `media_id`, the journal records `draft_media_id`, marks `draft_add` succeeded, sets `status` to `partial_success`, and atomically replaces the result file before any verification, preview, or issue-number increment runs.

`--resume` reads the same result file, validates the manifest fingerprint and account identity, and skips image uploads, cover upload, and `draft/add`. Safe pending work resumes. An `in_progress` draft without a media ID is `unknown` and cannot be retried automatically because exactly-once creation cannot be proven locally. An interrupted preview is also `unknown`; only `--retry-preview` explicitly accepts the duplicate-preview risk.

Issue-number increment becomes an idempotent compare-and-set: expected issue to next issue succeeds, already-next is accepted, and any later or unrelated value is a conflict. It never rolls a counter backward.

### Safe workbench bootstrap

The template has one non-executable bootstrap node:

```html
<script type="application/json" id="wechat-bootstrap">...</script>
```

`build_wechat_article_workbench.py` serializes Markdown, metadata, signature, and default presentation state once. After JSON serialization it escapes `<`, `>`, `&`, U+2028, and U+2029, preventing an embedded `</script>` from terminating the HTML element. The browser parses only `textContent`; no user-controlled value is concatenated into executable JavaScript.

The template contains exactly one `{{BOOTSTRAP_JSON}}` replacement point. Missing or duplicate replacement points are build errors. `read_bootstrap()` and `replace_bootstrap()` also recognize legacy constant-based workbenches so the first server save migrates them without losing content.

### Browser save controller

The browser maintains three independent facts:

- local cache state;
- newest client mutation waiting for or acknowledged by the server;
- server-derived manifest and image state.

Every input event synchronously updates `localStorage`, marks the UI as locally cached, clears the previous timer, and starts a 3000 ms timer. The Save button clears that timer and immediately queues the latest snapshot. A later input event creates a new timer.

Only one server request is active at a time. While it is active, repeated changes replace one pending snapshot instead of creating more requests. Responses carry a revision and mutation ID; an older response cannot mark a newer mutation saved. HTTP 409 adopts the server's current status and keeps only the newest unsaved snapshot; it never blindly retries an obsolete base revision.

The pure save controller lives in `assets/workbench-save-controller.js`. The builder inlines that production source into the single-file template, while Node tests execute the same source with fake storage, clock, and transport adapters. Initial page rendering explicitly disables scheduling so merely opening a workbench does not create a revision.

The toolbar contains a visible Save button. Separate compact elements report local/article save, manifest refresh, and image readiness so one state cannot overwrite another.

### Local server and revisioned document state

`scripts/workbench_document.py` owns article persistence. `serve_wechat_workbench.py` becomes an HTTP adapter.

GET `/__wechat_workbench/status` returns the current revision, manifest state, asset state, and a random per-server token. The browser can read this response only from the same origin. POST `/__wechat_workbench/save` requires:

- `Content-Type: application/json`;
- an allowed loopback `Host`;
- an exact same-origin `Origin`;
- `X-Workbench-Token` matching the current server process.

Direct `file://` mode never calls these endpoints and remains local-cache only.

A save request contains `baseRevision`, `clientMutationId`, Markdown, theme color, font size, and font family. Under a short lock, the document validates the revision and stages HTML, Markdown, and job JSON. It writes a transaction journal containing target hashes, replaces each staged file, then commits the new revision and committed hashes in the sidecar. On startup, an unfinished journal is completed when its staged files remain valid; otherwise the document reports `recovery_required` instead of accepting a normal save. The sidecar lives at `files/wechat-article-pipeline/<slug>/workbench-state.json` and is the durable server state.

### Manifest refresh and asset freshness

Manifest generation is not part of the synchronous save lock. A single background coordinator coalesces immutable refresh requests containing the revision, job JSON snapshot, resolved paths, publisher selectors, and source state. It retains only the newest request, writes the job snapshot beside the original job so relative asset paths keep their meaning, writes a candidate manifest to a temporary path, verifies that the candidate still targets the current revision, then atomically replaces the public manifest. An older task can never overwrite a newer revision or generate against a newer job while claiming an older revision.

Publisher parameters already present in the manifest or state—including article slug, environment-file path, and account selector—are preserved across refreshes.

The sidecar records:

```json
{
  "coreRevision": 13,
  "manifestRevision": 12,
  "manifestState": "pending | ready | stale | failed | unavailable",
  "assetState": "ready | stale | missing",
  "staleVisuals": [],
  "missingVisuals": [],
  "lastManifestError": ""
}
```

The sidecar stores a source fingerprint and asset fingerprint for each visual. Source fingerprints use the article title plus the segment associated with the slot; asset fingerprints use content and file metadata from paths resolved relative to the job. Presentation-only changes do not affect either value. Existing images are never silently deleted. Changed source with the same asset marks a slot stale; a missing file marks it missing. Replacing or regenerating the file advances the asset fingerprint and adopts a new ready baseline for the current source. The workbench reports this explicitly, the refreshed manifest carries the state, and verification/publishing refuses a manifest whose source state is stale or missing. A workbench without a manifest reports `not_configured` and does not start a refresh worker.

### Image-jobs v2

`scripts/image_jobs_contract.py` is the only image-jobs reader and validator. Its normalized in-memory shape is:

```json
{
  "kind": "wechat-image-jobs",
  "schema_version": 2,
  "article": {},
  "rules": {"version": 6, "sha256": "..."},
  "review_defaults": {},
  "slots": [],
  "generation_queue": []
}
```

`slots` is the only source of image-plan and slot-specific review data. It uses a fixed whitelist of identity, plan, local-context, visual, and slot-specific review fields; it does not repeat article defaults, global style, prompts, tasks, common avoid rules, or a complete review contract. Common avoid and quality-floor rules live once in `review_defaults`. `generation_queue` is the only prompt owner and contains only `slot`, authoritative `output`, and `generation_prompt`. The writer no longer emits duplicate `jobs`, `image_slots`, nested `image_plan.image_slots`, `generation_task`, `prompt`, full rule copies, rule Markdown, or fixed concurrency capacity.

When `schema_version` is absent or explicitly `1`, the reader treats the document as v1 and normalizes `jobs`, `image_slots`, or nested image slots plus legacy prompt/output fallbacks. Older A/B candidate files are recognized by variants or duplicate queue slots and deterministically collapse to their first route while keeping the final output. Conflicting copies in current single-pass v1 fail rather than silently choosing one. Unknown future versions fail explicitly. All consumers use the normalized contract and exact `output` filenames. Support `image-plan.json` and Markdown are derived through contract functions only when packaging needs them.

Image generation concurrency is an orchestration decision, not article data:

```text
worker_count = min(queue_length, currently_available_worker_slots)
```

As one worker completes, the next queued image may start. No fixed worker count is documented or serialized.

## Error Handling

- Local writes preserve the previous valid destination on serialization or replacement failure.
- Draft creation with an unknowable remote outcome stops with `unknown`; it never guesses and creates another draft.
- Post-draft failures exit non-zero after preserving a `partial_success` receipt.
- Core workbench saving can succeed even when manifest generation fails; the UI never labels the package fully ready in that state.
- Revision conflicts return HTTP 409 with current status rather than overwriting newer content.
- Stale and missing images block publish validation but remain on disk for inspection or deliberate regeneration.
- Unknown image-job schema versions fail with an actionable message.

## Testing Strategy

All behavior changes follow red-green-refactor.

Tests cover:

- immediate draft receipt before any post-draft action;
- partial success, atomic-write failure, resume, preview uncertainty, and idempotent issue increment;
- bootstrap round trips for `</script>`, mixed case tags, backticks, `${...}`, quotes, U+2028, and U+2029;
- same-origin token enforcement and invalid content types;
- immediate local cache, 3000 ms debounce, manual-save cancellation, future-edit rearming, and single-flight coalescing;
- revision conflicts, old manifest task suppression, manifest failure isolation, parameter preservation, and asset-state transitions;
- v1/v2 normalization equivalence, strict v2 output, missing-only filtering, unknown versions, dangling queue entries, and all consumer integrations;
- the existing package suite, standalone workbench behavior, and a browser-level smoke test.

No test performs a real WeChat API call or changes live credentials.
