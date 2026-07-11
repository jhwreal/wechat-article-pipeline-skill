# WeChat Pipeline Reliability Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fragile publisher, workbench persistence, and duplicated image-job internals with recoverable state machines and canonical contracts while keeping the user's existing commands and artifact paths.

**Architecture:** Add focused atomic-file, publish-run, workbench-document, and image-jobs contract modules. Keep current CLI scripts as adapters, make browser saving revision-aware and single-flight, and normalize legacy inputs at one boundary before the rest of the pipeline uses v2 data.

**Tech Stack:** Python 3 standard library, HTML/CSS/vanilla JavaScript, `unittest`, Node.js built-in test runner.

## Global Constraints

- Every edit writes `localStorage` synchronously.
- Autosave starts only after exactly 3000 ms without a newer edit.
- Clicking Save clears the pending timer, sends the newest snapshot immediately, and does not disable autosave for later edits.
- At most one workbench save request is active; only one newest pending snapshot is retained.
- Existing CLI entry points, main flags, artifact names, and direct `file://` mode remain usable.
- New image-job files use schema version 2; files without `schema_version` remain readable as legacy v1.
- Existing images are not deleted automatically.
- No test contacts WeChat, edits the repository `.env`, or uses live credentials.
- Production code is written only after the covering test has been observed failing for the intended reason.

---

### Task 1: Atomic files and recoverable draft delivery

**Files:**

- Create: `wechat-article-pipeline/scripts/atomic_files.py`
- Create: `wechat-article-pipeline/scripts/publish_run_state.py`
- Modify: `wechat-article-pipeline/scripts/publish_wechat_api.py`
- Modify: `wechat-article-pipeline/scripts/wechat_account_config.py`
- Create: `tests/test_publish_wechat_receipt.py`
- Modify: `tests/test_wechat_account_config.py`

**Interfaces:**

- `atomic_write_text(path: Path, text: str, *, mode: int | None = None) -> None`
- `atomic_write_json(path: Path, data: Mapping[str, Any], *, mode: int | None = None) -> None`
- `manifest_fingerprint(path: Path) -> str`
- `new_publish_run(...)->dict[str, Any]`
- `checkpoint(path: Path, run: dict[str, Any]) -> None`
- `mark_started`, `mark_succeeded`, and `mark_failed` update one `operation_state` entry without removing legacy result fields.
- `compare_and_set_env_value(path: Path, key: str, expected: str, value: str) -> str` returns `updated` or `already_applied`, and raises `ValueError` on conflict.

- [ ] **Step 1: Write receipt and resume tests before implementation**

Create tests whose fakes make network access impossible. The essential receipt assertion is:

```python
def fake_verify(media_id, expected_title, access_token):
    receipt = json.loads(result_path.read_text(encoding="utf-8"))
    testcase.assertEqual(receipt["draft_media_id"], "media-123")
    testcase.assertEqual(receipt["status"], "partial_success")
    testcase.assertEqual(receipt["operation_state"]["draft_add"]["state"], "succeeded")
    raise RuntimeError("verify stopped")
```

Cover these independently named behaviors:

```text
test_draft_receipt_exists_before_verify_runs
test_verify_failure_preserves_partial_success_and_exits_nonzero
test_resume_skips_upload_and_draft_add
test_unknown_preview_requires_retry_preview
test_draft_add_without_media_id_cannot_resume
test_success_keeps_legacy_result_fields
test_atomic_write_preserves_previous_destination_on_failure
test_issue_increment_is_idempotent_and_never_rolls_back
```

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```bash
python3 -m unittest tests.test_publish_wechat_receipt tests.test_wechat_account_config -v
```

Expected: failures because the atomic helper, result state, resume flags, and compare-and-set behavior do not exist.

- [ ] **Step 3: Implement atomic local persistence**

Use the same-directory replace sequence in `atomic_files.py`:

```python
payload = text.encode("utf-8")
fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
try:
    with os.fdopen(fd, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    if target_mode is not None:
        os.chmod(temp_name, target_mode)
    os.replace(temp_name, path)
finally:
    if os.path.exists(temp_name):
        os.unlink(temp_name)
```

Serialize JSON with `ensure_ascii=False`, `indent=2`, and one trailing newline before entering this sequence.

- [ ] **Step 4: Implement the additive publish journal**

Initialize all requested operations as `pending`, checkpoint `draft_add=in_progress` before the API call, and checkpoint the returned media ID immediately. Add CLI flags:

