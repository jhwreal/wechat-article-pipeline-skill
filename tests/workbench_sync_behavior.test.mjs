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
