"""将只读 Review 结果安全写入仓库内 Markdown 报告。"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Callable

from .config import ReviewConfig
from .models import ClassificationResult
from .models import DiffResult
from .models import ReviewResult
from .models import TaskState
from .report_format import MAX_REVIEW_OUTPUT_BYTES
from .report_format import format_report


class ReportWriteError(RuntimeError):
    """表示报告路径越界、原子写入失败或报告目录不可用。"""


class ReviewReportWriter:
    """把已完成或失败的审查结果写入用户仓库的报告目录。"""

    def __init__(
        self,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        """设置报告时间来源。

        Args:
            now_provider: 可选的本地时间提供函数，便于确定性测试。
        """

        self.now_provider = now_provider or datetime.now

    def write(
        self,
        repo_root: Path,
        config: ReviewConfig,
        task: TaskState,
        diff: DiffResult,
        classification: ClassificationResult,
        result: ReviewResult,
    ) -> Path:
        """在仓库内原子写入一份不覆盖既有报告的 Markdown 文件。

        Args:
            repo_root: 当前任务所属的 Git 仓库根目录。
            config: 当前项目有效配置，提供报告目录。
            task: 任务身份、原始 Prompt、起始 Tree 与创建时间。
            diff: 已捕获的 BASE→FINAL 完整任务 Diff。
            classification: 本轮 Review 决策和风险证据。
            result: Reviewer 完成、失败或跳过结果。

        Returns:
            成功写入报告的绝对路径。

        Raises:
            ReportWriteError: 报告目录越出仓库或文件无法安全写入时抛出。
        """

        current_time = self.now_provider().astimezone()
        report_directory = self._report_directory(
            repo_root,
            config.report_directory,
        )

        try:
            report_directory.mkdir(
                parents=True,
                exist_ok=True,
            )
            report_directory = self._validate_inside_repository(
                repo_root,
                report_directory,
            )
            report_text = format_report(
                task,
                diff,
                classification,
                result,
                current_time,
            )
            report_bytes = report_text.encode(
                "utf-8",
                errors="replace",
            )

            return self._atomic_write(
                report_directory,
                current_time.strftime("%Y-%m-%d-%H-%M-%S"),
                report_bytes,
            )
        except ReportWriteError:
            raise
        except (
            OSError,
            UnicodeError,
        ) as error:
            raise ReportWriteError(
                f"无法写入 Review 报告: {error}"
            ) from error

    @classmethod
    def _report_directory(
        cls,
        repo_root: Path,
        configured_directory: str,
    ) -> Path:
        """解析并验证项目自定义报告目录位于仓库根目录之内。

        Args:
            repo_root: 当前仓库根目录。
            configured_directory: 配置文件中的相对报告目录。

        Returns:
            经过解析并确认未越界的报告目录路径。

        Raises:
            ReportWriteError: 配置是绝对路径或解析后离开仓库根目录时抛出。
        """

        root_path = repo_root.expanduser().resolve()
        relative_path = Path(configured_directory)

        if relative_path.is_absolute():
            raise ReportWriteError(
                "报告目录必须是仓库内的相对路径"
            )

        candidate = (root_path / relative_path).resolve(
            strict=False,
        )

        return cls._validate_inside_repository(
            root_path,
            candidate,
        )

    @staticmethod
    def _validate_inside_repository(
        repo_root: Path,
        report_directory: Path,
    ) -> Path:
        """拒绝通过父目录或既有符号链接跳出仓库的报告路径。

        Args:
            repo_root: 当前仓库根目录。
            report_directory: 已解析或待复核的报告路径。

        Returns:
            位于仓库根目录之内的绝对报告目录。

        Raises:
            ReportWriteError: 解析路径不属于仓库子树时抛出。
        """

        root_path = repo_root.expanduser().resolve()
        directory_path = report_directory.expanduser().resolve(
            strict=False,
        )

        try:
            directory_path.relative_to(root_path)
        except ValueError as error:
            raise ReportWriteError(
                "报告目录不能越出当前仓库"
            ) from error

        return directory_path

    @staticmethod
    def _atomic_write(
        report_directory: Path,
        timestamp: str,
        report_bytes: bytes,
    ) -> Path:
        """先落盘同目录临时文件，再原子创建硬链接且拒绝覆盖。

        Args:
            report_directory: 已存在且已校验的报告目录。
            timestamp: 用于报告文件名的本地时间戳。
            report_bytes: 完整 UTF-8 编码的报告内容。

        Returns:
            原子重命名后的唯一报告路径。

        Raises:
            OSError: 临时文件创建、落盘或原子改名失败时抛出。
        """

        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=".codex-task-review-",
            suffix=".tmp",
            dir=report_directory,
        )
        temporary_path = Path(temporary_name)

        try:
            with os.fdopen(
                file_descriptor,
                "wb",
            ) as temporary_file:
                temporary_file.write(report_bytes)
                temporary_file.flush()
                os.fsync(
                    temporary_file.fileno()
                )

            suffix_index = 1

            while True:
                name_suffix = (
                    ""
                    if suffix_index == 1
                    else f"-{suffix_index:02d}"
                )
                report_path = report_directory / (
                    f"code-review-{timestamp}{name_suffix}.md"
                )

                try:
                    os.link(
                        temporary_path,
                        report_path,
                    )
                    return report_path
                except FileExistsError:
                    suffix_index += 1
        finally:
            temporary_path.unlink(
                missing_ok=True,
            )