```python
parser.add_argument("--resume", action="store_true")
parser.add_argument("--retry-preview", action="store_true")
```

`--resume` requires an existing `--out` result and never invokes body upload, cover upload, or `create_draft`. Validate the stored manifest SHA-256 and account alias/name. A post-draft error is checkpointed before it is re-raised so the command remains non-zero.

- [ ] **Step 5: Make issue increment compare-and-set**

For manifest issue `9`, accept only these `.env` states:

```text
9  -> atomically write 10 and return updated
10 -> write nothing and return already_applied
any other value -> raise conflict and preserve the file
```

Preserve the original file mode and unrelated lines.

- [ ] **Step 6: Run Task 1 tests and the publisher regression tests**

Run:

```bash
python3 -m unittest tests.test_publish_wechat_receipt tests.test_publish_wechat_api tests.test_wechat_account_config tests.test_skill_p1_contract.SkillP1ContractTest.test_publish_script_defaults_to_dry_run_without_network -v
```

Expected: all selected tests pass with no network calls.

- [ ] **Step 7: Commit Task 1**

```bash
git add wechat-article-pipeline/scripts/atomic_files.py wechat-article-pipeline/scripts/publish_run_state.py wechat-article-pipeline/scripts/publish_wechat_api.py wechat-article-pipeline/scripts/wechat_account_config.py tests/test_publish_wechat_receipt.py tests/test_wechat_account_config.py
git commit -m "refactor: make WeChat draft delivery recoverable"
```

---

### Task 2: Safe bootstrap and the user's save behavior

**Files:**

- Modify: `wechat-article-pipeline/scripts/build_wechat_article_workbench.py`
- Modify: `wechat-article-pipeline/scripts/serve_wechat_workbench.py`
- Create: `wechat-article-pipeline/assets/workbench-save-controller.js`
- Modify: `wechat-article-pipeline/assets/templates/wechat-md-workbench.template.v3.html`
- Modify: `wechat-article-pipeline/tests/test_serve_wechat_workbench.py`
- Create: `tests/workbench_save_behavior.test.mjs`

**Interfaces:**

- `html_safe_json(value: Any) -> str` escapes `<`, `>`, `&`, U+2028, and U+2029 after `json.dumps`.
- `read_bootstrap(html_text: str) -> dict[str, Any]` reads new bootstrap JSON or legacy constants.
- `replace_bootstrap(html_text: str, updates: Mapping[str, Any]) -> str` updates or migrates one bootstrap node.
- One `wechat-bootstrap` JSON node contains `markdown`, `metadata`, `signature`, `storageKey`, and `workbenchState`.
- `createWorkbenchSaveController(options)` exposes `cacheAndSchedule()`, `saveNow()`, `flush()`, and `getState()` for real browser use and fake-clock tests.

- [ ] **Step 1: Write bootstrap injection tests**

Build a workbench using values containing each payload:

```python
payloads = [
    "</script><script>window.pwned=1</script>",
    "</ScRiPt>",
    "`${window.pwned=2}`",
    "\u2028\u2029",
    "双引号\"与单引号'",
]
```

For every payload, use `html.parser.HTMLParser` to assert there is exactly one bootstrap node, the raw closing-script payload does not appear inside it, `json.loads(node_text)` round-trips the original values, and the executable-script-node count does not increase. Also assert a missing or duplicate `{{BOOTSTRAP_JSON}}` placeholder fails explicitly and a legacy constant-based HTML document migrates on first save.

- [ ] **Step 2: Write real save-controller tests**

Execute the production `assets/workbench-save-controller.js` with Node `vm.runInNewContext()`. Use fake `setTimeout`, `clearTimeout`, storage adapter, and transport adapter to assert:

```text
input writes storage before any timer runs
no server call occurs at 2999 ms
one server call occurs at 3000 ms
another input replaces the pending timer
manual Save clears the timer and calls immediately
no abandoned timer calls after manual Save
a later input arms a fresh 3000 ms timer
twenty edits during one in-flight request retain only the newest pending snapshot
an old response cannot mark the newest mutation saved
initial rendering does not arm a timer or call the server
```

- [ ] **Step 3: Run bootstrap and save tests and verify RED**

Run:

```bash
python3 -m unittest wechat-article-pipeline/tests/test_serve_wechat_workbench.py -v
node --test tests/workbench_save_behavior.test.mjs
```

