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
