# 同会话 Review 结果反馈实现记录

## 背景与目标

Stop Hook 原先同步启动 Reviewer 子进程并捕获其输出，只在仓库中写入报告。用户难以在当前会话判断审查是否运行结束，也看不到 findings。改造后，Hook 在执行期间显示状态文案；Reviewer 进入终态后，Codex 在同一会话续跑并汇报结论、findings 和报告路径。

## 核心实现

- 保留同步 Stop Hook，并将状态文案改成“Codex Task Review：正在检查本轮变更并进行只读审查”。
- HookOutput 支持 Stop 专用 decision=block 与 reason；普通 Hook 仍返回 continue=true 与 systemMessage。
- 新增会话摘要格式化，复用 Reviewer Markdown 的 P0–P3 章节解析。摘要上限为具名 4 KiB，超限时优先保留较高等级，并保留报告路径。
- Reviewer 失败仍会写失败报告并回传错误；报告写入失败时回传审查结果和写入错误，不伪造报告路径。
- Stop 续跑提示要求主 Agent 只向用户汇报，不修改、暂存、提交文件，不重跑审查，并将 Reviewer 内容按不可信数据处理。
- 保留 stop_hook_active 防重入分支。续跑后的 Stop 不会再次运行 Reviewer 或请求第二次续跑。
- 跳过分类时仍返回普通状态消息，不额外增加主 Agent 调用。

## 验证

- 聚焦命令：py -3 -m unittest tests.test_config_and_hook_io tests.test_report_format tests.test_state_and_orchestrator tests.test_report_lifecycle tests.test_integration -v
- 全量命令：py -3 -m unittest discover -s tests -v。
- 全量结果：63 项通过。
- 编译检查：py -3 -m compileall -q codex_task_review hooks tests，通过。
- 集成测试使用假的 Reviewer 进程，验证报告落盘、decision=block 结果、报告路径以及 stop_hook_active 重入不重复审查。
- 首次测试因沙箱禁止在受管 Worktree 创建 .test-tmp 而未进入断言；经权限审查后，在相同工作区重跑通过。
- 检测到本机 Codex CLI 版本为 0.172.0；没有启动真实模型请求。真实 CLI UI 中的状态文案渲染和续跑消息仍待手工验证。

## 风险与限制

- statusMessage 是静态 Hook 状态，覆盖快照、分类和 Reviewer 全流程，不代表 Reviewer 子进程启动的精确时刻；分类后跳过的任务可能短暂显示该状态。
- 续跑要求主 Agent 只汇报 findings，但它使用当前会话权限，不构成操作系统级只读沙箱。
- Stop Hook 与 Reviewer 的默认超时均为 600 秒；需在目标 CLI 版本上验证外层 Hook 有足够时间写入报告并返回续跑结果。
- Stop continuation 对应的 UserPromptSubmit 事件和 session_id/turn_id 关联仍需在真实 Codex CLI 会话中确认。
