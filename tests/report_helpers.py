"""报告测试共享数据与临时工作区工具。"""

from __future__ import annotations

from pathlib import Path

from codex_task_review.models import ClassificationResult
from codex_task_review.models import DiffFile
from codex_task_review.models import DiffResult
from codex_task_review.models import ReviewResult
from codex_task_review.models import TaskIdentity
from codex_task_review.models import TaskState
from tests.git_helpers import temporary_git_repository
from tests.temp_utils import temporary_workspace


def make_report_data(
    repo_root: Path,
    review_status: str = "completed",
    raw_output: str = "No findings",
    error: str | None = None,
) -> tuple[TaskState, DiffResult, ClassificationResult, ReviewResult]:
    """构造供报告格式和写入测试共享的稳定输入模型。

    Args:
        repo_root: 报告所属的临时仓库根目录。
        review_status: 模拟 Reviewer 的完成状态。
        raw_output: Reviewer 返回的原始 Markdown 或文本。
        error: Reviewer 失败原因，可为空。

    Returns:
        任务状态、任务 Diff、分类结果和 Reviewer 结果四元组。
    """

    task = TaskState(
        identity=TaskIdentity(
            session_id="report-session",
            turn_id="report-turn",
        ),
        repo_root=repo_root,
        base_tree="a" * 40,
        prompt="修复一个报告测试中的问题",
        created_at="2026-11-26T01:02:03+00:00",
    )
    diff = DiffResult(
        base_tree="a" * 40,
        final_tree="b" * 40,
        patch=(
            "diff --git a/src/模块.py b/src/模块.py\n"
            "@@ -1 +1 @@\n"
            "-return False\n"
            "+return True\n"
        ),
        files=[
            DiffFile(
                path="src/模块.py",
                status="M",
                additions=1,
                deletions=1,
            ),
        ],
        additions=1,
        deletions=1,
    )
    classification = ClassificationResult(
        kind="high_risk",
        should_review=True,
        reason="命中安全路径",
        changed_files=1,
        changed_lines=2,
        risk_evidence=[
            "path:src/security/",
        ],
    )
    review = ReviewResult(
        status=review_status,
        raw_output=raw_output,
        error=error,
    )

    return task, diff, classification, review
