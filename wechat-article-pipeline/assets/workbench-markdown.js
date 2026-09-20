    function escapeHtml(str) {
      return str
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    }

    function isSafeMarkdownUrl(value, image) {
      const candidate = String(value || '').trim();
      const schemeProbe = candidate.replace(/[\u0000-\u0020\u007f]+/g, '').toLowerCase();
      const scheme = schemeProbe.match(/^([a-z][a-z0-9+.-]*):/);
      if (!scheme) return true;
      if (scheme[1] === 'http' || scheme[1] === 'https') return true;
      if (!image && scheme[1] === 'mailto') return true;
      return image && scheme[1] === 'data' && schemeProbe.startsWith('data:image' + '/');
    }

    function inlineFormat(text) {
      return text
        .replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (_match, alt, url) => (
          isSafeMarkdownUrl(url, true) ? `<img alt="${alt}" src="${url}" />` : alt
        ))
        .replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_match, label, url) => (
          isSafeMarkdownUrl(url, false)
            ? `<a href="${url}" target="_blank" rel="noopener noreferrer">${label}</a>`
            : label
        ))
        .replace(/`([^`]+)`/g, '<code>$1</code>')
        .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
        .replace(/==([^=\n]+)==/g, '<span class="inline-accent" data-md-accent="mark">$1</span>')
        .replace(/(^|[\s（(“‘])'([^'\n]{1,80})'(?![\w])/g, '$1<span class="inline-accent" data-md-accent="quote">&#39;$2&#39;</span>')
        .replace(/\*([^*]+)\*/g, '<em>$1</em>');
    }

    function getMarkdownBlocks(md) {
      const normalized = md.replace(/\r\n?/g, '\n');
      const lines = normalized.split('\n');
      const lineOffsets = [];
      const blocks = [];
      let current = [];
      let startLine = 1;
      let startOffset = 0;
      let inCodeFence = false;

      let offset = 0;
      lines.forEach((line, index) => {
        lineOffsets[index] = offset;
        offset += line.length + (index < lines.length - 1 ? 1 : 0);
      });

      const pushCurrent = () => {
        if (!current.length) return;
        const text = current.join('\n');
        blocks.push({
          text,
          startLine,
          endLine: startLine + current.length - 1,
          startOffset,
          endOffset: startOffset + text.length
        });
        current = [];
      };

      lines.forEach((line, index) => {
        const lineNo = index + 1;
        const trimmed = line.trim();

        if (!current.length) {
          startLine = lineNo;
          startOffset = lineOffsets[index];
        }

        if (inCodeFence) {
          current.push(line);
          if (/^```/.test(trimmed)) inCodeFence = false;
          return;
        }

        if (!trimmed) {
          pushCurrent();
          return;
        }

        current.push(line);
        if (/^```/.test(trimmed)) inCodeFence = true;
      });

      pushCurrent();
      return { blocks, lineCount: lines.length || 1 };
    }

    function previewBlockAttributes(source, blockIndex) {
      return `class="preview-block" data-source-line="${source.startLine}" data-source-end-line="${source.endLine}" data-source-start="${source.startOffset}" data-source-end="${source.endOffset}" data-source-block="${blockIndex}"`;
    }

    function parseTable(block, attributes) {
      const lines = block.trim().split('\n');
      if (lines.length < 2) return null;
      const rows = lines
        .map(line => line.trim())
        .filter(Boolean)
        .map(line => line.replace(/^\|/, '').replace(/\|$/, '').split('|').map(cell => inlineFormat(escapeHtml(cell.trim()))));
      if (!rows[1].every(cell => /^:?-{3,}:?$/.test(cell.replace(/<[^>]+>/g, '')))) return null;
      const header = rows[0];
      const body = rows.slice(2);
      return `<table ${attributes}><thead><tr>${header.map(c => `<th>${c}</th>`).join('')}</tr></thead><tbody>${body.map(r => `<tr>${r.map(c => `<td>${c}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
    }

    function blockquoteToHtml(block, attributes) {
      const lines = block.split('\n').map(line => line.replace(/^>\s?/, '').trim());
      const content = lines.map(line => inlineFormat(escapeHtml(line))).join('<br>');
      return `<blockquote ${attributes} data-preview-editable="true"><p>${content}</p></blockquote>`;
    }

    function markdownToHtml(md) {
      const { blocks } = getMarkdownBlocks(md);
      let html = '';

      for (const [blockIndex, source] of blocks.entries()) {
        const rawBlock = source.text;
        const block = rawBlock.trim();
        if (!block) continue;
        const attributes = previewBlockAttributes(source, blockIndex);

        const tableHtml = parseTable(block, attributes);
        if (tableHtml) {
          html += tableHtml;
          continue;
        }

        if (/^```/.test(block)) {
          const code = block.replace(/^```[a-zA-Z0-9_-]*\n?/, '').replace(/```$/, '');
          html += `<pre ${attributes}><code>${escapeHtml(code)}</code></pre>`;
          continue;
        }

        if (/^---+$/.test(block)) {
          html += `<hr ${attributes} />`;
          continue;
        }

        if (/^>/.test(block)) {
          html += blockquoteToHtml(block, attributes);
          continue;
        }

        if (/^#{1,6}\s/.test(block)) {
          const level = block.match(/^#+/)[0].length;
          const text = block.replace(/^#{1,6}\s+/, '');
          html += `<h${level} ${attributes} data-preview-editable="true">${inlineFormat(escapeHtml(text))}</h${level}>`;
          continue;
        }

        if (/^(-|\*|\+)\s+/m.test(block) && block.split('\n').every(line => /^(-|\*|\+)\s+/.test(line.trim()))) {
          const items = block.split('\n').map(line => line.replace(/^(-|\*|\+)\s+/, '').trim()).map(item => `<li>${inlineFormat(escapeHtml(item))}</li>`).join('');
          html += `<ul ${attributes} data-preview-editable="true">${items}</ul>`;
          continue;
        }

        if (/^\d+\.\s+/m.test(block) && block.split('\n').every(line => /^\d+\.\s+/.test(line.trim()))) {
          const items = block.split('\n').map(line => line.replace(/^\d+\.\s+/, '').trim()).map(item => `<li>${inlineFormat(escapeHtml(item))}</li>`).join('');
          html += `<ol ${attributes} data-preview-editable="true">${items}</ol>`;
          continue;
        }

        const paragraph = block.split('\n').map(line => inlineFormat(escapeHtml(line.trim()))).join('<br>');
        html += `<p ${attributes} data-preview-editable="true">${paragraph}</p>`;
      }

      return html;
    }

