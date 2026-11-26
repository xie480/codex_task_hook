"""Markdown Review 报告文件写入与路径安全测试。"""

from __future__ import annotations

import subprocess
import unittest
from datetime import datetime
from datetime import timezone
from pathlib import Path

from codex_task_review.config import ReviewConfig
from tests.report_helpers import make_report_data
from tests.report_helpers import temporary_git_repository
from tests.report_helpers import temporary_workspace


class ReportTests(unittest.TestCase):
    """验证报告原子写入、唯一命名和仓库内路径限制。"""

    def test_writer_creates_timestamped_utf8_report_without_staging(
        self,
    ):
        """验证写入路径、中文 UTF-8 内容和原始 Git Index 保持不变。"""

        from codex_task_review.report import ReviewReportWriter

        with temporary_git_repository() as repo_root:
            task, diff, classification, review = make_report_data(
                repo_root,
            )
            index_path_text = subprocess.run(
                [
                    "git",
                    "rev-parse",
                    "--git-path",
                    "index",
                ],
                cwd=repo_root,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            ).stdout.strip()
            index_path = Path(index_path_text)

            if not index_path.is_absolute():
                index_path = repo_root / index_path

            index_before = index_path.read_bytes()
            report_path = ReviewReportWriter().write(
                repo_root,
                ReviewConfig.defaults(),
                task,
                diff,
                classification,
                review,
            )
            report_content = report_path.read_text(
                encoding="utf-8",
            )
            index_after = index_path.read_bytes()
            status = subprocess.run(
                [
                    "git",
                    "status",
                    "--porcelain",
                ],
                cwd=repo_root,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            ).stdout

        self.assertEqual(
            report_path.parent.relative_to(repo_root).as_posix(),
            ".codex/reviews",
        )
        self.assertRegex(
            report_path.name,
            r"^code-review-\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}\.md$",
        )
        self.assertIn(
            "修复一个报告测试中的问题",
            report_content,
        )
        self.assertEqual(
            index_before,
            index_after,
        )
        self.assertIn(
            "?? .codex/",
            status,
        )

    def test_writer_avoids_overwriting_reports_with_same_timestamp(
        self,
    ):
        """验证同一秒并发任务通过后缀保留各自报告。"""

        from codex_task_review.report import ReviewReportWriter

        fixed_time = datetime(
            2026,
            11,
            26,
            12,
            34,
            56,
            tzinfo=timezone.utc,
        )

        with temporary_workspace() as workspace:
            repo_root = workspace / "repo"
            repo_root.mkdir()
            task, diff, classification, review = make_report_data(
                repo_root,
            )
            writer = ReviewReportWriter(
                now_provider=lambda: fixed_time,
            )
            first_path = writer.write(
                repo_root,
                ReviewConfig.defaults(),
                task,
                diff,
                classification,
                review,
            )
            first_content = first_path.read_bytes()
            second_path = writer.write(
                repo_root,
                ReviewConfig.defaults(),
                task,
                diff,
                classification,
                review,
            )
            second_content = second_path.read_bytes()
            first_content_after = first_path.read_bytes()

        self.assertNotEqual(
            first_path,
            second_path,
        )
        self.assertTrue(
            second_path.name.endswith("-02.md"),
        )
        self.assertEqual(
            first_content_after,
            first_content,
        )
        self.assertTrue(
            second_content,
        )

    def test_writer_rejects_report_directory_escape(
        self,
    ):
        """验证项目配置不能把报告路径解析到仓库以外。"""

        from codex_task_review.report import ReportWriteError
        from codex_task_review.report import ReviewReportWriter

        with temporary_workspace() as workspace:
            repo_root = workspace / "repo"
            repo_root.mkdir()
            task, diff, classification, review = make_report_data(
                repo_root,
            )
            config = ReviewConfig.defaults()
            config.report_directory = "../../outside-reports"

            with self.assertRaises(ReportWriteError):
                ReviewReportWriter().write(
                    repo_root,
                    config,
                    task,
                    diff,
                    classification,
                    review,
                )

            self.assertFalse(
                (workspace.parent / "outside-reports").exists(),
            )


if __name__ == "__main__":
    unittest.main()
