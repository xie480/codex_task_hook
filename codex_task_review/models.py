"""Codex Task Review 的共享数据模型。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TaskIdentity:
    """表示一个由会话和轮次共同确定的任务身份。"""

    session_id: str
    turn_id: str

    @property
    def key(
        self,
    ) -> str:
        """返回会话与轮次的组合键。

        Returns:
            用冒号分隔的任务身份字符串。
        """

        return f"{self.session_id}:{self.turn_id}"


@dataclass(frozen=True)
class Snapshot:
    """保存一次工作区 Tree 与其所属仓库根目录。"""

    tree_id: str
    repo_root: Path


@dataclass(frozen=True)
class DiffFile:
    """描述本轮 Diff 中的一个文件变化。"""

    path: str
    status: str
    additions: int
    deletions: int
    old_path: str | None = None


@dataclass(frozen=True)
class DiffResult:
    """保存 BASE Tree 到 FINAL Tree 的完整 Diff 和统计信息。"""

    base_tree: str
    final_tree: str
    patch: str
    files: list[DiffFile]
    additions: int
    deletions: int

    @property
    def changed_lines(
        self,
    ) -> int:
        """返回新增与删除行数的绝对值之和。

        Returns:
            本次 Diff 的总变更行数。
        """

        return abs(self.additions) + abs(self.deletions)

    @property
    def is_empty(
        self,
    ) -> bool:
        """判断本轮是否没有文件变化。

        Returns:
            当文件清单和补丁内容均为空时返回真。
        """

        return not self.files and not self.patch


@dataclass(frozen=True)
class TaskState:
    """保存任务开始阶段用于 Stop Hook 的最小状态。"""

    identity: TaskIdentity
    repo_root: Path
    base_tree: str
    prompt: str
    created_at: str
    config_version: str = "1"


@dataclass(frozen=True)
class ClassificationResult:
    """保存确定性任务分类和是否审查的结论。"""

    kind: str
    should_review: bool
    reason: str
    changed_files: int
    changed_lines: int
    risk_evidence: list[str]


@dataclass(frozen=True)
class ReviewResult:
    """保存 Reviewer 执行状态、原始输出和失败原因。"""

    status: str
    raw_output: str
    error: str | None = None
    workspace: Path | None = None
