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

test('line start offsets keep preview-driven scrolling and textarea focus aligned', () => {
  const source = [
    extractFunction('getLineStartOffset'),
    'return getLineStartOffset;'
  ].join('\n');
  const getLineStartOffset = new Function(source)();
  const markdown = '第一行\n第二行很长\n第三行';

  assert.equal(getLineStartOffset(markdown, 1), 0);
  assert.equal(getLineStartOffset(markdown, 2), 4);
  assert.equal(getLineStartOffset(markdown, 3), 10);
  assert.equal(getLineStartOffset(markdown, 99), markdown.length);
});

test('caret events and viewport scrolling use different sync anchors', () => {
  assert.match(template, /schedulePreviewUpdate\('editor',\s*'caret'\)/);
  assert.match(template, /addEventListener\('click',\s*scheduleEditorCaretSync\)/);
  assert.match(template, /addEventListener\('keyup',\s*scheduleEditorCaretSync\)/);
  assert.match(template, /addEventListener\('select',\s*handleEditorSelectionSync\)/);
  assert.match(template, /const scheduleEditorCaretSync = \(\) => \{[\s\S]*?scheduleCaretSync\(\)/);
  assert.match(template, /syncPreviewToEditor\('viewport'\)/);
});

test('clicking the preview maps the pointer position back to a markdown line', () => {
  const source = [
    'const clamp = (value, min, max) => Math.min(Math.max(value, min), max);',
    extractFunction('getPreviewLineAtPoint'),
    'return getPreviewLineAtPoint;'
  ].join('\n');
  const getPreviewLineAtPoint = new Function(source)();
  const block = {
    dataset: { sourceLine: '10', sourceEndLine: '14' },
    getBoundingClientRect: () => ({ top: 100, height: 200 })
  };

  assert.equal(getPreviewLineAtPoint(block, 100), 10);
  assert.equal(getPreviewLineAtPoint(block, 200), 12);
  assert.equal(getPreviewLineAtPoint(block, 300), 14);
  assert.match(template, /preview\.addEventListener\('click',\s*syncEditorToPreviewPoint\)/);
});

test('preview-driven selection marks the matching wrapped markdown line', () => {
  const source = [
    extractFunction('findEditorLineForScrollTop'),
    'return findEditorLineForScrollTop;'
  ].join('\n');
  const findEditorLineForScrollTop = new Function(source)();

  assert.equal(findEditorLineForScrollTop(0, [0, 26, 78, 104]), 1);
  assert.equal(findEditorLineForScrollTop(50, [0, 26, 78, 104]), 2);
  assert.equal(findEditorLineForScrollTop(80, [0, 26, 78, 104]), 3);
  assert.match(template, /id="editorSyncMarker"[^>]*>▶<\/span>/);
  assert.match(template, /scrollEditorToLine\(lineNo, true\)/);
  assert.match(template, /setEditorSelectionToLine\(lineIndex \+ 1\)/);
  assert.match(template, /editorSyncMarker\.title = `右侧对应 Markdown 第 \$\{editorSyncMarkerLine\} 行`/);
});

test('delayed programmatic scroll events cannot pull focus back to the other pane', () => {
  const source = [
    extractFunction('classifyScrollEvent'),
    'return classifyScrollEvent;'
  ].join('\n');
  const classifyScrollEvent = new Function(source)();

  assert.equal(classifyScrollEvent(500, 500, null, 'editor'), 'programmatic');
  assert.equal(classifyScrollEvent(520, 500, 'editor', 'editor'), 'user');
  assert.equal(classifyScrollEvent(500, null, 'editor', 'editor'), 'locked');
  assert.equal(classifyScrollEvent(500, null, null, 'editor'), 'user');
  assert.match(template, /pendingPreviewScrollTop = next;\s*previewShell\.scrollTop = next/);
  assert.match(template, /pendingEditorScrollTop = next;\s*editor\.scrollTop = next/);
});

test('leaving the preview for the editor keeps the markdown caret authoritative', () => {
  assert.match(
    template,
    /preview\.addEventListener\('focusout',[\s\S]*?document\.activeElement === editor[\s\S]*?updatePreview\('editor', 'caret'\)/
  );
});

test('preview scroll drives the editor only after real preview interaction', () => {
  const source = [
    extractFunction('shouldPreviewScrollDriveEditor'),
    'return shouldPreviewScrollDriveEditor;'
  ].join('\n');
  const shouldPreviewScrollDriveEditor = new Function(source)();

  assert.equal(shouldPreviewScrollDriveEditor('programmatic', true), false);
  assert.equal(shouldPreviewScrollDriveEditor('user', false), false);
  assert.equal(shouldPreviewScrollDriveEditor('user', true), true);
  assert.match(template, /editor\.addEventListener\('pointerdown',[\s\S]*?clearPreviewScrollIntent\(\)/);
  assert.match(template, /previewShell\.addEventListener\('wheel',\s*notePreviewScrollIntent/);
});

test('preview synchronization adds no artificial bottom space', () => {
  assert.doesNotMatch(template, /preview-scroll-spacer|caret-scroll-spacer|sync-bottom-padding/);
});

test('markdown blocks expose stable source offsets for preview edits', () => {
  const source = [
    extractFunction('getMarkdownBlocks'),
    'return getMarkdownBlocks;'
  ].join('\n');
  const getMarkdownBlocks = new Function(source)();
  const markdown = '# 标题\n\n第一行\n第二行\n\n结尾';
  const result = getMarkdownBlocks(markdown);

  assert.deepEqual(
    result.blocks.map(block => ({
      text: block.text,
      startLine: block.startLine,
      endLine: block.endLine,
      startOffset: block.startOffset,
      endOffset: block.endOffset
    })),
    [
      { text: '# 标题', startLine: 1, endLine: 1, startOffset: 0, endOffset: 4 },
      { text: '第一行\n第二行', startLine: 3, endLine: 4, startOffset: 6, endOffset: 13 },
      { text: '结尾', startLine: 6, endLine: 6, startOffset: 15, endOffset: 17 }
    ]
  );
});
