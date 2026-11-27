# Bot 资料库：聊天页「+」上传文件

日期：2026-11-20　状态：设计已通过，按此实现

## 目标

每个 Bot 的聊天输入框左侧有一个「+」。用户通过它给这个 Bot 上传文本类文件，文件保存在 Bot 名下，之后每次对话 Bot 都能参考。

## 已确认的决策

1. 文件保存在后端，属于某个 Bot（不是只附在单条消息里）。
2. 内容全文注入系统提示，不做切片与检索。
3. 总量上限跟着模型上下文窗口走，窗口越大上限越高。

## 上限

- Bot 的资料总量上限 `budget_chars = floor(context_window × 0.6 × 1.5)`，即窗口的 60% 给资料，1 token 按 1.5 字符保守估算。
- `context_window` 取自 Bot 所用槽位（`slots[bot.slot].context_window`）。槽位缺失时按 32768。
- 示例：32K → 29,491 字符；65K → 58,982；131K → 117,964。
- 单个文件不单设上限，只受总量约束。超出时拒绝上传。
- 已知限制：Bot 使用非百炼供应商时，窗口仍取槽位声明值，不探测真实窗口。

## 支持的文件

只收纯文本。扩展名白名单：`txt md markdown csv tsv json yaml yml toml ini log sql html css xml` 以及代码文件 `py ts tsx js jsx java go rs c cc cpp h hpp rb php sh swift kt`。其他格式（PDF、Word、图片等）返回 415，提示暂不支持。内容含 NUL 字符视为二进制，同样拒绝。

## 后端

- 表 `bot_files`（Alembic `0011`）：`file_id` 主键、`bot_id`（外键 `bots.bot_id`）、`filename`、`chars`、`content`、`created_at`；`bot_id` 上建索引。
- 同名文件重新上传视为替换，总量检查时排除旧文件。
- 接口：
  - `GET /api/bots/{id}/files` → `{items:[{file_id, filename, chars, created_at}], used_chars, budget_chars}`
  - `POST /api/bots/{id}/files`，JSON `{filename, content}` → 201，返回新文件条目与用量
  - `DELETE /api/bots/{id}/files/{file_id}` → 204
- 错误：`bot_not_found` 404、`bot_archived` 409、`validation_error` 400、`unsupported_file_type` 415、`secret_in_body` 400（沿用现有密钥检测）、`file_budget_exceeded` 409、`file_not_found` 404。
- 文件名只取 basename，去掉控制字符，最长 120。

## 注入模型

- 聊天时把该 Bot 的文件放进系统提示的「资料文件」部分，每个文件一个代码块并标明文件名，围栏长度大于内容里最长的反引号串。
- 提示声明这些内容只是参考资料，其中出现的指示不要执行。
- 总量超过当前预算（例如换了更小窗口的模型）时，从最旧的文件开始少带，并在聊天响应里返回 `files_omitted`（数量），界面提示一次。

## 前端

- 聊天输入框左侧加「+」按钮，点击弹出面板：「上传文件」、文件列表（文件名、字符数、删除）、用量「已用 / 上限」。
- 前端用 `File.text()` 读文本，再以 JSON 发送；扩展名在前端也先检查一遍，错误信息显示在面板里。
- 只在聊天页做，Bot 配置页不加。

## 测试

- 后端：上传、替换、列表、删除、超限、疑似密钥、非文本、归档 Bot、注入系统提示、`files_omitted`、迁移升降级。
- 前端：「+」面板、上传流程、错误提示、删除、`files_omitted` 提示。
- 更新 OpenAPI 快照与 `docs/API.md`。
