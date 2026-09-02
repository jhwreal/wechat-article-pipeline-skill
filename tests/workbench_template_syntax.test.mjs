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


test('blockquote preview renders Markdown line breaks instead of escaped br text', () => {
  const helpersStart = template.indexOf('    function escapeHtml');
  const helpersEnd = template.indexOf('    function getMarkdownBlocks');
  const quoteStart = template.indexOf('    function blockquoteToHtml');
  const quoteEnd = template.indexOf('    function markdownToHtml');
  assert.ok(helpersStart >= 0 && helpersEnd > helpersStart);
  assert.ok(quoteStart >= 0 && quoteEnd > quoteStart);

  const renderQuote = new Function(
    `${template.slice(helpersStart, helpersEnd)}\n${template.slice(quoteStart, quoteEnd)}; return blockquoteToHtml;`,
  )();
  const rendered = renderQuote('> 作者：[法]安德烈·焦尔当\n>\n> 整理说明：仅摘录原文。', 'data-test="quote"');

  assert.match(rendered, /作者：\[法\]安德烈·焦尔当<br><br>整理说明：仅摘录原文。/);
  assert.doesNotMatch(rendered, /&lt;br&gt;/);
});


test('WeChat rich copy preserves semantic tables', () => {
  assert.doesNotMatch(
    template,
    /root\.querySelectorAll\('table'\)\.forEach\(table => \{[\s\S]*?table\.replaceWith\(p\)/,
  );
  assert.match(template, /setStyle\('table', 'width:100%; border-collapse:collapse;/);
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


test('the first Markdown H1 is the only editable article title', () => {
  assert.match(template, /id="articleWorkbenchTitle"/);
  assert.match(template, /function syncArticleTitle\(\)/);
  assert.match(template, /document\.title = displayTitle/);
  assert.match(template, /articleWorkbenchTitle\.textContent = `\$\{displayTitle\}工作台`/);
  assert.match(template, /Markdown 缺少一级标题/);
  assert.doesNotMatch(template, /document\.title\.replace\(\/工作台\$\//);
});
