import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';


const template = fs.readFileSync(
  new URL('../wechat-article-pipeline/assets/templates/wechat-md-workbench.template.v3.html', import.meta.url),
  'utf8',
);


test('all executable inline template scripts are valid JavaScript', () => {
  const scripts = [...template.matchAll(/<script(?<attrs>[^>]*)>(?<source>[\s\S]*?)<\/script>/gi)];
  assert.ok(scripts.length >= 3);

  for (const match of scripts) {
    if (/type=["']application\/json["']/i.test(match.groups.attrs)) continue;
    const source = match.groups.source.replace('{{SAVE_CONTROLLER_JS}}', '');
    assert.doesNotThrow(() => new Function(source));
  }
});


test('markdown preview blocks executable URL schemes', () => {
  const start = template.indexOf('    function escapeHtml');
  const end = template.indexOf('    function getMarkdownBlocks');
  assert.ok(start >= 0 && end > start);
  const helpers = new Function(
    `${template.slice(start, end)}; return { escapeHtml, inlineFormat };`,
  )();

  const unsafeLink = helpers.inlineFormat(helpers.escapeHtml('[点击](java\tscript:evil)'));
  const unsafeImage = helpers.inlineFormat(helpers.escapeHtml('![图](javascript:evil)'));
  const safeLink = helpers.inlineFormat(helpers.escapeHtml('[官网](https://example.com)'));
  const safeImage = helpers.inlineFormat(
    helpers.escapeHtml('![图](data:image/png;base64,cG5n)'),
  );

  assert.equal(unsafeLink, '点击');
  assert.equal(unsafeImage, '图');
  assert.match(safeLink, /href="https:\/\/example\.com"/);
  assert.match(safeImage, /src="data:image\/png;base64,cG5n"/);
});


test('save button keeps mouse feedback until pointer exit and clears other inputs', () => {
  assert.match(
    template,
    /#saveArticle\.save-click-feedback:not\(:disabled\)/,
  );
  assert.match(
    template,
    /addEventListener\('pointerdown',[\s\S]*?showSaveButtonFeedback\(\)/,
  );
  assert.match(
    template,
    /addEventListener\('pointerleave', clearSaveButtonFeedback\)/,
  );
  assert.match(
    template,
    /addEventListener\('pointercancel', clearSaveButtonFeedback\)/,
  );
  assert.match(template, /setTimeout\(clearSaveButtonFeedback, 260\)/);
  assert.match(template, /id="saveStatus" role="status" aria-live="polite"/);
});
