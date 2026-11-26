"""Markdown Review 报告结构和 Reviewer 内容格式测试。"""

from __future__ import annotations

import unittest
from datetime import datetime
from datetime import timezone

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


if __name__ == "__main__":
    unittest.main()