Expected: failures because bootstrap data is still executable JavaScript, debounce is 500 ms, and no manual-save/single-flight controller exists.

- [ ] **Step 4: Replace all inline data substitutions with one bootstrap JSON**

The generated template must contain:

```html
<script type="application/json" id="wechat-bootstrap">{{BOOTSTRAP_JSON}}</script>
<script>
  const BOOTSTRAP = JSON.parse(document.getElementById('wechat-bootstrap').textContent);
</script>
```

Require exactly one placeholder before replacing it. Remove user data from `DEFAULT_MARKDOWN` template literals and raw metadata/signature/state replacements. The post-parse JavaScript may expose compatibility aliases sourced from `BOOTSTRAP`, but bootstrap remains the sole default authority, including the initial theme control value. Keep clipboard image data in its existing dedicated generated script because it is produced from trusted local image bytes, not article text.

- [ ] **Step 5: Implement the save controller and toolbar button**

Add `<button id="saveArticle" class="btn">保存</button>` before the copy button. On every edit or style change call `cacheAndSchedule()` after rendering. `saveNow()` must clear the current timer, cache the same snapshot, and queue it immediately. It must not set a permanent autosave-disabled flag.

Inline the production controller source into the template so the output remains one HTML file. Give the controller dependency-injected clock, storage, snapshot, mutation ID, transport, and state callbacks. Add three independent status elements. Their text uses these exact distinctions when applicable:

```text
已缓存到本机
正在保存正文…
正文已保存
发布清单更新中
图片待复核
保存失败
```

Update `serve_wechat_workbench.py` to use `replace_bootstrap()` for new workbenches while keeping a first-save migration path for legacy constant HTML. Initial load must render with scheduling disabled; only an input/change event or Save click enters the controller.

- [ ] **Step 6: Run Task 2 tests and existing sync tests**

Run:

```bash
python3 -m unittest wechat-article-pipeline/tests/test_serve_wechat_workbench.py -v
node --test tests/workbench_save_behavior.test.mjs tests/workbench_sync_behavior.test.mjs
```

Expected: all tests pass.

- [ ] **Step 7: Commit Task 2**

```bash
git add wechat-article-pipeline/scripts/build_wechat_article_workbench.py wechat-article-pipeline/scripts/serve_wechat_workbench.py wechat-article-pipeline/assets/workbench-save-controller.js wechat-article-pipeline/assets/templates/wechat-md-workbench.template.v3.html wechat-article-pipeline/tests/test_serve_wechat_workbench.py tests/workbench_save_behavior.test.mjs
git commit -m "refactor: secure and simplify workbench saving"
```

---

### Task 3: Revisioned workbench server and asynchronous manifest state

**Files:**

- Create: `wechat-article-pipeline/scripts/workbench_document.py`
- Modify: `wechat-article-pipeline/scripts/serve_wechat_workbench.py`
- Modify: `wechat-article-pipeline/assets/workbench-save-controller.js`
- Modify: `wechat-article-pipeline/assets/templates/wechat-md-workbench.template.v3.html`
- Modify: `wechat-article-pipeline/scripts/make_wechat_publish_manifest.py`
- Modify: `wechat-article-pipeline/scripts/verify_wechat_article_package.py`
- Modify: `wechat-article-pipeline/scripts/publish_wechat_api.py`
- Modify: `wechat-article-pipeline/tests/test_serve_wechat_workbench.py`
- Modify: `tests/workbench_save_behavior.test.mjs`

**Interfaces:**

- `RevisionConflict(current_status: dict[str, Any])`
- `WorkbenchDocument.status() -> dict[str, Any]`
- `WorkbenchDocument.save(payload: Mapping[str, Any]) -> dict[str, Any]`
- `WorkbenchDocument.close() -> None`
- `ManifestRefreshRequest` is an immutable dataclass containing revision, job snapshot, paths, article slug, env file, account selector, and source state.
- `ManifestRefreshCoordinator.request(request: ManifestRefreshRequest) -> None`
- `inspect_visuals(markdown, visuals, *, job_dir, baselines) -> VisualStatus`
- GET `/__wechat_workbench/status`; POST `/__wechat_workbench/save`.

- [ ] **Step 1: Add revision, security, coalescing, and asset tests**

Cover these exact cases with temporary workspaces and fake manifest runners:

