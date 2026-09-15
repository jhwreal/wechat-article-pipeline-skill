# Delivery Contract

Use this guide when handing off an article or workbench. Match the requested output; local delivery does not authorize external draft creation or publishing.

## Choose the output

- **Editable workbench (default for a complete article package):** verify the package, start the persistence server, and give its working URL first, followed by the absolute HTML file link. The URL supports saving edits back to project files; the HTML is the durable local artifact.
- **Static HTML, Markdown, or file-only request:** give the requested main file first. Do not start a server merely because an HTML file exists. Directly opened workbench HTML supports preview/copy only; state that limitation if editing matters.
- **Existing article edits:** update only the requested layer and preserve the slug, assets, and delivery mode. Reuse an existing server only after checking it serves the current article and current content.
- **External draft/publish request:** report the actual platform result, selected account, and receipt path. Include a public URL only if one was obtained. Do not label a local file, clipboard copy, or unsent draft as published.

## Editable workbench service

After `verify_wechat_article_package.py <html>` succeeds, run:

```bash
python3 <skill>/scripts/serve_wechat_workbench.py \
  <workspace>/files/<slug>.html \
  --workspace <workspace>
```

Read the emitted `WORKBENCH_URL` and `HTML_PATH`; do not invent a port or reuse an unverified old URL. Check that the URL responds with the expected article and keep the process running for handoff. This is a local loopback service, not public hosting.

Edits are cached immediately; automatic saving writes them after 3 idle seconds, and Save writes immediately. A directly opened HTML file locks editing. Preserve visible saving, saved, error, and recovery-required states.

If the service cannot run, deliver the verified files and explain that editable saving is unavailable. If the user requested editing, mark that part incomplete instead of presenting static HTML as a completed editable workbench.

## Final response

For an editable workbench, lead with the working URL and then the HTML file link. For static output, lead with the main file link. Add Markdown, images, job data, manifests, or API receipts only when useful for the task. State missing assets or unfinished steps plainly. Do not create a ZIP unless requested.
