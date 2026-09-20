import fs from 'node:fs';

// Match the production builder's in-place module expansion.
export function loadWorkbenchTemplate() {
  const template = fs.readFileSync(new URL('../wechat-article-pipeline/assets/templates/wechat-md-workbench.template.v3.html', import.meta.url), 'utf8');
  const renderer = fs.readFileSync(new URL('../wechat-article-pipeline/assets/workbench-markdown.js', import.meta.url), 'utf8');
  return template.replace('{{MARKDOWN_RENDERER_JS}}', renderer);
}