```text
same baseRevision saves once and increments revision
stale baseRevision raises RevisionConflict without changing files
save returns before a blocked manifest runner completes
revision 2 manifest cannot replace revision 3 output
twenty rapid saves request only the current or final manifest revision
manifest failure leaves core save successful and state failed/stale
existing article slug, env file, and account selector survive refresh
style-only save keeps assetState ready
source edit marks the affected visual stale
deleted image marks the visual missing
invalid Origin, Host, token, and Content-Type are rejected
valid same-origin token request succeeds
status handshake failure leaves browser in local-cache-only mode
old constant workbench migrates to bootstrap on first save
unfinished file transaction completes on startup or reports recovery_required
stale visual returns ready after its asset is regenerated
close drains or cancels worker state without publishing an old candidate
```

- [ ] **Step 2: Run server tests and verify RED**

Run:

```bash
python3 -m unittest wechat-article-pipeline/tests/test_serve_wechat_workbench.py -v
```

Expected: failures because revisions, sidecar state, token checks, background refresh, and asset fingerprints do not exist.

- [ ] **Step 3: Extract revisioned document persistence**

The sidecar starts with revision zero when absent. A valid save requires `baseRevision == coreRevision`. Stage every new file and hash first, persist a transaction journal, replace the staged files, then commit `coreRevision += 1`, committed hashes, asset state, and manifest target while clearing the journal. Startup completes an intact transaction or enters `recovery_required` if neither staged nor committed hashes form a consistent revision. Return:

```json
{
  "saved": true,
  "revision": 1,
  "clientMutationId": "client-1",
  "manifest": {"state": "pending", "targetRevision": 1},
  "assets": {"state": "ready", "staleVisuals": [], "missingVisuals": []}
}
```

- [ ] **Step 4: Implement one-worker manifest coalescing**

Keep at most one active refresh and one immutable newest request. Its job snapshot is written to a temporary file in the original job directory before manifest generation so relative image paths remain valid. Under the document lock, replace the public manifest only if `candidate_revision == coreRevision`; otherwise discard the candidate and process the newest request. Persist errors without rolling back the core save. `close()` must be called from the server's `finally` block.

- [ ] **Step 5: Enforce HTTP request boundaries**

Generate a token with `secrets.token_urlsafe(32)`. The status endpoint returns it only over loopback HTTP. On page load, the browser fetches status and stores its token/revision; when unavailable it stays local-cache only. Save sends `baseRevision`, `clientMutationId`, and `X-Workbench-Token`, and accepts only JSON, exact loopback Host with the bound port, exact `Origin` equal to the server origin, and the token header. Return 409 plus current status for revision conflicts, 403 for origin/token/host failures, and 415 for invalid content type. The controller adopts a 409 revision without replaying an obsolete request over newer server content.

- [ ] **Step 6: Make stale source state block verification and publishing**

Manifest generation includes:

```json
"source_state": {
  "core_revision": 3,
  "manifest_revision": 3,
  "asset_state": "stale",
  "stale_visuals": ["body-1"],
  "missing_visuals": []
}
```

`verify_wechat_article_package.py` records a failed check and `publish_wechat_api.validate_manifest` raises `SystemExit` when revisions differ or assets are stale/missing. Manifests without `source_state` remain valid legacy inputs.

Persist each visual baseline as source and asset fingerprints. If source changes while the asset fingerprint is unchanged, mark stale; if the asset is missing, mark missing; if a stale or missing slot later has a new asset fingerprint, adopt the current source/asset pair as ready. A missing manifest is `not_configured`, never `pending`, and starts no worker.

- [ ] **Step 7: Run Task 3 tests and package regressions**

Run:

```bash
python3 -m unittest wechat-article-pipeline/tests/test_serve_wechat_workbench.py tests.test_package_wechat_article_bundle tests.test_wechat_draft_html -v
node --test tests/workbench_save_behavior.test.mjs tests/workbench_sync_behavior.test.mjs
```

Expected: all selected tests pass and the manifest runner is never invoked inside the synchronous save lock.

- [ ] **Step 8: Commit Task 3**

```bash
git add wechat-article-pipeline/scripts/workbench_document.py wechat-article-pipeline/scripts/serve_wechat_workbench.py wechat-article-pipeline/assets/workbench-save-controller.js wechat-article-pipeline/assets/templates/wechat-md-workbench.template.v3.html wechat-article-pipeline/scripts/make_wechat_publish_manifest.py wechat-article-pipeline/scripts/verify_wechat_article_package.py wechat-article-pipeline/scripts/publish_wechat_api.py wechat-article-pipeline/tests/test_serve_wechat_workbench.py tests/workbench_save_behavior.test.mjs
git commit -m "refactor: add revisioned workbench persistence"
```

