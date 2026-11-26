# Codex Task Review

**按任务边界生成 Git 快照，并对需要关注的变更运行只读 Codex Review。**

Codex Task Review 是一个独立的 Codex 插件。它在任务开始时保存仓库快照，在任务结束时只比较本轮变更；符合规则的任务会交由 `codex review -` 检查，并把结果写入仓库内的 Markdown 报告。

插件不会修改用户文件或真实 Git Index，不会自动暂存、提交或阻止主任务继续。

> 插件包含 Codex 生命周期 Hooks，通过 GitHub Marketplace 或本地仓库安装。用户必须在 Codex 中检查并信任 Hooks 后，它们才会运行。含生命周期 Hooks 的插件不能提交到 OpenAI 公共插件目录。

## 工作流程

1. `UserPromptSubmit` 将任务 Prompt 与临时 Git 起始快照关联到当前 session 和 turn。
2. `Stop` 创建最终快照，计算起始与最终 Tree 之间的任务级 Diff。
3. 本地分类器跳过无变化、小型明确 Bug 修复和纯视觉 UI 变更；复杂任务、高风险变更和 UI 业务逻辑会运行 Reviewer。
4. Reviewer 在只读临时工作区执行 `codex --sandbox read-only review -`，只接收当前任务 Diff。
5. 插件在仓库内写入 `.codex/reviews/code-review-YYYY-MM-DD-HH-mm-ss.md`。

报告在最终快照和 Diff 完成之后才写入，因此不会混入产生该报告的当前任务 Diff。插件不会修改目标仓库的 `.gitignore`；如果你不希望报告显示为未跟踪文件，可在目标仓库手动忽略 `.codex/reviews/`。

## 环境要求

- Codex CLI，支持 `codex plugin`、生命周期 Hooks 和 `codex review -`。
- Git 2.x；Windows 推荐 Git for Windows。
- Python 3.10 或更高版本。Windows 使用 `py -3`；macOS/Linux 使用 `python3`。
- 插件 Hooks 只在本机 Codex 环境执行。安装插件不会部署云端 Hook 脚本。

本项目只使用 Python 标准库；测试使用 `unittest`，不需要安装第三方 Python 包。

## 插件清单和兼容选择

本仓库用 `.codex-plugin/plugin.json` 作为 Codex 主清单，并省略根目录 `plugin.json`。当前核验的 Codex 插件加载源码对 Agent Plugins 格式返回空的插件 Hook 列表；Codex 兼容清单格式可以声明 `hooks` 并加载 `hooks/hooks.json`。因此本项目优先保证 Codex 生命周期 Hook 可用，暂不提供 Agent Plugins portable manifest。

