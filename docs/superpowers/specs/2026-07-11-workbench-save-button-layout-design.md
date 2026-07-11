# Workbench Save Button Layout Design

## Goal

Make the manual save action visually and logically belong to the Markdown editor while preserving the existing workbench behavior.

## Layout

- Split the sticky top bar into the same two-column proportion used by the main workbench: `1.05fr .95fr`.
- Keep the brand at the start of the left column and place the Save button at the end of that column, aligned above the Markdown editor.
- Keep font family, font size, theme color, and Copy Rich Text controls in the right column because they affect or act on the rendered preview.
- On narrow screens, collapse the top bar into a wrapping layout so controls remain usable without absolute positioning.

## Visual Treatment

- Give the Save button the same `btn primary` treatment as Copy Rich Text.
- Reuse the existing theme color, border, typography, hover behavior, and height rather than introducing a new button variant.
- Allow Save to remain content-width while Copy Rich Text retains its existing minimum width.

## Behavior and Compatibility

- Keep the existing `saveArticle` id and click handler unchanged.
- Do not change autosave, server persistence, localStorage fallback, copy behavior, or article rendering.
- Apply the canonical change to the project skill template, then synchronize the verified template to the installed Codex skill.

## Verification

- Add a template contract test that asserts the Save button is in the left top-bar group and uses the primary button class.
- Assert preview controls and Copy Rich Text remain in the right group.
- Run the focused template/server tests and the project test suite.
- Confirm both project and installed templates contain the same verified layout.
