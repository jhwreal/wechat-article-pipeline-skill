# WeChat Official API Publishing

Use this reference only when the user explicitly asks to push a generated article package to the WeChat Official Account draft box. Sending preview is separate and must also be explicitly requested.

## Official API scope

Use only official WeChat server APIs. Do not use private `mp.weixin.qq.com` backend endpoints and do not use Computer Use for the public account backend in this workflow.

Relevant official docs:

- Stable access token: <https://developers.weixin.qq.com/doc/subscription/api/base/api_getstableaccesstoken.html>
- Draft switch: <https://developers.weixin.qq.com/doc/subscription/api/draftbox/draftmanage/api_draft_switch.html>
- Add draft: <https://developers.weixin.qq.com/doc/subscription/api/draftbox/draftmanage/api_draft_add.html>
- Upload article body image: <https://developers.weixin.qq.com/doc/subscription/api/notify/message/api_uploadimage.html>
- Upload permanent material: <https://developers.weixin.qq.com/doc/subscription/api/material/permanent/api_addmaterial.html>
- Preview message: <https://developers.weixin.qq.com/doc/subscription/api/notify/message/api_preview.html>

Known coverage:

- The API can create a draft with title, author, digest, HTML content, cover `thumb_media_id`, comments, and crop strings.
- Body images must be uploaded through `cgi-bin/media/uploadimg`; WeChat filters external image links in article content.
- Cover images should be uploaded as permanent material through `cgi-bin/material/add_material?type=image`.
- Preview uses `cgi-bin/message/mass/preview` with `msgtype=mpnews` and the created draft `media_id`.
- Article author is account-scoped local config, not a hardcoded default. For the default account use `WECHAT_AUTHOR`; for named accounts use `WECHAT_ACCOUNT_<ALIAS>_AUTHOR`. If the selected account has no author configured, ask the user for it and store it in the corresponding `.env` field before creating a draft.
- Draft creation opens comments by default with `need_open_comment=1` and `only_fans_can_comment=0`, which means all readers can comment.
- Original declaration, reward/赞赏, automatic selected-comments, reward account, and collection selection are not available in the public draft API fields used here. Do not claim they were set. The user handles those manually in the WeChat UI if needed.
- The official selected-comment API is a later moderation action, not a draft setting: it requires a published `msg_data_id` and a concrete `user_comment_id`.
- Final publishing is not part of the default flow.

## Local config

Publisher defaults and Official API credentials live in a local `.env` copied from the skill-local `.env.example`. The installable skill includes that template; `.env` is ignored by Git and must never be committed.

```text
.env
```

Shape:

```dotenv
WECHAT_APPID=
WECHAT_APPSECRET=
WECHAT_ACCOUNT_NAME=
WECHAT_AUTHOR=
WECHAT_SIGNATURE_AUTHOR=
WECHAT_ORIGINAL_ISSUE=1
WECHAT_PREVIEW_ACCOUNT=
```

For multiple Official Accounts, keep the environment variable suffix as an ASCII alias and store the public account name in a separate `NAME` field. Match by that name when creating a draft:

```dotenv
WECHAT_ACCOUNT_JUZI_NAME=橘子
WECHAT_ACCOUNT_JUZI_APPID=
WECHAT_ACCOUNT_JUZI_APPSECRET=
WECHAT_ACCOUNT_JUZI_AUTHOR=
WECHAT_ACCOUNT_JUZI_SIGNATURE_AUTHOR=
WECHAT_ACCOUNT_JUZI_ORIGINAL_ISSUE=
WECHAT_ACCOUNT_JUZI_PREVIEW_ACCOUNT=
```

Keep `<ALIAS>` to uppercase ASCII letters, numbers, and underscores. Avoid aliases ending in `_SIGNATURE`, `_ORIGINAL`, or `_PREVIEW`, because those suffixes combine with reserved fields such as `AUTHOR`, `ISSUE`, and `ACCOUNT`.