---

### Task 4: Canonical image-jobs v2 and consumer migration

**Files:**

- Create: `wechat-article-pipeline/scripts/image_jobs_contract.py`
- Modify: `wechat-article-pipeline/scripts/make_wechat_article_image_jobs.py`
- Modify: `wechat-article-pipeline/scripts/postprocess_wechat_article.py`
- Modify: `wechat-article-pipeline/scripts/package_wechat_article_bundle.py`
- Modify: `wechat-article-pipeline/scripts/build_wechat_article_workbench.py`
- Modify: `wechat-article-pipeline/scripts/verify_wechat_article_package.py`
- Modify: `tests/test_skill_p0_contract.py`
- Modify: `tests/test_skill_p1_contract.py`
- Modify: `tests/test_package_wechat_article_bundle.py`
- Create: `tests/test_image_jobs_contract.py`

**Interfaces:**

- `normalize_image_jobs(payload: Mapping[str, Any]) -> dict[str, Any]`
- `validate_image_jobs(payload: Mapping[str, Any]) -> dict[str, Any]`
- `filter_missing_image_jobs(payload: Mapping[str, Any], exists: Callable[[str], bool]) -> dict[str, Any]`
- `slots_by_name(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]`
- `derive_image_plan(payload: Mapping[str, Any]) -> dict[str, Any]`
- `render_image_plan_markdown(payload: Mapping[str, Any]) -> str`
- v2 queue item keys are exactly `slot`, `output`, and `generation_prompt`.
- `output` is the authoritative relative filename for generation, missing checks, packaging, and verification.
- Running `image_jobs_contract.py <path>` validates one file and exits zero only for a normalized valid contract.

- [ ] **Step 1: Replace shape-pinning tests with contract tests**

In `test_image_jobs_contract.py`, add a minimal current v1 fixture containing `jobs`, nested `generation_task`, and `prompt`, an older candidate v1 fixture containing variants and duplicate queue slots, plus equivalent v2 fixtures. Assert normalization equality for article, slot name/output/context/review data, and generation prompt. Add tests for:

```text
v2 writer emits kind/schema_version/article/rules/review_defaults/slots/generation_queue
v2 writer omits jobs/image_slots/image_plan/generation_task/prompt/image_rules/image_rules_markdown/image_execution
queue keys are exactly slot/output/generation_prompt
generation_prompt exists only in generation_queue
slots omit article defaults, common review defaults, prompts, and tasks
slot and output values are unique
each queue slot references exactly one slot
queue output equals its slot output
unsafe absolute or parent-relative output fails
unknown schema version fails
dangling queue slot fails
missing-only filters slots and queue together
missing-only calls exists(output), including slot body-1 with output diagram.webp
no-image mode uses the same v2 schema with empty arrays
v1 and v2 package to equivalent visuals and support plans
historical A/B v1 deterministically selects the first route and final output
conflicting prompt copies in single-pass v1 fail
normalization is idempotent and does not mutate input
```

- [ ] **Step 2: Run image tests and verify RED**

Run:

```bash
python3 -m unittest tests.test_image_jobs_contract tests.test_skill_p0_contract tests.test_skill_p1_contract tests.test_package_wechat_article_bundle -v
```

Expected: failures because the writer still emits the duplicated v1 layout and consumers read different fallbacks independently.

- [ ] **Step 3: Implement the centralized v1/v2 normalizer**

Treat absent or explicit `schema_version: 1` as v1. For v1, select slots in this order: `jobs`, top-level `image_slots`, nested `image_plan.image_slots`. Map top-level article fields to `article.*`, with nested plan and the first full job as fallbacks. Resolve prompt by matching queue item, then nested generation task, then job; at each level prefer `generation_prompt` to `prompt`. Resolve output from job output, nested task output/final output, queue output/final output, then `<slot>.png`. Current single-pass duplicate copies must agree. Detect variants or duplicate queue slots as historical candidate format, choose the first route deterministically, and preserve its final output. Unknown explicit versions raise `ValueError`.

Canonicalize rule SHA-256 from sorted compact JSON. Validate the normalized v2 shape once: kind/version, non-empty unique slot names and outputs, safe relative output filenames, exact non-empty queue keys, queue/slot bijection, and matching queue/slot outputs. Convert contract errors at CLI boundaries into path-qualified messages rather than tracebacks.