这一选择基于当前 Codex CLI 插件加载路径。若 Codex 后续为 portable 格式加载插件 Hooks，可再恢复根目录清单并重新验证安装行为。可查阅 [Codex 插件打包文档](https://developers.openai.com/plugins/build/plugins)、[Hooks 文档](https://developers.openai.com/codex/hooks) 和 [Codex 插件加载器](https://github.com/openai/codex/blob/main/codex-rs/core-plugins/src/loader.rs#L3853-L3873)。

插件 Hooks 是非托管 Hook。安装或启用插件不会自动信任它们；第一次使用前，在 Codex CLI 输入 `/hooks` 检查并信任当前定义。更新 Hook 脚本后，Codex 可能要求重新审查。

## 仓库结构

```text
.
├── .agents/plugins/marketplace.json
├── .codex-plugin/plugin.json
├── assets/codex-task-review.svg
├── codex_task_review/
├── examples/
├── hooks/
├── tests/
├── LICENSE
└── README.md
```

## 安装

先把 Marketplace 文件与插件清单中的 `YOUR_GITHUB_USERNAME`、`YOUR_NAME` 替换成你的 GitHub 用户名和发布者名称，再发布仓库。

```powershell
codex plugin marketplace add YOUR_GITHUB_USERNAME/codex-task-review --ref main
codex plugin add codex-task-review@codex-task-review-marketplace
codex plugin list
```

CLI 安装只注册并安装插件，不会绕过 Hook 信任流程。回到 Codex 后打开 `/hooks`，检查 `UserPromptSubmit` 和 `Stop` 两个命令及其插件路径，再信任这组 Hook。

如果你在本地修改了插件，可以创建本地 Marketplace 指向该插件目录；Marketplace 的 `source.path` 必须以 `./` 开始并位于 Marketplace 根目录内。远程安装时则使用仓库里的 `.agents/plugins/marketplace.json`。

## 更新

刷新 GitHub Marketplace 的快照：

```powershell
codex plugin marketplace upgrade codex-task-review-marketplace
```

Marketplace 更新后重启 Codex 会话并运行 `codex plugin list` 检查安装状态。若插件仍显示旧版本，先移除再重新安装：

```powershell
codex plugin remove codex-task-review@codex-task-review-marketplace
codex plugin add codex-task-review@codex-task-review-marketplace
```

更新的 Hook 定义需要重新审查和信任。

## 卸载

移除插件；如果不再使用该来源，再移除 Marketplace：

```powershell
codex plugin remove codex-task-review@codex-task-review-marketplace
codex plugin marketplace remove codex-task-review-marketplace
```

## 配置

项目级配置路径是 `.codex/task-review.json`。复制 `examples/task-review.json` 到目标仓库的该路径后按需调整：

```powershell
New-Item -ItemType Directory -Force .codex | Out-Null
Copy-Item examples/task-review.json .codex/task-review.json
```

默认值如下：

| 配置项 | 默认值 | 作用 |
|---|---:|---|
| `skip_simple_bugfix` | `true` | 允许跳过阈值内的简单 Bug 修复 |
| `skip_pure_ui` | `true` | 允许跳过纯视觉 UI 变更 |
| `max_bugfix_files` | `3` | 简单 Bug 修复的最大文件数 |
| `max_bugfix_changed_lines` | `80` | 简单 Bug 修复的最大变化行数 |
| `force_review_marker` | `[review:force]` | 在任务 Prompt 中强制运行 Reviewer |
| `report_directory` | `.codex/reviews` | 仓库内报告目录；绝对路径或越界路径会被拒绝 |
| `review_timeout` | `600` 秒 | 单次 `codex review` 超时 |
| `max_diff_bytes` | `1048576` 字节 | 启动 Reviewer 前允许的最大 Diff |

未配置的高风险关键词和路径使用内置默认值。修改 `.codex/task-review.json` 不会改写全局 Codex 设置。

## 跳过规则

分类按以下优先级执行：

1. 无文件变化时不运行 Reviewer。
2. Prompt 含 `[review:force]` 时运行 Reviewer。
3. 高风险路径或内容总是运行 Reviewer，例如权限、认证、支付、数据库、迁移、并发、部署和 CI 配置。
4. Prompt 表示新功能、重构、架构调整或复杂开发任务时运行 Reviewer。
5. 纯 UI 文件中的 API 请求、状态、校验、数据转换、权限、事件处理或持久化逻辑会运行 Reviewer。
6. 仅涉及静态展示、样式、文案或视觉资源的 UI 变更默认跳过。
7. 其余明确的简单 Bug 修复在最多 3 个文件且最多 80 行变化时默认跳过；其他未知或一般代码变化会运行 Reviewer。

安全路径/内容检查和强制标记优先于跳过规则。可在项目配置中关闭 `skip_simple_bugfix` 或 `skip_pure_ui`。

## 报告示例

完整示例见 [examples/code-review-example.md](examples/code-review-example.md)。报告包含任务元信息、BASE/FINAL Tree、文件统计、P0–P3、已检查与未能检查章节、修复建议和有界的 Reviewer 原始输出。报告使用 UTF-8；同一秒的并发报告会使用 `-02` 等后缀，不覆盖已有文件。

空等级会明确显示“未发现”。Reviewer 失败时，报告会标明审查未完成，不会将失败误报为通过。报告写入失败也不会阻止主任务继续。

## 常见问题

### 插件已安装，但没有记录快照

先确认项目 Hook 功能开启，再在 `/hooks` 中检查并信任插件的 Hook 定义。Codex 不会自动信任新安装的插件 Hook。

### Reviewer 没有运行

本轮可能命中无变化、简单 Bug 修复或纯视觉 UI 跳过规则。Stop Hook 会把分类原因写入 Codex 消息。高风险路径、复杂任务和检测到逻辑行为的 UI Diff 会进入 Review。

### 报告文件出现在 `git status`

报告写入目标仓库的 `.codex/reviews/`，插件不会改写该仓库的 `.gitignore`。如果希望忽略报告，可在目标仓库 `.gitignore` 中添加：

```gitignore
.codex/reviews/
```

### 目标仓库没有 HEAD

任务快照需要 Git 仓库和一个已提交的基线。如果仓库尚无首个提交，插件会安全跳过并返回原因。

### 高风险规则误报或漏报

规则基于 Prompt、路径、Diff 关键词和文件规模，不是完整静态分析。可以调整 `.codex/task-review.json`，也可在任务 Prompt 中加入 `[review:force]`。

## Windows 故障排查

- **找不到 Python：**在 PowerShell 运行 `py -3 --version`。如果失败，安装 Python 3 并启用 Python Launcher；Hook 命令使用 `py -3`。
- **找不到 Git：**运行 `git --version` 并确认 Git for Windows 已加入 `PATH`。
- **Codex 报告 Hook 未信任：**打开 `/hooks`，检查脚本路径与命令后再信任。
- **Review 超时：**增大项目配置的 `review_timeout`，并检查 `codex review --help` 是否可用。
- **路径包含空格或中文：**Hook 命令会给 `${PLUGIN_ROOT}` 路径加引号，报告使用 UTF-8；仍需确认 Git for Windows 和 Python 使用 UTF-8 环境。

## 本地开发与测试

```powershell
py -3 -m unittest discover -s tests -v
py -3 -m compileall -q codex_task_review hooks tests
```

测试使用临时仓库和假的 Reviewer 结果，不会调用真实 Codex 模型。

## GitHub 发布

此项目可以作为公开 GitHub 仓库供 Codex CLI Marketplace 安装。它含有生命周期 Hooks，因此不要把当前包描述成已发布或符合 OpenAI 公共插件目录资格。

首次推送前，将所有 `YOUR_GITHUB_USERNAME` 和 `YOUR_NAME` 占位符替换为真实发布信息。已有 GitHub 空仓库后，在当前仓库执行：

```powershell
git remote add origin https://github.com/YOUR_GITHUB_USERNAME/codex-task-review.git
git branch -M main
git push -u origin main
```

然后按“安装”章节的命令添加 Marketplace 并安装插件。公开 GitHub 仓库不等于 OpenAI 公共插件目录发布；后者有单独的提交和审核流程，且当前生命周期 Hook 插件不符合该目录的提交条件。

## 许可证

[MIT License](LICENSE)