`WECHAT_AUTHOR` and `WECHAT_ACCOUNT_<ALIAS>_AUTHOR` are only for the official draft API author field. The visible byline under the cover image is separate: use `WECHAT_SIGNATURE_AUTHOR` / `WECHAT_ORIGINAL_ISSUE` for the default account, or `WECHAT_ACCOUNT_<ALIAS>_SIGNATURE_AUTHOR` / `WECHAT_ACCOUNT_<ALIAS>_ORIGINAL_ISSUE` for named accounts. The workbench renders `<signature author>的第<issue>篇原创` as a centered theme-green label with 14px regular-weight white text below the cover image. If the issue is missing, packaging uses `1`; packaging does not advance `.env` by default.

For the first draft of an article in the current Codex conversation, package normally. Its signed manifest uses `counter_policy=consume_on_success`: before upload, the publisher requires the current `.env` counter to equal the manifest issue, then advances it exactly once after successful draft creation.

If that same conversation creates another draft for the same article slug, treat it as a revision and rebuild the package with `--same-session-revision`. Packaging uses the selected account's current counter minus one and writes `counter_policy=reuse_previous`. Before upload, the publisher requires the current counter to equal the reused issue plus one; after success it leaves `.env` unchanged. Use this flag only when both the current Codex conversation and article slug match a prior successful draft. Do not infer revision state merely from old receipt files in the workspace, and do not manually roll the counter backward for revisions.

`--increment-original-issue` remains accepted for compatibility but is unnecessary for a signed first-draft manifest and is rejected for a same-session revision manifest. Use the package script's explicit `--increment-original-issue` only in a workflow that will not subsequently create the draft from that same manifest.

`NAME` is the account selector. `AUTHOR` is only the official draft API author and must not be used to identify credentials or the visible article signature.

When no `--account` is provided, exactly one configured account (default or named) is selected automatically. If both the default account and any named account are configured, or multiple named accounts exist, ask which public account to use. Pass its name/alias with `--account`; use `--account default` to choose the unprefixed `WECHAT_*` fields explicitly.

If `.env` is missing or lacks credentials for the selected account, ask the user for the account name, AppID, and AppSecret, then generate the file locally with restrictive permissions. Do not echo AppSecret in final answers or logs.

Access token cache is local-only and outside the repo:

```text
~/.codex/wechat-article-pipeline/wechat-token-cache.json
```

Never commit `.env` or token cache files.

## Manifest

Local packaging skips the publish manifest by default. Pass `--publish-manifest` to write `<html-stem>.publish-manifest.json` for an explicitly requested API handoff. It contains title, author, digest, rendered HTML, text, embedded cover/body images, image candidates, a source fingerprint, optional preview account, and safety flags. Verification recomputes the fingerprint from the current job and image bytes so a leftover manifest cannot silently describe older content. External image URLs are rejected because WeChat filters them and the uploader only accepts embedded images. The manifest must not contain original declaration, reward account, or collection fields.

Do not publish external hyperlinks in WeChat article bodies. Source names may remain as plain text, but remove every external anchor from the final Markdown/workbench content before manifest creation. Before `draft/add`, verify that `content_html` contains no external `<a href>` values. This is separate from image handling: uploaded WeChat body-image URLs in `img src` are required and are not article hyperlinks.

`content_html` is generated as a draft-safe stream: ordinary blocks are paragraphs, while Markdown tables remain semantic `table` / `thead` / `tbody` / `tr` / `th` / `td` elements with inline styles. Do not wrap the article body in `section` / `div`, and do not use `blockquote`, `pre`, `ul`, or `ol` in the API manifest. The WeChat draft editor can normalize those tags into extra blank editable lines around badges and code blocks. Inline black code blocks keep their internal padding inside a styled `<p>`; fenced code blocks may contain blank lines, but the full fenced block must stay together before conversion so closing backticks never leak into draft-box body text.

The manifest separates the article hero image from WeChat platform cover crops:

- `cover.src` is the original article cover image and remains the image used in the body content.
- `wechat_cover.crop_values.pic_crop_235_1` and `wechat_cover.crop_values.pic_crop_1_1` are the crop coordinates sent to the draft API.
- `wechat_cover.crop_previews` points to generated preview assets such as `cover.wechat-235.png` and `cover.wechat-1x1.png`.

For no-body-image draft delivery, WeChat still requires a cover `thumb_media_id`. Use `postprocess_wechat_article.py --no-images --publish-manifest --cover-image <cover>` so the cover is uploaded for the draft payload but not inserted into `content_html`. In this mode `content_html` may contain zero body images; that is valid as long as `cover.src` is a data image.