- [ ] **Step 4: Make the image planner write only v2**

Before constructing the queue, reduce every slot to a fixed whitelist: `index`, `name`, `output`, `position`, `role`, `image_type`, `target_effect`, `local_context`, `source_context`, `content_focus`, `visual_distance`, `composition`, `emotional_tone`, `abstraction_level`, `information_density`, `visual_type`, `text_budget`, `purpose`, `must_include`, `quality_gate`, `variation_note`, and `selection_criteria`. Prompt fields exist only in a temporary local mapping and the queue. Common `must_avoid` and `quality_floor` values exist only in `review_defaults`. The top-level result is:

```python
{
    "kind": "wechat-image-jobs",
    "schema_version": 2,
    "article": article_record,
    "rules": {"version": rules["version"], "sha256": rules_digest},
    "review_defaults": review_defaults,
    "slots": slots,
    "generation_queue": [
        {"slot": slot["name"], "output": slot["output"], "generation_prompt": prompts[slot["name"]]}
        for slot in slots
    ],
}
```

Store only slot-specific review fields in each canonical slot and remove prompt/task/article/default-review compatibility copies.

- [ ] **Step 5: Migrate every consumer to the contract module**

The planner's own `filter_missing_jobs`, `postprocess`, packager, and verifier must call the shared normalizer. All file discovery uses the exact canonical `output`, while `infer_image_dir_name` reads `article.slug`. `--debug-plan` calls `render_image_plan_markdown()` instead of reading a removed field. No consumer may read `jobs`, `image_slots`, or nested image slots directly. The packager normalizes image-jobs and derives the workbench `image_plan`; the workbench support writer only serializes that already-derived plan. Derive optional `image-plan.json` and Markdown from `article + slots`; do not put them back into the authoritative image-jobs JSON.

- [ ] **Step 6: Measure and assert the payload reduction**

For the existing four-slot `examples/method-article.md`, serialize sorted compact UTF-8 v2 and compare it with the frozen base-commit v1 byte count of 133704:

```python
self.assertLess(len(v2_bytes), 133704 * 0.35)
```

This allows at least a 65% reduction while the observed target is approximately 80%.

- [ ] **Step 7: Run Task 4 tests and full Python package tests**

Run:

```bash
python3 -m unittest tests.test_image_jobs_contract -v
python3 -m unittest discover -s tests -v
python3 -m unittest discover -s wechat-article-pipeline/tests -v
```

Expected: all tests pass, including legacy fixtures.

- [ ] **Step 8: Commit Task 4**

```bash
git add wechat-article-pipeline/scripts/image_jobs_contract.py wechat-article-pipeline/scripts/make_wechat_article_image_jobs.py wechat-article-pipeline/scripts/postprocess_wechat_article.py wechat-article-pipeline/scripts/package_wechat_article_bundle.py wechat-article-pipeline/scripts/build_wechat_article_workbench.py wechat-article-pipeline/scripts/verify_wechat_article_package.py tests/test_image_jobs_contract.py tests/test_skill_p0_contract.py tests/test_skill_p1_contract.py tests/test_package_wechat_article_bundle.py
git commit -m "refactor: introduce canonical image jobs v2"
```

---

### Task 5: Skill guidance, schemas, and forward compatibility

**Files:**

- Modify: `wechat-article-pipeline/SKILL.md`
- Modify: `wechat-article-pipeline/references/image-production.md`
- Modify: `wechat-article-pipeline/references/image-rules.json`
- Modify: `wechat-article-pipeline/references/job-schema.md`
- Modify: `wechat-article-pipeline/references/publishing.md`
- Modify: `wechat-article-pipeline/references/workflow.md`
- Modify: `tests/test_skill_p0_contract.py`
- Modify: `tests/test_skill_p1_contract.py`

**Interfaces:**

- `SKILL.md` remains below 1200 whitespace-delimited words.
- `image-rules.json` version becomes 6 and contains visual rules only, not runtime worker capacity.
- The execution instruction is `min(queue length, currently available worker slots)` and contains no fixed number.

- [ ] **Step 1: Write documentation-contract tests first**

Assert:

```text
SKILL.md is at most 1200 words
SKILL.md and image-production contain no fixed image-worker count
image-rules version is 6 and has no max_parallel_subagents
job-schema documents v2 and legacy v1 read compatibility
publishing documents partial_success/unknown/resume/retry-preview
workflow documents local cache, three-second autosave, and manual Save semantics
```

