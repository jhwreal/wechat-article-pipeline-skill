# Workbench Save Button Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align the Save button with the Markdown editor column, give it the same primary visual treatment as Copy Rich Text, document the recently added user-facing capabilities, synchronize the installed Codex skill, and publish the verified repository state.

**Architecture:** The canonical project template will split its sticky top bar into two grid-aligned groups that reuse the main workbench column ratio. A focused source-contract test will lock down group ownership and button styling before the HTML/CSS change. The project skill remains authoritative; after verification its complete contents are copied to the installed Codex skill.

**Tech Stack:** Standalone HTML/CSS/JavaScript template, Python `unittest`, Git, filesystem synchronization.

## Global Constraints

- Keep the existing `saveArticle` id and click handler unchanged.
- Save belongs to the left top-bar group and uses `class="btn primary"`.
- Font family, font size, theme color, and Copy Rich Text remain in the right top-bar group.
- Reuse `grid-template-columns: 1.05fr .95fr` and avoid absolute positioning.
- Preserve direct-file `localStorage`, local-server saving, copy behavior, and responsive wrapping.
- Treat `wechat-article-pipeline/` as canonical and synchronize it to `/Users/john/.codex/skills/wechat-article-pipeline/` only after tests pass.

---

### Task 1: Lock Down And Implement The Top-Bar Layout

**Files:**
- Modify: `wechat-article-pipeline/tests/test_serve_wechat_workbench.py`
- Modify: `wechat-article-pipeline/assets/templates/wechat-md-workbench.template.v3.html`

**Interfaces:**
- Consumes: static template source at `TEMPLATE`.
- Produces: `.topbar-primary` containing brand and Save; `.toolbar` containing preview controls and Copy Rich Text.

- [x] **Step 1: Write the failing test**

Add a test that extracts both top-bar groups and asserts exact ownership and styling:

```python
def test_save_button_belongs_to_markdown_topbar_group_and_matches_primary_action(self):
    source = TEMPLATE.read_text(encoding="utf-8")
    left = source.split('<div class="topbar-primary">', 1)[1].split('<div class="toolbar">', 1)[0]
    right = source.split('<div class="toolbar">', 1)[1].split('<div class="main">', 1)[0]
    self.assertIn('<button id="saveArticle" class="btn primary">保存</button>', left)
    self.assertNotIn('id="copyWechat"', left)
    self.assertIn('id="fontFamily"', right)
    self.assertIn('id="fontSize"', right)
    self.assertIn('id="themeColor"', right)
    self.assertIn('<button id="copyWechat" class="btn primary">复制富文本</button>', right)
    self.assertNotIn('id="saveArticle"', right)
    self.assertIn('grid-template-columns: 1.05fr .95fr', source)
```

- [x] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest wechat-article-pipeline/tests/test_serve_wechat_workbench.py -v`

Expected: FAIL because `.topbar-primary` does not exist and Save is still inside `.toolbar`.

- [x] **Step 3: Write minimal implementation**

Update the top-bar CSS to use the main column proportion and add a left group:

```css
.topbar {
  display: grid;
  grid-template-columns: 1.05fr .95fr;
}
.topbar-primary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  min-width: 0;
}
.topbar-primary .btn.primary { min-width: auto; }
```

Move Save beside the brand inside `.topbar-primary`, change it to `class="btn primary"`, and leave all preview controls inside `.toolbar`. Extend the existing `@media (max-width: 1080px)` rule so `.topbar` collapses to one column and both groups can wrap without overlap.

- [x] **Step 4: Run focused and full tests**

Run: `python3 -m unittest wechat-article-pipeline/tests/test_serve_wechat_workbench.py -v`

Expected: all focused tests PASS.

Run: `python3 -m unittest discover -s tests -p 'test_*.py'`

Expected: all project tests PASS.

Run: `node --test tests/*.test.mjs`

Expected: all Node workbench behavior tests PASS.

- [ ] **Step 5: Commit the feature and README**

```bash
git add README.md docs/superpowers/plans/2026-07-11-workbench-save-button-layout.md wechat-article-pipeline/tests/test_serve_wechat_workbench.py wechat-article-pipeline/assets/templates/wechat-md-workbench.template.v3.html
git commit -m "feat: align workbench save action with editor"
```

### Task 2: Synchronize Installed Skill And Publish

**Files:**
- Source: `wechat-article-pipeline/`
- Destination: `/Users/john/.codex/skills/wechat-article-pipeline/`

**Interfaces:**
- Consumes: verified canonical project skill.
- Produces: byte-identical installed skill files and an updated GitHub `main` branch.

- [ ] **Step 1: Synchronize the installed skill**

Run: `rsync -a --exclude '.env' wechat-article-pipeline/ /Users/john/.codex/skills/wechat-article-pipeline/`

Expected: the installed skill receives the verified repository contents while its local `.env` remains intact.

- [ ] **Step 2: Verify source and installed copies**

Run: `rsync -ani --exclude '.env' wechat-article-pipeline/ /Users/john/.codex/skills/wechat-article-pipeline/`

Expected: no output, proving every canonical project file is identical in the installed skill without deleting installation-only files.

Run: `python3 /Users/john/.codex/skills/wechat-article-pipeline/scripts/verify_wechat_article_package.py --help`

Expected: exit code 0 and command usage output.

- [ ] **Step 3: Push through the verified SSH remote**

Run: `git push git@github.com:jhwreal/wechat-article-pipeline-skill.git main`

Expected: GitHub accepts the new commits.

- [ ] **Step 4: Refresh and verify remote tracking state**

Run: `git fetch origin`

Run: `git status --short --branch`

Expected: `main...origin/main` with no ahead/behind marker and no working-tree changes.
