import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const template = fs.readFileSync(
  new URL('../wechat-article-pipeline/assets/templates/wechat-md-workbench.template.v3.html', import.meta.url),
  'utf8',
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

test('workbench template stays within the single-file startup budget', () => {
  assert.ok(Buffer.byteLength(template, 'utf8') < 120_000);
  assert.equal((template.match(/id="preview"/g) || []).length, 1);
  assert.equal((template.match(/id="copyCurrentPlatform"/g) || []).length, 1);
});

test('only the active platform preview is mounted', () => {
  assert.equal((template.match(/id="preview"/g) || []).length, 1);
  assert.doesNotMatch(template, /id="(?:wechat|toutiao|xiaohongshu)Preview"/);
  assert.match(template, /preview\.innerHTML = buildPlatformPreviewHtml\(activePlatform\)/);
});

test('semantic markdown parsing is reused across preview, copy, and export', () => {
  const editor = { value: '# 第一版' };
  let calls = 0;
  const getSemanticMarkdownHtml = new Function(
    'editor',
    'markdownToHtml',
    `let semanticMarkdownCacheSource = null;
     let semanticMarkdownCacheHtml = '';
     ${extractFunction('getSemanticMarkdownHtml')}
     return getSemanticMarkdownHtml;`,
  )(editor, markdown => {
    calls += 1;
    return `<p>${markdown}</p>`;
  });

  assert.equal(getSemanticMarkdownHtml(), '<p># 第一版</p>');
  assert.equal(getSemanticMarkdownHtml(), '<p># 第一版</p>');
  assert.equal(calls, 1);
  editor.value = '# 第二版';
  assert.equal(getSemanticMarkdownHtml(), '<p># 第二版</p>');
  assert.equal(calls, 2);
});

test('typing coalesces preview renders and post-render scroll work', () => {
  assert.match(template, /function schedulePreviewUpdate[\s\S]*?requestAnimationFrame/);
  assert.match(template, /editor\.addEventListener\('input',[\s\S]*?schedulePreviewUpdate\('editor', 'caret'\)/);
  assert.match(template, /if \(postRenderSyncFrame !== null\) cancelAnimationFrame\(postRenderSyncFrame\)/);
});

test('scroll synchronization reuses measured preview layout', () => {
  assert.match(template, /if \(!previewLayoutDirty\) return previewLayoutCache/);
  assert.match(template, /previewLayoutCache = blocks\.map/);
  assert.match(template, /new ResizeObserver\(invalidatePreviewLayout\)/);
  assert.match(template, /preview\.addEventListener\('load', invalidatePreviewLayout, true\)/);
});

test('style changes avoid rebuilding article DOM', () => {
  const applySettings = extractFunction('applySettings');
  assert.match(applySettings, /--preview-font-size/);
  assert.doesNotMatch(applySettings, /updatePreview\(/);
});

test('clipboard image conversion is bounded and temporary', () => {
  assert.match(template, /const CLIPBOARD_IMAGE_CONCURRENCY = 3/);
  assert.match(extractFunction('inlineImagesForClipboard'), /Promise\.all/);
  assert.match(extractFunction('inlineImagesForClipboard'), /ensureClipboardAssetsLoaded/);
  assert.match(extractFunction('releaseClipboardAssets'), /WECHAT_CLIPBOARD_IMAGE_DATA = \{\}/);
  assert.doesNotMatch(template, /<script src="[^\"]*clipboard-assets\.js"/);
  assert.match(template, /document\.body\.removeChild\(box\)/);
});
