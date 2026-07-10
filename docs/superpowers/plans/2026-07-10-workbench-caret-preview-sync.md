# Workbench Caret Preview Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the WeChat Markdown workbench preview follow the active editing line after typing or moving the caret while preserving natural scroll limits and existing bidirectional scrolling.

**Architecture:** Keep the existing `data-source-line` preview mapping and scroll lock. Add pure caret-offset/line helpers, distinguish caret-driven synchronization from viewport-driven synchronization, and coalesce caret movement events with `requestAnimationFrame`. Do not add bottom spacers or change copied article HTML.

**Tech Stack:** Single-file HTML template, browser DOM APIs, Node.js built-in test runner, Python `unittest`, existing WeChat packaging scripts.

## Global Constraints

- Input, click, and keyboard caret movement synchronize the preview to the active Markdown line.
- Left-editor scrolling continues to synchronize from the first visible line.
- Right-preview scrolling continues to synchronize back to the editor.
- Natural right-preview scroll limits apply; no artificial bottom spacer or padding is allowed.
- Markdown rendering, rich-text clipboard output, and existing article HTML files remain unchanged unless explicitly regenerated.

---

### Task 1: Add executable caret-line regression tests

**Files:**
- Create: `tests/workbench_sync_behavior.test.mjs`
- Test: `tests/workbench_sync_behavior.test.mjs`

**Interfaces:**
- Consumes: `wechat-article-pipeline/assets/templates/wechat-md-workbench.template.v3.html`
- Produces: executable contracts for `getActiveSelectionOffset(textarea)`, `getLineNumberAtOffset(text, offset)`, caret event wiring, and the absence of preview bottom spacers

- [ ] **Step 1: Write the failing test**

Create a Node built-in test that reads the real template, extracts named function declarations with a small brace-counting helper, and evaluates the two pure functions together:

```js
import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const template = fs.readFileSync(
  new URL('../wechat-article-pipeline/assets/templates/wechat-md-workbench.template.v3.html', import.meta.url),
  'utf8'
);

function extractFunction(name) {
  const marker = `function ${name}(`;
  const start = template.indexOf(marker);
  assert.notEqual(start, -1, `${name} must exist in the workbench template`);
  const bodyStart = template.indexOf('{', start);
  let depth = 0;
  for (let index = bodyStart; index < template.length; index += 1) {
    if (template[index] === '{') depth += 1;
    if (template[index] === '}') depth -= 1;
    if (depth === 0) return template.slice(start, index + 1);
  }
  throw new Error(`Could not extract ${name}`);
}

test('active selection endpoint respects selection direction', () => {
  const source = [
    extractFunction('getActiveSelectionOffset'),
    'return getActiveSelectionOffset;'
  ].join('\n');
  const getActiveSelectionOffset = new Function(source)();
  assert.equal(getActiveSelectionOffset({ selectionStart: 2, selectionEnd: 8, selectionDirection: 'backward' }), 2);
  assert.equal(getActiveSelectionOffset({ selectionStart: 2, selectionEnd: 8, selectionDirection: 'forward' }), 8);
  assert.equal(getActiveSelectionOffset({ selectionStart: 5, selectionEnd: 5, selectionDirection: 'none' }), 5);
});

test('line number is derived from the caret offset', () => {
  const source = [
    extractFunction('getLineNumberAtOffset'),
    'return getLineNumberAtOffset;'
  ].join('\n');
  const getLineNumberAtOffset = new Function(source)();
  assert.equal(getLineNumberAtOffset('第一行\n第二行\n第三行', 0), 1);
  assert.equal(getLineNumberAtOffset('第一行\n第二行\n第三行', 4), 2);
  assert.equal(getLineNumberAtOffset('第一行\n第二行\n第三行', 999), 3);
});

test('caret events and viewport scrolling use different sync anchors', () => {
  assert.match(template, /updatePreview\('editor',\s*'caret'\)/);
  assert.match(template, /addEventListener\('click',\s*scheduleCaretSync\)/);
  assert.match(template, /addEventListener\('keyup',\s*scheduleCaretSync\)/);
  assert.match(template, /addEventListener\('select',\s*scheduleCaretSync\)/);
  assert.match(template, /syncPreviewToEditor\('viewport'\)/);
});

test('preview synchronization adds no artificial bottom space', () => {
  assert.doesNotMatch(template, /preview-scroll-spacer|caret-scroll-spacer|sync-bottom-padding/);
});
```

- [ ] **Step 2: Run the test to verify RED**

Run: `node --test tests/workbench_sync_behavior.test.mjs`

Expected: FAIL because `getActiveSelectionOffset` does not yet exist.

- [ ] **Step 3: Commit the failing regression test**

```bash
git add tests/workbench_sync_behavior.test.mjs
git commit -m "test: cover caret-driven workbench sync"
```

### Task 2: Implement caret-driven preview synchronization

**Files:**
- Modify: `wechat-article-pipeline/assets/templates/wechat-md-workbench.template.v3.html:505-510`
- Modify: `wechat-article-pipeline/assets/templates/wechat-md-workbench.template.v3.html:794-915`
- Modify: `wechat-article-pipeline/assets/templates/wechat-md-workbench.template.v3.html:1156-1172`
- Test: `tests/workbench_sync_behavior.test.mjs`

**Interfaces:**
- Consumes: existing `findPreviewScrollForLine(lineNo)`, `syncEditorToPreview()`, and `holdScrollLock(source)`
- Produces: `getActiveSelectionOffset(textarea): number`, `getLineNumberAtOffset(text, offset): number`, `getCaretLine(): number`, `getFirstVisibleEditorLine(): number`, `syncPreviewToEditor(anchorMode): void`, and `scheduleCaretSync(): void`

- [ ] **Step 1: Add the minimal line-source helpers**

Add pure helpers and two editor-specific wrappers:

```js
function getActiveSelectionOffset(textarea) {
  return textarea.selectionDirection === 'backward'
    ? textarea.selectionStart
    : textarea.selectionEnd;
}

function getLineNumberAtOffset(text, offset) {
  const safeOffset = clamp(Number(offset) || 0, 0, text.length);
  return text.slice(0, safeOffset).split('\n').length;
}

function getCaretLine() {
  return getLineNumberAtOffset(editor.value, getActiveSelectionOffset(editor));
}

function getFirstVisibleEditorLine() {
  return Math.max(1, Math.floor(editor.scrollTop / getEditorLineHeight()) + 1);
}
```

- [ ] **Step 2: Give editor-to-preview sync an explicit anchor mode**

Change synchronization signatures so render-driven input can request the caret and scrolling can request the viewport:

```js
function syncPreviewToEditor(anchorMode = 'viewport') {
  const lineNo = anchorMode === 'caret' ? getCaretLine() : getFirstVisibleEditorLine();
  const target = findPreviewScrollForLine(lineNo);
  const maxScroll = Math.max(0, previewShell.scrollHeight - previewShell.clientHeight);
  previewShell.scrollTop = clamp(target, 0, maxScroll);
}

function syncAfterRender(preferredSource = 'editor', editorAnchor = 'viewport') {
  requestAnimationFrame(() => {
    holdScrollLock(preferredSource);
    if (preferredSource === 'preview') {
      syncEditorToPreview();
    } else {
      syncPreviewToEditor(editorAnchor);
    }
  });
}

function updatePreview(preferredSource = activeScrollSource || 'editor', editorAnchor = 'viewport') {
  preview.innerHTML = markdownToHtml(editor.value);
  injectSignature(preview);
  const text = editor.value.replace(/\s+/g, '');
  wordCount.textContent = `${text.length} 字`;
  lineCount.textContent = `${editor.value.split('\n').length} 行`;
  saveStatus.textContent = '编辑中…';
  syncAfterRender(preferredSource, editorAnchor);
}
```

- [ ] **Step 3: Wire input and caret movement without changing scroll behavior**

Add one animation-frame handle near the existing timers, then wire explicit events:

```js
let caretSyncFrame = null;

function scheduleCaretSync() {
  if (caretSyncFrame !== null) return;
  caretSyncFrame = requestAnimationFrame(() => {
    caretSyncFrame = null;
    holdScrollLock('editor');
    syncPreviewToEditor('caret');
  });
}

editor.addEventListener('input', () => {
  holdScrollLock('editor');
  updatePreview('editor', 'caret');
  scheduleSave();
});

editor.addEventListener('click', scheduleCaretSync);
editor.addEventListener('keyup', scheduleCaretSync);
editor.addEventListener('select', scheduleCaretSync);

editor.addEventListener('scroll', () => {
  if (activeScrollSource === 'preview') return;
  holdScrollLock('editor');
  syncPreviewToEditor('viewport');
});
```

- [ ] **Step 4: Run the focused test to verify GREEN**

Run: `node --test tests/workbench_sync_behavior.test.mjs`

Expected: 4 tests PASS.

- [ ] **Step 5: Run repository regression tests**

Run: `python3 -m unittest discover -s tests -v`

Expected: all existing Python tests PASS with no traceback.

- [ ] **Step 6: Commit the implementation**

```bash
git add wechat-article-pipeline/assets/templates/wechat-md-workbench.template.v3.html
git commit -m "fix: follow workbench caret in preview"
```

### Task 3: Package and browser-verify a real article workbench

**Files:**
- Read: `/Users/john/Documents/WeChatArticle/files/chatgpt-eats-codex-work-sites.job.json`
- Create temporarily: `/private/tmp/chatgpt-eats-codex-work-sites-caret-sync.html`
- Verify: `wechat-article-pipeline/assets/templates/wechat-md-workbench.template.v3.html`

**Interfaces:**
- Consumes: updated template and existing `build_wechat_article_workbench.py`
- Produces: evidence that caret/input/scroll interactions work in a real rendered workbench

- [ ] **Step 1: Build a temporary workbench from the screenshot article**

Run:

```bash
python3 wechat-article-pipeline/scripts/build_wechat_article_workbench.py \
  /Users/john/Documents/WeChatArticle/files/chatgpt-eats-codex-work-sites.job.json \
  /private/tmp/chatgpt-eats-codex-work-sites-caret-sync.html \
  --template wechat-article-pipeline/assets/templates/wechat-md-workbench.template.v3.html
```

Expected: the temporary HTML exists and contains the updated caret helpers.

- [ ] **Step 2: Run browser interaction checks**

Open the temporary workbench with the in-app browser and verify:

- clicking a paragraph near the bottom of the left viewport brings the matching preview block into view;
- typing in that paragraph keeps the same preview block visible and updates its rendered text;
- arrow-key movement across Markdown lines updates the preview anchor;
- left scrolling follows the first visible editor line rather than the off-screen caret;
- right scrolling still moves the editor and does not oscillate;
- the final paragraph stops at the natural right-side maximum scroll position without extra whitespace.

- [ ] **Step 3: Verify clipboard/export isolation**

In the page, call `window.__WECHAT_ARTICLE_EXPORT__()` and confirm `content_html` contains no `preview-scroll-spacer`, `caret-scroll-spacer`, or `sync-bottom-padding` marker.

### Task 4: Sync the verified template into the installed skill

**Files:**
- Read: `wechat-article-pipeline/assets/templates/wechat-md-workbench.template.v3.html`
- Modify: `/Users/john/.codex/skills/wechat-article-pipeline/assets/templates/wechat-md-workbench.template.v3.html`

**Interfaces:**
- Consumes: the repository template verified in Tasks 1–3
- Produces: identical installed and repository templates for future article packages

- [ ] **Step 1: Copy only the verified template**

Run with filesystem approval:

```bash
cp wechat-article-pipeline/assets/templates/wechat-md-workbench.template.v3.html \
  /Users/john/.codex/skills/wechat-article-pipeline/assets/templates/wechat-md-workbench.template.v3.html
```

Expected: command succeeds without modifying `.env` or any other installed-skill file.

- [ ] **Step 2: Verify byte identity**

Run:

```bash
shasum wechat-article-pipeline/assets/templates/wechat-md-workbench.template.v3.html \
  /Users/john/.codex/skills/wechat-article-pipeline/assets/templates/wechat-md-workbench.template.v3.html
```

Expected: both SHA-1 values are identical.

- [ ] **Step 3: Run final clean-tree and test checks**

Run: `git status --short --branch`

Expected: `main` is ahead only by the intentional design, plan, test, and implementation commits; no uncommitted files remain.

Run: `node --test tests/workbench_sync_behavior.test.mjs`

Expected: 4 tests PASS.

Run: `python3 -m unittest discover -s tests -v`

Expected: all tests PASS.
