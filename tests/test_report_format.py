"""Markdown Review 报告结构和 Reviewer 内容格式测试。"""

from __future__ import annotations

import unittest
from datetime import datetime
from datetime import timezone
from pathlib import Path

from tests.report_helpers import make_report_data
from tests.report_helpers import temporary_workspace


class ReportTests(unittest.TestCase):
    """验证报告正文完整且不会误报审查结论。"""

    def test_format_report_includes_metadata_findings_and_all_sections(
        self,
    ):
        """验证成功报告含任务、Diff、等级、检查项和原始 Reviewer 文本。"""

        from codex_task_review.report_format import format_report

        raw_output = "\n".join(
            [
                "## P0",
                "未发现。",
                "## P1",
                "### 问题一",
                "- 标题：可能丢失用户数据",
                "  - 文件：src/模块.py:12",
                "  - 触发条件：保存期间网络断开",
                "  - 影响：最后一次写入被覆盖",
                "  - 证据：return True",
                "  - 建议：保留旧值直到写入成功",
                "  - 推荐测试：模拟写入失败",
                "  - 置信度：高",
                "## P2",
                "未发现。",
                "## P3",
                "未发现。",
                "## 已检查且未发现问题",
                "输入字段校验正常。",
                "## 未能检查",
                "无。",
                "## 修复建议汇总",
                "保留旧值直到写入成功。",
            ]
        )
        with temporary_workspace() as workspace:
            task, diff, classification, review = make_report_data(
                workspace,
                raw_output=raw_output,
            )

            report = format_report(
                task,
                diff,
                classification,
                review,
                datetime(
                    2026,
                    11,
                    26,
                    12,
                    34,
                    56,
                    tzinfo=timezone.utc,
                ),
            )

        for heading in (
            "## P0",
            "## P1",
            "## P2",
            "## P3",
            "## 已检查且未发现问题",
            "## 未能检查",
            "## 修复建议汇总",
            "## Reviewer 原始输出",
        ):
            with self.subTest(heading=heading):
                self.assertIn(
                    heading,
                    report,
                )

        for expected_text in (
            "修复一个报告测试中的问题",
            "a" * 40,
            "b" * 40,
            "src/模块.py",
            "命中安全路径",
            "可能丢失用户数据",
            "return True",
            "推荐测试：模拟写入失败",
            "保留旧值直到写入成功。",
            "2026-11-26T12:34:56+00:00",
        ):
            with self.subTest(expected_text=expected_text):
                self.assertIn(
                    expected_text,
                    report,
                )

    def test_failed_review_marks_severity_sections_unchecked(
        self,
    ):
        """验证 Reviewer 失败时保留原因并标明未执行等级检查。"""

        from codex_task_review.report_format import format_report

        with temporary_workspace() as workspace:
            task, diff, classification, review = make_report_data(
                workspace,
                review_status="failed",
                raw_output="partial reviewer output",
                error="Codex CLI 超时",
            )
            report = format_report(
                task,
                diff,
                classification,
                review,
                datetime.now(
                    timezone.utc,
                ),
            )

        self.assertIn(
            "Codex CLI 超时",
            report,
        )
        self.assertIn(
            "Reviewer 未完成审查",
            report,
        )
        self.assertIn(
            "partial reviewer output",
            report,
        )
        self.assertIn(
            "## P0",
            report,
        )
        self.assertIn(
            "## P3",
            report,
        )

    def test_format_report_bounds_oversized_reviewer_output(
        self,
    ):
        """验证报告限制原始 Reviewer 文本长度且保留截断说明。"""

        from codex_task_review.report_format import MAX_REVIEW_OUTPUT_BYTES
        from codex_task_review.report_format import format_report

        oversized_output = "x" * (
            MAX_REVIEW_OUTPUT_BYTES + 128
        )

        with temporary_workspace() as workspace:
            task, diff, classification, review = make_report_data(
                workspace,
                raw_output=oversized_output,
            )
            report = format_report(
                task,
                diff,
                classification,
                review,
            )

        self.assertIn(
            "原始 Reviewer 输出超过报告上限",
            report,
        )
        self.assertNotIn(
            oversized_output,
            report,
        )

    def test_format_session_feedback_contains_findings_and_report_path(
        self,
    ):
        """验证会话摘要包含 finding 定位信息及完整报告路径。"""

        from codex_task_review.report_format import format_session_feedback

        raw_output = "\n".join(
            [
                "## P0",
                "未发现。",
                "## P1",
                "### 令牌校验可能绕过",
                "- 文件：src/auth.py:42",
                "- 影响：空令牌会被当作有效值。",
                "- 建议：拒绝空白输入。",
            ]
        )

        with temporary_workspace() as workspace:
            _, _, _, review = make_report_data(
                workspace,
                raw_output=raw_output,
            )
            report_path = workspace / ".codex" / "reviews" / "review.md"
            feedback = format_session_feedback(
                review,
                report_path,
            )

        for expected_text in (
            "只读审查已完成",
            "P1",
            "令牌校验可能绕过",
            "src/auth.py:42",
            "空令牌会被当作有效值",
            str(report_path),
        ):
            with self.subTest(expected_text=expected_text):
                self.assertIn(
                    expected_text,
                    feedback,
                )

    def test_format_session_feedback_marks_empty_and_failed_reviews_honestly(
        self,
    ):
        """验证无发现和审查失败反馈不会混淆为同一种结果。"""

        from codex_task_review.report_format import format_session_feedback

        with temporary_workspace() as workspace:
            _, _, _, no_findings_review = make_report_data(
                workspace,
                raw_output="No findings",
            )
            no_findings = format_session_feedback(
                no_findings_review,
                workspace / "review.md",
            )
            _, _, _, empty_review = make_report_data(
                workspace,
                raw_output="",
            )
            empty = format_session_feedback(
                empty_review,
                workspace / "empty-review.md",
            )
            _, _, _, failed_review = make_report_data(
                workspace,
                review_status="failed",
                raw_output="partial output",
                error="Codex CLI 超时",
            )
            failed = format_session_feedback(
                failed_review,
                workspace / "failed-review.md",
            )

        self.assertIn(
            "未发现可操作问题",
            no_findings,
        )
        self.assertIn(
            "未返回可展示的审查结论",
            empty,
        )
        self.assertNotIn(
            "未发现可操作问题",
            empty,
        )
        self.assertIn(
            "审查未完成，不能视为审查通过",
            failed,
        )
        self.assertIn(
            "Codex CLI 超时",
            failed,
        )
        self.assertIn(
            "partial output",
            failed,
        )

    def test_format_session_feedback_bounds_text_and_preserves_report_path(
        self,
    ):
        """验证 findings 超长时有界截断且报告路径仍保留。"""

        from codex_task_review.report_format import MAX_SESSION_FEEDBACK_BYTES
        from codex_task_review.report_format import format_session_feedback

        oversized_output = "\n".join(
            [
                "## P0",
                "### Critical",
                "文件：src/critical.py:1",
                "证据：" + "危险" * MAX_SESSION_FEEDBACK_BYTES,
            ]
        )
        report_path = "C:/repo/.codex/reviews/code-review-final.md"
        expected_report_path = str(
            Path(report_path),
        )

        with temporary_workspace() as workspace:
            _, _, _, review = make_report_data(
                workspace,
                raw_output=oversized_output,
            )
            feedback = format_session_feedback(
                review,
                Path(report_path),
            )

        self.assertLessEqual(
            len(feedback.encode("utf-8")),
            MAX_SESSION_FEEDBACK_BYTES,
        )
        self.assertIn(
            "会话摘要已截断",
            feedback,
        )
        self.assertIn(
            expected_report_path,
            feedback,
        )


if __name__ == "__main__":
    unittest.main()
