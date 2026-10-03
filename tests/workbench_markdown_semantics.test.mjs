import { loadWorkbenchTemplate } from './workbench-template.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const template = loadWorkbenchTemplate();
function extract(name) {
  const start = template.search(new RegExp(`^    (?:async )?function ${name}\\(`, 'm'));
  assert.ok(start >= 0, name);
  const next = template.slice(start + 1).search(/^    (?:async )?function /m);
  return template.slice(start, start + 1 + next);
}
const helpers = ['escapeHtml', 'isSafeMarkdownUrl', 'inlineFormat', 'getMarkdownBlocks',
  'previewBlockAttributes', 'parseTable', 'blockquoteToHtml', 'markdownToHtml'];
const context = {};
vm.createContext(context);
vm.runInContext(helpers.map(extract).join('\n'), context);
const cases = JSON.parse(fs.readFileSync('tests/fixtures/markdown-semantics.json', 'utf8'));
for (const example of cases) {
  test(`shared Markdown semantics: ${example.name}`, () => {
    const rendered = context.markdownToHtml(example.markdown);
    const plain = rendered.replace(/<[^>]+>/g, '');
    let cursor = 0;
    for (const fragment of example.text) {
      const at = plain.indexOf(fragment, cursor);
      assert.ok(at >= 0, fragment);
      cursor = at + fragment.length;
    }
    const positions = (example.images || []).map(name => rendered.indexOf(name));
    assert.ok(positions.every(position => position >= 0));
    assert.deepEqual(positions, [...positions].sort((a, b) => a - b));
  });
}

test('escaped punctuation stays literal and inline code is not formatted', () => {
  assert.equal(context.inlineFormat(context.escapeHtml(String.raw`And f\*\*k Sam Altman.`)), 'And f&#42;&#42;k Sam Altman.');
  assert.equal(context.inlineFormat('And f**k Sam Altman.'), 'And f**k Sam Altman.');
  assert.equal(context.inlineFormat(context.escapeHtml(String.raw`\[plain\] \<tag\> C:\temp`)), '&#91;plain&#93; &lt;tag&gt; C:\\temp');
  assert.equal(context.inlineFormat(context.escapeHtml(String.raw`\`literal\``)), '&#96;literal&#96;');
  assert.equal(context.inlineFormat(context.escapeHtml(String.raw`\*literal\* **bold**`)), '&#42;literal&#42; <strong>bold</strong>');
  assert.equal(context.inlineFormat(context.escapeHtml('`f\\*\\*k **bold** [x](https://example.com)`')), '<code>f\\*\\*k **bold** [x](https://example.com)</code>');
});
