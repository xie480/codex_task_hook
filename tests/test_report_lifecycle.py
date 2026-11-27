"""Markdown Review 报告与 Stop 生命周期集成测试。"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import Mock
from unittest.mock import patch

from tests.report_helpers import temporary_git_repository
from tests.report_helpers import temporary_workspace


class ReportTests(unittest.TestCase):
    """验证 Stop 时序、失败安全放行和当前任务状态清理。"""

    def test_report_write_failure_returns_findings_without_faking_a_path(
        self,
    ):
        """验证报告磁盘故障仍回传 findings，且不伪造报告路径。"""

        from codex_task_review.hook_io import HookInput
        from codex_task_review.models import ReviewResult
        from codex_task_review.orchestrator import TaskOrchestrator
        from codex_task_review.report import ReportWriteError
        from codex_task_review.state import TaskStateStore

        with temporary_workspace() as workspace:
            with temporary_git_repository() as repo_root:
                data_root = workspace / "plugin-data"
                review_runner = Mock()
                review_runner.run.return_value = ReviewResult(
                    status="completed",
                    raw_output="No findings",
                )
                report_writer = Mock()
                report_writer.write.side_effect = ReportWriteError(
                    "disk full",
                )
                orchestrator = TaskOrchestrator(
                    data_root,
                    review_runner=review_runner,
                    report_writer=report_writer,
                )
                prompt_input = HookInput.from_payload(
                    {
                        "hook_event_name": "UserPromptSubmit",
                        "session_id": "report-failure-session",
                        "turn_id": "report-failure-turn",
                        "cwd": str(repo_root),
                        "prompt": "add a feature",
                    }
                )
                orchestrator.handle_user_prompt_submit(prompt_input)
                (repo_root / "feature.py").write_text(
                    "def feature():\n    return True\n",
                    encoding="utf-8",
                )
                stop_input = HookInput.from_payload(
                    {
                        "hook_event_name": "Stop",
                        "session_id": "report-failure-session",
                        "turn_id": "report-failure-turn",
                        "cwd": str(repo_root),
                        "stop_hook_active": False,
                        "last_assistant_message": "done",
                    }
                )

                stop_output = orchestrator.handle_stop(stop_input)
                stored = TaskStateStore(data_root).load(
                    stop_input.identity,
                )

        result = stop_output.to_dict()
        self.assertEqual(
            result["decision"],
            "block",
        )
        self.assertIn(
            "report_write_failed",
            result["systemMessage"],
        )
        self.assertIn(
            "disk full",
            result["systemMessage"],
        )
        self.assertIn(
            "报告写入失败",
            result["reason"],
        )
        self.assertNotIn(
            "完整报告：",
            result["reason"],
        )
        self.assertIsNone(stored)
        review_runner.run.assert_called_once()
        report_writer.write.assert_called_once()

    def test_stop_writes_report_after_diff_and_then_cleans_task_state(
        self,
    ):
        """验证报告写入发生在 Diff 与 Reviewer 之后且只清理本轮状态。"""

        from codex_task_review.git_snapshot import GitSnapshotter
        from codex_task_review.models import DiffResult
        from codex_task_review.hook_io import HookInput
        from codex_task_review.models import ReviewResult
        from codex_task_review.orchestrator import TaskOrchestrator
        from codex_task_review.state import TaskStateStore

        events: list[str] = []

        with temporary_workspace() as workspace:
            with temporary_git_repository() as repo_root:
                data_root = workspace / "plugin-data"
                review_runner = Mock()
                review_runner.run.return_value = ReviewResult(
                    status="completed",
                    raw_output="No findings",
                )
                report_writer = Mock()
                report_path = repo_root / ".codex" / "reviews" / "report.md"

                def record_report(
                    *arguments: object,
                ) -> Path:
                    """记录报告调用顺序并返回可断言的虚拟报告路径。

                    Args:
                        arguments: 报告写入接口传入的任务参数。

                    Returns:
                        临时仓库中的固定报告路径。
                    """

                    events.append("report")
                    return report_path

                report_writer.write.side_effect = record_report
                orchestrator = TaskOrchestrator(
                    data_root,
                    review_runner=review_runner,
                    report_writer=report_writer,
                )
                prompt_input = HookInput.from_payload(
                    {
                        "hook_event_name": "UserPromptSubmit",
                        "session_id": "report-flow-session",
                        "turn_id": "report-flow-turn",
                        "cwd": str(repo_root),
                        "prompt": "add a feature",
                    }
                )
                orchestrator.handle_user_prompt_submit(prompt_input)
                (repo_root / "feature.py").write_text(
                    "def feature():\n    return True\n",
                    encoding="utf-8",
                )
                original_diff = GitSnapshotter.diff

                def record_diff(
                    snapshotter: GitSnapshotter,
                    base_tree: str,
                    final_tree: str,
                ) -> DiffResult:
                    """在计算真实 Diff 后记录其生命周期位置。

                    Args:
                        snapshotter: 被编排器调用的快照器实例。
                        base_tree: 任务起始快照 Tree ID。
                        final_tree: 任务结束快照 Tree ID。

                    Returns:
                        原始快照器计算出的任务级 Diff。
                    """

                    result = original_diff(
                        snapshotter,
                        base_tree,
                        final_tree,
                    )
                    events.append("diff")
                    return result

                stop_input = HookInput.from_payload(
                    {
                        "hook_event_name": "Stop",
                        "session_id": "report-flow-session",
                        "turn_id": "report-flow-turn",
                        "cwd": str(repo_root),
                        "stop_hook_active": False,
                        "last_assistant_message": "done",
                    }
                )

                with patch(
                    "codex_task_review.orchestrator.GitSnapshotter.diff",
                    record_diff,
                ):
                    stop_output = orchestrator.handle_stop(stop_input)

                stored = TaskStateStore(data_root).load(
                    stop_input.identity,
                )

        self.assertLess(
            events.index("diff"),
            events.index("report"),
        )
        stop_result = stop_output.to_dict()
        self.assertIn(
            "review_completed",
            stop_result["systemMessage"],
        )
        self.assertIn(
            str(report_path),
            stop_result["systemMessage"],
        )
        self.assertEqual(
            stop_result["decision"],
            "block",
        )
        self.assertIn(
            str(report_path),
            stop_result["reason"],
        )
        self.assertIsNone(stored)
        review_runner.run.assert_called_once()
        report_writer.write.assert_called_once()


if __name__ == "__main__":
    unittest.main()
