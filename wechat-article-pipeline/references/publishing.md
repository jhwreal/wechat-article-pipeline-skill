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
- Original declaration, reward account, and collection selection are not available in the public draft API fields used here. Do not put them in the API manifest and do not claim they were set. The user handles those manually in the WeChat UI if needed.
- Final publishing is not part of the default flow.

## Local config

Publisher defaults and Official API credentials live in a local `.env` copied from `.env.example`. The GitHub package includes `.env.example`, but `.env` is ignored by Git and must never be committed.

```text
.env
```

Shape:

```dotenv
WECHAT_APPID=
WECHAT_APPSECRET=
WECHAT_AUTHOR=
WECHAT_PREVIEW_ACCOUNT=
```

If `.env` is missing or lacks `WECHAT_APPID` / `WECHAT_APPSECRET`, ask the user for AppID/AppSecret and generate the file locally with restrictive permissions. Do not echo AppSecret in final answers or logs.

Access token cache is local-only and outside the repo:

```text
~/.codex/wechat-article-pipeline/wechat-token-cache.json
```

Never commit `.env` or token cache files.

## Manifest

`package_wechat_article_bundle.py` writes `<html-stem>.publish-manifest.json` by default, so each HTML output gets its own manifest instead of reusing a fixed filename. It contains title, author, digest, rendered HTML, text, cover image, image candidates, optional preview account, and safety flags. It must not contain original declaration, reward account, or collection fields.

If needed, regenerate it directly:

```bash
python3 scripts/make_wechat_publish_manifest.py output.job.json output.publish-manifest.json \
  --workbench-html output.html
```

## API flow

Dry-run first:

```bash
python3 scripts/publish_wechat_api.py output.publish-manifest.json --dry-run
```

Create a draft:

```bash
python3 scripts/publish_wechat_api.py output.publish-manifest.json \
  --env-file /path/to/.env \
  --remember \
  --check-draft-switch \
  --verify-draft
```

Send a preview only when explicitly requested:

```bash
python3 scripts/publish_wechat_api.py output.publish-manifest.json \
  --env-file /path/to/.env \
  --remember \
  --check-draft-switch \
  --verify-draft \
  --send-preview
```

If `manifest.preview.account` is empty, pass `--preview-account WECHAT_ID`. If an OpenID is available, pass `--preview-openid OPENID`.

The script performs:

1. Read `WECHAT_APPID` / `WECHAT_APPSECRET` from `.env`, then obtain `access_token` from `cgi-bin/stable_token`, reusing a valid local cache when possible.
2. Optionally check the draft switch through `cgi-bin/draft/switch?checkonly=1`.
3. Upload every `data:image` in `content_html` through `cgi-bin/media/uploadimg`.
4. Replace article image `src` values with WeChat image URLs.
5. Upload the cover through `cgi-bin/material/add_material?type=image`.
6. Build the `articles[0]` payload and call `cgi-bin/draft/add`.
7. Optionally call `cgi-bin/draft/get` to verify the created draft title.
8. If and only if preview was explicitly requested, call `cgi-bin/message/mass/preview` with the created `media_id`.
9. Stop. Do not publish.

## Operational notes

- `stable_token` can return `40164` when the current IP is not in the official account IP whitelist. Ask the user to add the machine's outbound IP in WeChat public platform developer settings, then retry.
- `stable_token` can return `89503` when administrator confirmation is required. Stop and ask the user to confirm in WeChat.
- Preview is available only for certified accounts according to the official doc.
- `media/uploadimg` body images must be JPG or PNG and under 1 MB. The script attempts to compress with Pillow when available; otherwise it stops with a clear message.
- Cover permanent material supports larger image files, but it counts toward the official account material quota.
- Do not log AppSecret or access tokens in final answers.

## Safety

- Uploading generated images, creating a draft, and sending preview are allowed when the user requested this workflow and provided credentials.
- QR login and browser security prompts are not part of the API flow.
- Admin confirmation, IP whitelist, permission, and risk-control errors are user-handled.
- Final publish/group-send APIs are out of scope by default.
