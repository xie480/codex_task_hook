"""把 Hook 输入连接到快照、状态保存与 Diff 获取流程。"""

from __future__ import annotations

from datetime import datetime
from datetime import timezone
from pathlib import Path

from .classifier import classify_task
from .config import ReviewConfig
from .git_snapshot import GitRepository
from .git_snapshot import GitRepositoryError
from .git_snapshot import GitSnapshotter
from .hook_io import HookInput
from .hook_io import HookOutput
from .models import TaskState
from .report import ReportWriteError
from .report import ReviewReportWriter
from .reviewer import ReviewRunner
from .state import TaskStateStore


class TaskOrchestrator:
    """执行任务开始/结束 Hook 的安全最小生命周期。"""

    def __init__(
        self,
        data_root: Path,
        review_runner: ReviewRunner | None = None,
        report_writer: ReviewReportWriter | None = None,
    ) -> None:
        """初始化插件状态目录。

        Args:
            data_root: Codex 提供的 `PLUGIN_DATA` 持久化目录。
            review_runner: 可选的 Reviewer 执行器，便于离线测试和复用。
            report_writer: 可选的报告写入器，便于离线测试和复用。
        """

        self.state_store = TaskStateStore(data_root)
        self.review_runner = (
            review_runner
            if review_runner is not None
            else ReviewRunner()
        )
        self.report_writer = (
            report_writer
            if report_writer is not None
            else ReviewReportWriter()
        )

    def handle_user_prompt_submit(
        self,
        hook_input: HookInput,
    ) -> HookOutput:
        """捕获任务开始 Tree 并保存到隔离状态文件。

        Args:
            hook_input: 已校验的 UserPromptSubmit Hook 输入。

        Returns:
            记录成功、非 Git 目录或失败时的安全 Hook 输出。
        """

        try:
            repository = GitRepository.find(
                hook_input.cwd,
            )
            snapshot = GitSnapshotter(
                repository,
            ).capture()
            task_state = TaskState(
                identity=hook_input.identity,
                repo_root=repository.root,
                base_tree=snapshot.tree_id,
                prompt=hook_input.prompt,
                created_at=datetime.now(
                    timezone.utc,
                ).isoformat(),
            )
            self.state_store.save(task_state)
        except GitRepositoryError as error:
            return HookOutput(
                "skipped",
                "snapshot_failed",
                str(error),
            )
        except OSError as error:
            return HookOutput(
                "skipped",
                "state_write_failed",
                f"无法保存任务快照状态: {error}",
            )

        return HookOutput(
            "recorded",
            "snapshot_recorded",
            f"已记录任务开始快照（{snapshot.tree_id}）",
        )

    def handle_stop(
        self,
        hook_input: HookInput,
    ) -> HookOutput:
        """读取任务状态并获取同一仓库中的最终 Tree 与精确 Diff。

        Args:
            hook_input: 已校验的 Stop Hook 输入。

        Returns:
            跳过、完成 Review 或失败降级时的安全 Hook 输出。
        """

        if hook_input.stop_hook_active:
            self.state_store.remove(
                hook_input.identity,
            )
            return HookOutput(
                "skipped",
                "stop_hook_active",
                "Stop Hook 已处于重入状态，本次跳过审查",
            )

        task_state = self.state_store.load(
            hook_input.identity,
        )

        if task_state is None:
            return HookOutput(
                "skipped",
                "missing_task_state",
                "未找到本轮任务开始快照；为避免混入其他修改，未执行 Git Diff",
            )

        try:
            repository = GitRepository.find(
                hook_input.cwd,
            )

            if repository.root != task_state.repo_root.resolve():
                self.state_store.remove(
                    hook_input.identity,
                )
                return HookOutput(
                    "skipped",
                    "repository_changed",
                    "任务开始和结束时的 Git 仓库不同，未生成 Diff",
                )

            snapshotter = GitSnapshotter(repository)
            final_snapshot = snapshotter.capture()
            diff_result = snapshotter.diff(
                task_state.base_tree,
                final_snapshot.tree_id,
            )
        except (
            GitRepositoryError,
            OSError,
        ) as error:
            self.state_store.remove(
                hook_input.identity,
            )
            return HookOutput(
                "skipped",
                "snapshot_failed",
                f"无法安全获取任务结束 Diff: {error}",
            )

        if diff_result.is_empty:
            self.state_store.remove(
                hook_input.identity,
            )
            return HookOutput(
                "skipped",
                "no_changes",
                "本轮没有代码变化，无需启动 Review",
            )

        config = ReviewConfig.from_repo(
            repository.root,
        )
        classification = classify_task(
            task_state.prompt,
            diff_result,
            config,
        )

        if not classification.should_review:
            self.state_store.remove(
                hook_input.identity,
            )
            return HookOutput(
                "skipped",
                classification.kind,
                classification.reason,
            )

        review_result = self.review_runner.run(
            repository.root,
            final_snapshot.tree_id,
            diff_result,
            task_state.prompt,
            config,
        )

        if review_result.status not in {
            "completed",
            "failed",
        }:
            self.state_store.remove(
                hook_input.identity,
            )
            return HookOutput(
                "skipped",
                "review_skipped",
                review_result.error or "Reviewer 本次未运行",
            )

        try:
            report_path = self.report_writer.write(
                repository.root,
                config,
                task_state,
                diff_result,
                classification,
                review_result,
            )
        except ReportWriteError as error:
            self.state_store.remove(
                hook_input.identity,
            )
            return HookOutput(
                "review_failed",
                "report_write_failed",
                f"Review 已结束但报告写入失败，主任务继续：{error}",
            )

        self.state_store.remove(
            hook_input.identity,
        )

        if review_result.status == "completed":
            return HookOutput(
                "reviewed",
                "review_completed",
                (
                    f"{classification.reason}；已完成只读 Review，"
                    f"覆盖 {classification.changed_files} 个文件、"
                    f"{classification.changed_lines} 行变化；报告：{report_path}"
                ),
            )

        if review_result.status == "failed":
            return HookOutput(
                "review_failed",
                "review_failed",
                (
                    "只读 Review 未完成，主任务继续："
                    f"{review_result.error or '未知 Reviewer 错误'}；"
                    f"报告：{report_path}"
                ),
            )

    @staticmethod
    def load_config(
        repo_root: Path,
    ) -> ReviewConfig:
        """读取项目配置，供后续分类与审查阶段复用。

        Args:
            repo_root: 当前仓库根目录。

        Returns:
            项目级 Review 配置或默认配置。
        """

        return ReviewConfig.from_repo(repo_root)
