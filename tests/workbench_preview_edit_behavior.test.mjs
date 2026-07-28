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

globalThis.Node = { TEXT_NODE: 3, ELEMENT_NODE: 1 };

function text(value) {
  return { nodeType: Node.TEXT_NODE, nodeValue: value };
}

function element(tagName, childNodes = [], options = {}) {
  const classes = new Set(options.classes || []);
  const attrs = options.attrs || {};
  return {
    nodeType: Node.ELEMENT_NODE,
    tagName,
    childNodes,
    children: childNodes.filter(node => node.nodeType === Node.ELEMENT_NODE),
    dataset: options.dataset || {},
    classList: { contains: value => classes.has(value) },
    getAttribute: name => attrs[name] || ''
  };
}

const serializers = new Function([
  extractFunction('serializePreviewInline'),
  extractFunction('normalizePreviewMarkdown'),
  extractFunction('serializePreviewBlock'),
  'return { serializePreviewBlock };'
].join('\n'))();

test('right-side text edits preserve heading and inline markdown wrappers', () => {
  const block = element('H2', [
    text('新的'),
    element('STRONG', [text('标题')]),
    text('与'),
    element('SPAN', [text('重点')], {
      classes: ['inline-accent'],
      dataset: { mdAccent: 'mark' }
    })
  ]);

  assert.equal(
    serializers.serializePreviewBlock(block, '## 旧的**标题**与==重点=='),
    '## 新的**标题**与==重点=='
  );
});

test('quoted accents and links keep their original markdown meaning', () => {
  const block = element('P', [
    text('修改'),
    element('SPAN', [text("'这个词'")], {
      classes: ['inline-accent'],
      dataset: { mdAccent: 'quote' }
    }),
    text('，参见'),
    element('A', [text('文档')], { attrs: { href: 'https://example.com/path' } })
  ]);

  assert.equal(
    serializers.serializePreviewBlock(block, "原文'这个词'，参见[文档](https://example.com/path)"),
    "修改'这个词'，参见[文档](https://example.com/path)"
  );
});

test('added and removed lines keep quote and list structure', () => {
  const quote = element('BLOCKQUOTE', [
    element('P', [text('第一行'), element('BR'), text('新增行')])
  ]);
  const list = element('UL', [
    element('LI', [text('甲')]),
    element('LI', [text('乙改')]),
    element('LI', [text('新增')])
  ]);

  assert.equal(
    serializers.serializePreviewBlock(quote, '> 第一行'),
    '> 第一行\n> 新增行'
  );
  assert.equal(
    serializers.serializePreviewBlock(list, '- 甲\n+ 乙'),
    '- 甲\n+ 乙改\n- 新增'
  );
});

test('browser div line wrappers become markdown line breaks', () => {
  const paragraph = element('P', [
    text('第一行'),
    element('DIV', [text('第二行')])
  ]);

  assert.equal(
    serializers.serializePreviewBlock(paragraph, '旧第一行\n旧第二行'),
    '第一行\n第二行'
  );
});

test('preview editing is enabled without a toolbar and excludes fragile blocks', () => {
  assert.match(template, /data-preview-editable="true"/);
  assert.match(template, /block\.querySelector\('img'\)/);
  assert.match(template, /preview\.addEventListener\('input'/);
  assert.match(template, /syncPreviewBlockToMarkdown/);
  assert.match(template, /new MutationObserver/);
  assert.doesNotMatch(template, /id="previewEditToggle"|id="previewToolbar"/);
});
