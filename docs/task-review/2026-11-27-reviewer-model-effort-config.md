# Reviewer 模型与推理强度配置

## 背景与目标

Reviewer 通过独立的 Codex CLI 子进程执行。长时间审查时，用户需要能在目标仓库配置 Reviewer 使用的模型和推理强度，同时保留 Codex CLI 默认选择作为回退。

## 现状与方案

插件从目标仓库的 .codex/task-review.json 读取项目级配置。本次新增两个可选字段：

- review_model：Reviewer 模型名。
- review_reasoning_effort：映射到 Codex 的 model_reasoning_effort 配置项。

字段省略或设为 null 时不传入 CLI 覆盖项。设置了字段时，插件仅对当前 Reviewer 子进程追加 -c 参数，不写入或修改全局 Codex 配置。配置值按 JSON 字符串转义后作为单个 argv 参数传递，不经过 Shell。

模型和推理强度值由当前安装的 Codex CLI 与模型决定；插件只校验非空字符串，不维护可能过期的模型或推理档位清单。显式配置为空字符串或非字符串时，Hook 会报告 invalid_review_config、清除当前任务状态并继续放行主任务。

## 核心修改

- 配置数据类增加 review_model 和 review_reasoning_effort，默认均为 null。
- Reviewer 启动命令按需添加 review_model 和 model_reasoning_effort 的 -c 覆盖。
- Hook 对空值和错误类型给出可见错误，避免静默回退到不同模型。
- README 和示例 JSON 说明配置字段、默认行为及作用范围。

## 验证

- 完整命令：py -3 -m unittest discover -s tests -v。
- 完整结果：59 项通过。
- 测试使用假的 Reviewer 进程；未调用真实 Codex 模型，也未测量真实审查耗时。

## 风险与后续

启用较快模型或较低推理强度可能缩短等待时间，但实际收益取决于模型、任务 Diff 和服务负载；这次实现没有预设用户的模型或推理强度。用户可在目标仓库的 .codex/task-review.json 中填写所选值，再按实际审查耗时与发现质量调整。CLI 不支持的配置值会由 CLI 报错，插件会按 Reviewer 失败路径继续放行主任务。
