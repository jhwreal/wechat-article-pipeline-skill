# 三平台草稿同步与恢复

发布前先执行 [隐藏检查记录](pre-publish-check.md)，在任何平台写入前检查当前稿件计数。未经检查时的选择提示适用于本流程，包括草稿、定时发布和已明确授权发布；同一版同一次流程不重复询问。

仅在用户明确要求同步三个平台时使用。三平台同步默认只创建或保存草稿，不等于公开发布。

## 单一内容源

- 最终 Markdown 是唯一正文源；微信、头条和小红书只是平台适配视图。
- 复制前在工作台下拉框选择目标格式，再点击唯一的“复制为当前平台格式”按钮。
- 微信使用官方 API；头条和小红书使用已登录 Chrome 与 macOS 系统剪贴板。
- 正常顺序是微信 → 头条 → 小红书。头条可以复用与当前文章、图片版本一致的微信上传回执；没有有效回执时复制原图内嵌内容，不要求先创建微信草稿。

## 可恢复状态

开始写入任何平台前创建状态文件：

```bash
python3 <skill>/scripts/platform_delivery_state.py init \
  <workspace>/files/<slug>.three-platform-result.json \
  --slug <slug> \
  --markdown <workspace>/files/<slug>.md
```

状态文件的文章标题由 `--markdown` 中的第一个 H1 自动读取，不接受另一份独立标题。

初始化会计算正文及本地图片的版本指纹。正文、图片或标题变化后再次运行 `init`，会把上一轮完整记录保存在 `history`，再建立新的待同步状态；存在未确认的提交时会停止，先核实原提交结果。`summary` 返回 `stale` 时必须重新初始化，不能沿用旧的 `verified`。

每个平台完成、失败或结果未知后，先写它自己的结果文件，再合并到总状态：

平台结果必须带上本轮总状态 `article.source_fingerprint`，字段名为 `delivery_source_fingerprint`（也兼容 `source_fingerprint`）。在开始平台操作前固定此值，不能在操作后补上另一个版本的指纹。微信 API 回执在有关联 Markdown 时自动记录该字段；头条和小红书由本轮执行者连同核验结果记录。

```bash
python3 <skill>/scripts/platform_delivery_state.py record \
  <workspace>/files/<slug>.three-platform-result.json \
  wechat|toutiao|xiaohongshu \
  <workspace>/files/<slug>.<platform>-result.json
```

需要恢复时先运行 `summary`，只继续 `pending`、`ready` 或已经明确失败且允许重试的平台。`verified` 平台不得重复创建草稿；`submission_maybe_sent=true` 是单向锁，不能通过重启任务或重写结果文件恢复为 `false`。

## 顺序与门槛

1. 本地包验证通过，保存最终 Markdown 指纹。
2. 微信 API dry-run 通过后创建并验证草稿；成功回执自动把正文 HTTPS 图片地址写回工作台。
3. 工作台选择头条格式。复制前检查必须显示可复制；缺少匹配当前正文和图片的完整托管回执时，工作台回退到原图内嵌复制。系统剪贴板一次复制、头条正文区一次粘贴，然后按 `publishing-toutiao.md` 只读核验并保存草稿。
4. 工作台选择小红书格式。系统剪贴板一次复制、小红书正文区一次粘贴，然后按 `publishing-xiaohongshu.md` 核验 H1/H2 和平台图片托管并保存草稿。
5. 三个结果都为 `verified` 后，总状态才是 `verified`。任何 `failed` 形成 `partial_failure`；任何可能已经提交但无法确认的结果形成 `unknown`，此时冻结写操作。

## 统一结果字段

总状态记录每个平台的：`status`、`mode`、`result_file`、预期/实测图片数、H1/H2 数、`clipboard_strategy`、`draft_verified`、`submission_maybe_sent`、`public_url`、错误信息和更新时间。平台专属字段继续保留在各自结果文件中。

微信创建成功不等于验证成功，合并为 `verified` 需要草稿 ID 和成功的 `draft_verification`。头条需要图片、H1 的预期与实测计数，小红书还需要 H2；这些字段应是非负整数，没有图片或对应标题时填 0。缺失或不一致不能通过验证。历史 `submission_maybe_sent` 标记会保留；只有实际完成的回读核验才能把状态从未知变为已验证。
