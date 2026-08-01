# 三平台草稿同步与恢复

仅在用户明确要求同步三个平台时使用。三平台同步默认只创建或保存草稿，不等于公开发布。

## 单一内容源

- 最终 Markdown 是唯一正文源；微信、头条和小红书只是平台适配视图。
- 复制前在工作台下拉框选择目标格式，再点击唯一的“复制为当前平台格式”按钮。
- 微信使用官方 API；头条和小红书使用已登录 Chrome 与 macOS 系统剪贴板。
- 带图头条依赖微信正文图片上传回执，因此正常顺序是微信 → 头条 → 小红书。小红书不依赖微信托管图，但仍排在最后以便统一核验。

## 可恢复状态

开始写入任何平台前创建状态文件：

```bash
python3 <skill>/scripts/platform_delivery_state.py init \
  <workspace>/files/<slug>.three-platform-result.json \
  --slug <slug> \
  --title "<最终标题>" \
  --markdown <workspace>/files/<slug>.md
```

每个平台完成、失败或结果未知后，先写它自己的结果文件，再合并到总状态：

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
3. 工作台选择头条格式。复制前检查必须显示可复制；带图文章如果托管图片数量不等会被工作台阻断。系统剪贴板一次复制、头条正文区一次粘贴，然后按 `publishing-toutiao.md` 只读核验并保存草稿。
4. 工作台选择小红书格式。系统剪贴板一次复制、小红书正文区一次粘贴，然后按 `publishing-xiaohongshu.md` 核验 H1/H2 和平台图片托管并保存草稿。
5. 三个结果都为 `verified` 后，总状态才是 `verified`。任何 `failed` 形成 `partial_failure`；任何可能已经提交但无法确认的结果形成 `unknown`，此时冻结写操作。

## 统一结果字段

总状态记录每个平台的：`status`、`mode`、`result_file`、预期/实测图片数、H1/H2 数、`clipboard_strategy`、`draft_verified`、`submission_maybe_sent`、`public_url`、错误信息和更新时间。平台专属字段继续保留在各自结果文件中。