- [ ] **Step 2: Run the documentation tests and verify RED**

Run:

```bash
python3 -m unittest tests.test_skill_p0_contract tests.test_skill_p1_contract -v
```

Expected: failures for the pre-existing 1331-word SKILL, fixed concurrency text, old image schema, and missing recovery/save documentation.

- [ ] **Step 3: Rewrite guidance around stable decisions**

Keep the main Skill procedural and route details to one-level references. Replace the fixed worker instruction with:

```text
Start at most min(generation_queue length, currently available worker slots) image workers. Refill a free slot from the remaining queue; do not serialize runtime capacity into article data.
```

Document that a manual Save cancels only the pending autosave for the current edit cycle and that a later edit starts a new three-second timer.

- [ ] **Step 4: Run documentation and skill validation**

Run:

```bash
python3 -m unittest tests.test_skill_p0_contract tests.test_skill_p1_contract -v
python3 /Users/john/.codex/skills/.system/skill-creator/scripts/quick_validate.py wechat-article-pipeline
```

Expected: tests pass and validator exits zero.

- [ ] **Step 5: Commit Task 5**

```bash
git add wechat-article-pipeline/SKILL.md wechat-article-pipeline/references/image-production.md wechat-article-pipeline/references/image-rules.json wechat-article-pipeline/references/job-schema.md wechat-article-pipeline/references/publishing.md wechat-article-pipeline/references/workflow.md tests/test_skill_p0_contract.py tests/test_skill_p1_contract.py
git commit -m "docs: align WeChat skill with reliability contracts"
```

---

### Task 6: Integration verification and installed-skill handoff

**Files:**

- Modify only if failures require a covered fix: files already listed in Tasks 1–5
- Verify: generated temporary article packages under the system temporary directory
- Later sync target after explicit filesystem approval: `/Users/john/.codex/skills/wechat-article-pipeline/`

**Interfaces:**

- A generated no-image package and a generated image-plan package both verify successfully.
- Workbench local HTTP mode saves a manual edit, reports the new revision, and leaves standalone localStorage code in the HTML.
- Repository and installed copy differ only by intentionally local files such as `.env` and caches after synchronization.

- [ ] **Step 1: Run the complete automated suite fresh**

```bash
python3 -m unittest discover -s tests -v
python3 -m unittest discover -s wechat-article-pipeline/tests -v
node --test tests/workbench_save_behavior.test.mjs tests/workbench_sync_behavior.test.mjs
```

Expected: zero failures and zero errors.

- [ ] **Step 2: Generate and verify representative temporary packages**

Use temporary markdown files and existing generated test PNG bytes; run `postprocess_wechat_article.py` once with `--no-images` and once with `--plan-only`. Then run `verify_wechat_article_package.py` on the no-image HTML and validate the plan-only `.image-jobs.json` with `image_jobs_contract.py`. No final asset is left outside the repository or the temporary directory.

- [ ] **Step 3: Run a loopback workbench smoke test**

Start the server on port zero in a subprocess, read `WORKBENCH_URL`, fetch status, then POST one valid manual save with matching Origin/token/baseRevision. Assert HTTP 200, revision increment, Markdown update, and no pending duplicate save. Shut the server down deterministically.

- [ ] **Step 4: Review the whole branch**

Generate a diff from base commit `1a870f0` to `HEAD`. Review for requirement coverage, security boundary mistakes, state-machine ambiguity, stale compatibility reads, secret leakage, and missing tests. Fix every Critical or Important finding with a new failing test before production changes.

- [ ] **Step 5: Re-run the complete suite after review fixes**

Run the same three commands from Step 1 plus the exact smoke commands from Steps 2–3. Expected: zero failures, no live network access, and clean shutdown.

- [ ] **Step 6: Commit final integration fixes**

```bash
git add wechat-article-pipeline tests docs/superpowers
git commit -m "test: verify WeChat pipeline reliability refactor"
```

Skip this commit only when `git status --short` is empty after review.

- [ ] **Step 7: Synchronize the verified skill only after approval**

Copy the verified repository skill contents to `/Users/john/.codex/skills/wechat-article-pipeline/` without replacing the installed `.env`. Re-run `quick_validate.py` and representative tests against the installed path, then compare file hashes for tracked skill files.
