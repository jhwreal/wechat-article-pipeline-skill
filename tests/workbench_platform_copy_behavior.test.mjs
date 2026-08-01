import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const template = fs.readFileSync(
  new URL('../wechat-article-pipeline/assets/templates/wechat-md-workbench.template.v3.html', import.meta.url),
  'utf8',
);
const adapterRegistry = JSON.parse(fs.readFileSync(
  new URL('../wechat-article-pipeline/references/platform-adapters.json', import.meta.url),
  'utf8',
));
delete adapterRegistry.schema_version;

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

const platformHelpers = new Function('PLATFORM_ADAPTERS', [
  extractFunction('platformAdapter'),
  extractFunction('platformHeadingTag'),
  extractFunction('platformClipboardImagePolicy'),
  extractFunction('platformUsesNativeSelection'),
  'return { platformHeadingTag, platformClipboardImagePolicy, platformUsesNativeSelection };',
].join('\n'))(adapterRegistry);

test('platform heading adapters preserve each editor schema', () => {
  assert.equal(platformHelpers.platformHeadingTag('wechat', 'H2'), 'H2');
  assert.equal(platformHelpers.platformHeadingTag('toutiao', 'H2'), 'H1');
  assert.equal(platformHelpers.platformHeadingTag('toutiao', 'H5'), 'H1');
  assert.equal(platformHelpers.platformHeadingTag('xiaohongshu', 'H2'), 'H1');
  assert.equal(platformHelpers.platformHeadingTag('xiaohongshu', 'H3'), 'H2');
  assert.equal(platformHelpers.platformHeadingTag('xiaohongshu', 'H6'), 'H2');
});

test('platform copy uses the image representation accepted by each editor', () => {
  assert.equal(platformHelpers.platformClipboardImagePolicy('wechat', 6, 6), 'embedded-data');
  assert.equal(platformHelpers.platformClipboardImagePolicy('toutiao', 6, 6), 'hosted-url');
  assert.equal(platformHelpers.platformClipboardImagePolicy('toutiao', 6, 5), 'unavailable');
  assert.equal(platformHelpers.platformClipboardImagePolicy('xiaohongshu', 6, 6), 'embedded-data');
  assert.equal(platformHelpers.platformClipboardImagePolicy('xiaohongshu', 6, 0), 'embedded-data');
  assert.equal(platformHelpers.platformUsesNativeSelection('wechat'), false);
  assert.equal(platformHelpers.platformUsesNativeSelection('toutiao'), true);
  assert.equal(platformHelpers.platformUsesNativeSelection('xiaohongshu'), true);
});

test('platform preview selector precedes typography and drives one semantic source', () => {
  assert.ok(template.indexOf('id="platformMode"') < template.indexOf('id="fontFamily"'));
  assert.match(template, /<option value="wechat" selected>微信格式<\/option>/);
  assert.match(template, /<option value="toutiao">头条格式<\/option>/);
  assert.match(template, /<option value="xiaohongshu">小红书格式<\/option>/);
  assert.equal((template.match(/id="copyCurrentPlatform"/g) || []).length, 1);
  assert.doesNotMatch(template, /id="copy(?:Wechat|Toutiao|Xiaohongshu)"/);
  assert.match(template, /preview\.innerHTML = buildPlatformPreviewHtml\(activePlatform\)/);
  assert.match(template, /activePlatform === 'wechat'/);
});

test('Toutiao and Xiaohongshu copy from semantic HTML instead of flattened WeChat HTML', () => {
  const createClipboardBox = extractFunction('createClipboardBox');
  assert.match(createClipboardBox, /target === 'wechat'/);
  assert.match(createClipboardBox, /buildInlineWechatHtml\(\)/);
  assert.match(createClipboardBox, /createSemanticArticleRoot\(target, \{ forClipboard: true \}\)/);
  assert.doesNotMatch(template, /data-xhs-image-marker|\[\[XHS_IMAGE_/);
  assert.match(template, /applyHostedImagesForClipboard/);
  assert.doesNotMatch(template, /wrapXiaohongshuImagesForClipboard/);
  assert.match(template, /platformAdapter\(target\)\.imagePolicy/);
  assert.match(template, /imagePolicy === 'unavailable'/);
  assert.match(template, /张图片未准备完成，已停止复制/);
  assert.match(template, /ensureClipboardAssetsLoaded/);
  assert.match(template, /releaseClipboardAssets/);
  assert.match(extractFunction('buildInlineWechatHtml'), /removePlatformExternalLinks\(root\)/);
});

test('Toutiao refreshes WeChat-hosted image receipts without a manual page reload', () => {
  const refresh = extractFunction('refreshPlatformImagesFromWorkbench');
  const copy = extractFunction('copyPlatformContent');
  assert.match(refresh, /fetch\(location\.pathname, \{ cache: 'no-store' \}\)/);
  assert.match(refresh, /latest\.platformImageUrls/);
  assert.match(refresh, /PLATFORM_IMAGE_URLS = urls/);
  assert.match(copy, /target === 'toutiao'[^;]*await refreshPlatformImagesFromWorkbench\(\)/);
});
