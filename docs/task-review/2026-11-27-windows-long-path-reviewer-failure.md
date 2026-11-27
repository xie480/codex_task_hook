# Windows 长路径导致 Reviewer 快照导出失败

## 背景与根因

Codex Task Review 在 Windows 上导出 FINAL Tree 时，连续两次失败于同一文件：

`aiep/aiep_k12/server/agents/new/skills/releases/2ca20bb34dcf7a68bfcf4b261f3b9f5d7c9bbd34473065ed96f863b2591b7f53/package/examples/arcade-cabinet/arcade-cabinet.css`

两次使用的临时目录和 Tree ID 不同，但该文件都存在于 FINAL Tree，第一次任务的 Diff 中也没有修改它。报错绝对路径为 261 个字符；调查时系统 `LongPathsEnabled` 为 `0`。Reviewer 在运行 `codex review` 前导出整个仓库，因此这次失败发生在本地临时快照准备阶段，审查并未开始。

Windows 传统 `MAX_PATH` 为 260 个字符（包括终止符）。Windows 长路径需要操作系统设置及应用支持；详见 [Microsoft 路径长度说明](https://learn.microsoft.com/en-us/windows/win32/fileio/maximum-file-path-limitation?tabs=powershell) 和 [Python Windows 长路径说明](https://docs.python.org/3.13/using/windows.html#removing-the-max-path-limitation)。

## 核心修改

- Reviewer 临时工作区从 `codex-task-review-{32位UUID}` 缩短为 `ctr-{64位随机串}`，使用标准库 `secrets.token_hex(8)`。
- 隔离快照目录从 `final-snapshot` 改为 `snapshot`。
- 保留唯一目录的原子创建和冲突重试。对本次失败路径，导出目标由 261 个字符降到约 225 个字符。
- Tree 导出遇到 Windows 文件系统错误时，检查异常路径长度并按 UTF-16 单元计算；超过传统上限时报告路径长度、失败路径和可操作的处理建议。

## 验证

- 新增深层文件集成回归用例。修复前，它在当前 Windows 环境中复现了原始 `FileNotFoundError`；修复后，深层文件已成功导出，模拟 Reviewer 收到该文件并完成。
- 新增长路径错误诊断用例，验证报告包含 `MAX_PATH`、实际路径和路径长度。
- 受影响模块：16 项通过。
- 完整测试套件：61 项通过。
- `py -3 -m compileall -q codex_task_review hooks tests`：通过。
- Reviewer 由测试 Fake 模拟；未调用真实 Codex CLI 或真实模型。

## 风险与后续

缩短临时目录解决本次已测路径，但相对路径更深的仓库仍可能超过传统上限。此时 Hook 会给出明确诊断；若要覆盖这类极端路径，需要额外设计并验证 Windows 扩展路径在路径校验、符号链接、Git 子进程及清理流程中的完整支持。本次未修改系统注册表，也不要求用户为常规运行启用全局长路径设置。