If needed, regenerate it directly:

```bash
python3 scripts/make_wechat_publish_manifest.py output.job.json output.publish-manifest.json \
  --workbench-html output.html
```

For a same-session revision, rebuild through the main entry point so the visible signature and manifest policy stay aligned:

```bash
python3 scripts/postprocess_wechat_article.py article.md article.html \
  --workspace /path/to/workspace \
  --article-slug article-slug \
  --publish-manifest \
  --publisher-env-file /path/to/.env \
  --same-session-revision
```

## API flow

Local dry-run first; this is the default and makes no network calls:

```bash
python3 scripts/publish_wechat_api.py output.publish-manifest.json
```

Create a draft:

```bash
python3 scripts/publish_wechat_api.py output.publish-manifest.json \
  --create-draft \
  --env-file /path/to/.env \
  --account 橘子 \
  --remember \
  --check-draft-switch \
  --verify-draft
```

Omit `--account` only when `.env` contains exactly one configured credential profile in total. If default and named credentials coexist, select one explicitly; use `--account default` for the unprefixed pair.

Send a preview only when explicitly requested:

```bash
python3 scripts/publish_wechat_api.py output.publish-manifest.json \
  --create-draft \
  --env-file /path/to/.env \
  --remember \
  --check-draft-switch \
  --verify-draft \
  --send-preview
```

If `manifest.preview.account` is empty, pass `--preview-account WECHAT_ID`. If an OpenID is available, pass `--preview-openid OPENID`.

The script performs:

1. Read the selected account credentials from `.env`, then obtain `access_token` from `cgi-bin/stable_token`, reusing a valid account-specific local cache when possible.
2. Optionally check the draft switch through `cgi-bin/draft/switch?checkonly=1`.
3. Upload every `data:image` in `content_html` through `cgi-bin/media/uploadimg`.
4. Replace article image `src` values with WeChat image URLs.
5. Upload the cover through `cgi-bin/material/add_material?type=image`.
6. Build the `articles[0]` payload and call `cgi-bin/draft/add`.
7. Optionally call `cgi-bin/draft/get` to verify the created draft title.
8. When the manifest names an existing `workbench_html`, write the ordered uploaded body-image HTTPS URLs into that workbench's bootstrap data. The local Markdown and relative image paths stay unchanged; the open loopback workbench refreshes these URLs when Toutiao format is selected or copied, so no manual page reload is required. Xiaohongshu uses embedded image data already packaged in the workbench.
9. If and only if preview was explicitly requested, call `cgi-bin/message/mass/preview` with the created `media_id`.
10. Stop. Do not publish.

## Operational notes

- `stable_token` can return `40164` when the current IP is not in the official account IP whitelist. This is an immediate workflow-wide hard stop. As soon as the live command returns it, stop all remaining WeChat and cross-platform delivery work, do not retry, and immediately notify the user in the same turn. Quote the outbound IP parsed from `errmsg`, say clearly that no draft was created, and ask the user to add that IP in WeChat Official Account → Developer settings → IP whitelist. End the turn; retry only after the user explicitly confirms the whitelist was updated.
- `stable_token` can return `89503` when administrator confirmation is required. Stop and ask the user to confirm in WeChat.
- Preview is available only for certified accounts according to the official doc.
- `media/uploadimg` body images must be JPG or PNG and under 1 MB. The script targets 900 KiB when compression is needed, attempts to keep the best quality under that margin with Pillow when available, and otherwise stops with a clear message.
- Non-macOS image packaging and publishing workflows should have Pillow installed. macOS can use the system `sips` fallback for some cover-crop preview work, but Pillow is still recommended for pre-upload body-image compression.
- Cover permanent material supports larger image files, but it counts toward the official account material quota.
- Do not log AppSecret or access tokens in final answers.

## Safety

- Uploading generated images, creating a draft, and sending preview are allowed when the user requested this workflow and provided credentials.
- Reject draft submission when the rendered article body contains an external hyperlink. Remove the anchor while preserving its visible text, rebuild the manifest, and dry-run again.
- QR login and browser security prompts are not part of the API flow.
- Admin confirmation, IP whitelist, permission, and risk-control errors are user-handled.
- Final publish/group-send APIs are out of scope by default.
