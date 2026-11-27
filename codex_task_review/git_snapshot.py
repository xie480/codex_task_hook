"""Git 仓库定位、临时 Index 快照和任务 Diff 计算。"""

from __future__ import annotations

import io
import os
import re
import subprocess
import tarfile
import tempfile
import uuid
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from pathlib import PurePosixPath
from typing import Iterable

from .models import DiffFile
from .models import DiffResult
from .models import Snapshot


TREE_ID_PATTERN = re.compile(
    r"^(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})$",
)
WINDOWS_MAX_PATH = 260


class GitRepositoryError(RuntimeError):
    """表示 Git 仓库查找、快照或 Diff 计算失败。"""


@dataclass(frozen=True)
class GitRepository:
    """封装仓库根路径与当前工作树的 Git 元数据路径。"""

    root: Path
    git_dir: Path

    @classmethod
    def find(
        cls,
        cwd: Path,
    ) -> "GitRepository":
        """从给定目录向上解析所属 Git 仓库。

        Args:
            cwd: Codex Hook 输入中的工作目录。

        Returns:
            已解析为绝对路径的仓库根目录和 Git 元数据目录。

        Raises:
            GitRepositoryError: 当前目录不属于可访问的 Git 仓库时抛出。
        """

        start_path = cwd.expanduser().resolve()
        root_result = subprocess.run(
            [
                "git",
                "rev-parse",
                "--show-toplevel",
            ],
            cwd=start_path,
            capture_output=True,
            check=False,
        )

        if root_result.returncode != 0:
            detail = root_result.stderr.decode(
                "utf-8",
                errors="replace",
            ).strip()
            raise GitRepositoryError(
                f"当前目录不属于 Git 仓库: {detail}"
            )

        repo_root = Path(
            root_result.stdout.decode(
                "utf-8",
                errors="replace",
            ).strip()
        ).resolve()
        git_dir_result = subprocess.run(
            [
                "git",
                "rev-parse",
                "--absolute-git-dir",
            ],
            cwd=repo_root,
            capture_output=True,
            check=False,
        )

        if git_dir_result.returncode != 0:
            detail = git_dir_result.stderr.decode(
                "utf-8",
                errors="replace",
            ).strip()
            raise GitRepositoryError(
                f"无法解析 Git 元数据目录: {detail}"
            )

        git_dir = Path(
            git_dir_result.stdout.decode(
                "utf-8",
                errors="replace",
            ).strip()
        ).resolve()

        return cls(
            root=repo_root,
            git_dir=git_dir,
        )

    def run_bytes(
        self,
        arguments: Iterable[str],
        env_overrides: dict[str, str] | None = None,
    ) -> bytes:
        """在仓库根目录执行 Git 命令并返回原始 stdout。

        Args:
            arguments: 不含可执行文件名的 Git 参数序列。
            env_overrides: 可选的进程级环境变量覆盖。

        Returns:
            Git 命令的标准输出字节。

        Raises:
            GitRepositoryError: Git 不可执行或命令返回非零状态时抛出。
        """

        environment = os.environ.copy()

        if env_overrides:
            environment.update(env_overrides)

        command = [
            "git",
            *arguments,
        ]

        try:
            result = subprocess.run(
                command,
                cwd=self.root,
                env=environment,
                capture_output=True,
                check=False,
            )
        except OSError as error:
            raise GitRepositoryError(
                f"无法启动 Git 命令 {command[1]}: {error}"
            ) from error

        if result.returncode != 0:
            detail = result.stderr.decode(
                "utf-8",
                errors="replace",
            ).strip()
            command_text = " ".join(command)
            raise GitRepositoryError(
                f"Git 命令失败 ({command_text}): {detail}"
            )

        return result.stdout

    def run_text(
        self,
        arguments: Iterable[str],
        env_overrides: dict[str, str] | None = None,
    ) -> str:
        """执行 Git 命令并将标准输出按 UTF-8 解码。

        Args:
            arguments: 不含可执行文件名的 Git 参数序列。
            env_overrides: 可选的进程级环境变量覆盖。

        Returns:
            使用替换策略解码后的标准输出字符串。

        Raises:
            GitRepositoryError: Git 命令无法执行或返回失败状态时抛出。
        """

        output = self.run_bytes(
            arguments,
            env_overrides=env_overrides,
        )

        return output.decode(
            "utf-8",
            errors="replace",
        ).strip()


class GitSnapshotter:
    """用临时 Git Index 对同一仓库的工作区状态生成 Tree。"""

    def __init__(
        self,
        repository: GitRepository,
    ) -> None:
        """绑定快照器到一个 Git 仓库。

        Args:
            repository: 已解析并验证的 Git 仓库。
        """

        self.repository = repository

    def capture(
        self,
    ) -> Snapshot:
        """通过独立临时 Index 将当前工作区写成 Git Tree。

        Returns:
            当前工作区快照 Tree ID 和所属仓库。

        Raises:
            GitRepositoryError: 仓库没有 HEAD 或 Git 写入快照失败时抛出。
        """

        index_path = self._create_temporary_index_path()
        environment = {
            "GIT_INDEX_FILE": str(index_path),
        }

        try:
            try:
                self.repository.run_bytes(
                    [
                        "read-tree",
                        "HEAD",
                    ],
                    env_overrides=environment,
                )
            except GitRepositoryError as error:
                raise GitRepositoryError(
                    "仓库没有可读取的初始提交 HEAD，无法创建任务快照"
                ) from error

            self.repository.run_bytes(
                [
                    "add",
                    "-A",
                ],
                env_overrides=environment,
            )
            tree_id = self.repository.run_text(
                [
                    "write-tree",
                ],
                env_overrides=environment,
            )

            return Snapshot(
                tree_id=tree_id,
                repo_root=self.repository.root,
            )
        finally:
            self._remove_temporary_index(index_path)

    def diff(
        self,
        base_tree: str,
        final_tree: str,
    ) -> DiffResult:
        """计算两个 Tree 之间的二进制补丁、路径和行数统计。

        Args:
            base_tree: 任务开始时保存的 Tree ID。
            final_tree: 任务结束时保存的 Tree ID。

        Returns:
            含重命名信息、行数统计和补丁正文的任务 Diff。

        Raises:
            GitRepositoryError: Tree ID 格式无效或 Git Diff 命令失败时抛出。
        """

        self._validate_tree_id(base_tree)
        self._validate_tree_id(final_tree)
        patch_bytes = self.repository.run_bytes(
            [
                "diff",
                "--binary",
                "--no-ext-diff",
                "--no-color",
                "-M",
                base_tree,
                final_tree,
            ]
        )
        status_bytes = self.repository.run_bytes(
            [
                "diff",
                "--name-status",
                "-z",
                "-M",
                base_tree,
                final_tree,
            ]
        )
        numstat_bytes = self.repository.run_bytes(
            [
                "diff",
                "--numstat",
                "-z",
                "--no-renames",
                base_tree,
                final_tree,
            ]
        )
        file_statuses = self._parse_name_status(status_bytes)
        line_stats = self._parse_numstat(numstat_bytes)
        files = self._merge_file_stats(
            file_statuses,
            line_stats,
        )
        additions = sum(
            item[0]
            for item in line_stats.values()
        )
        deletions = sum(
            item[1]
            for item in line_stats.values()
        )

        return DiffResult(
            base_tree=base_tree,
            final_tree=final_tree,
            patch=patch_bytes.decode(
                "utf-8",
                errors="surrogateescape",
            ),
            files=files,
            additions=additions,
            deletions=deletions,
        )

    def export_tree(
        self,
        tree_id: str,
        destination: Path,
    ) -> None:
        """安全导出 Tree 到新目录，供隔离 Reviewer 工作区使用。

        Args:
            tree_id: 经过格式校验的 Git Tree ID。
            destination: 必须尚不存在的导出目录。

        Returns:
            无；文件内容写入 destination。

        Raises:
            GitRepositoryError: 归档失败、目标目录已存在或成员路径不安全时抛出。
        """

        self._validate_tree_id(tree_id)

        if destination.exists():
            raise GitRepositoryError(
                f"Tree 导出目标必须是新目录: {destination}"
            )

        archive = self.repository.run_bytes(
            [
                "archive",
                "--format=tar",
                tree_id,
            ]
        )
        destination.mkdir(
            parents=True,
        )
        root_path = destination.resolve()

        try:
            with tarfile.open(
                fileobj=io.BytesIO(archive),
                mode="r:",
            ) as archive_file:
                for member in archive_file.getmembers():
                    member_path = self._safe_archive_path(
                        root_path,
                        member.name,
                    )

                    if member.isdir():
                        member_path.mkdir(
                            parents=True,
                            exist_ok=True,
                        )
                        continue

                    member_path.parent.mkdir(
                        parents=True,
                        exist_ok=True,
                    )

                    if member.isfile():
                        source = archive_file.extractfile(member)

                        if source is None:
                            raise GitRepositoryError(
                                f"无法读取归档成员: {member.name}"
                            )

                        member_path.write_bytes(
                            source.read()
                        )
                        continue

                    if member.issym():
                        self._create_safe_symlink(
                            root_path,
                            member_path,
                            member.linkname,
                        )
                        continue

                    raise GitRepositoryError(
                        f"不支持的 Git 归档成员类型: {member.name}"
                    )
        except (
            OSError,
            tarfile.TarError,
        ) as error:
            detail = str(error)
            failed_path = getattr(
                error,
                "filename",
                None,
            )

            if (
                os.name == "nt"
                and isinstance(
                    failed_path,
                    (str, bytes, os.PathLike),
                )
            ):
                failed_path_text = os.fsdecode(
                    failed_path,
                )
                path_character_count = len(
                    failed_path_text.encode(
                        "utf-16-le",
                        errors="surrogatepass",
                    )
                ) // 2
                path_length = path_character_count + 1

                if path_length > WINDOWS_MAX_PATH:
                    detail = (
                        "Windows 导出路径可能超过传统 MAX_PATH 限制 "
                        f"（路径 {path_character_count} 个 UTF-16 单元，含终止符共 "
                        f"{path_length}，上限 {WINDOWS_MAX_PATH}）："
                        f"{failed_path_text}。请缩短临时目录路径，或启用 "
                        "Windows 长路径支持后重启 Codex。"
                    )

            raise GitRepositoryError(
                f"无法导出 Tree {tree_id}: {detail}"
            ) from error

    def _create_temporary_index_path(
        self,
    ) -> Path:
        """在 Git 元数据目录中创建唯一的临时 Index 文件。

        Returns:
            已创建并关闭文件描述符的临时 Index 路径。

        Raises:
            GitRepositoryError: 无法在仓库元数据目录创建临时文件时抛出。
        """

        try:
            file_descriptor, filename = tempfile.mkstemp(
                prefix="codex-task-review-index-",
                suffix=f"-{uuid.uuid4().hex}.tmp",
                dir=self.repository.git_dir,
            )
            os.close(file_descriptor)
        except OSError as error:
            raise GitRepositoryError(
                f"无法创建临时 Git Index: {error}"
            ) from error

        return Path(filename)

    @staticmethod
    def _remove_temporary_index(
        index_path: Path,
    ) -> None:
        """清理本次快照的临时 Index 与其锁文件。

        Args:
            index_path: 临时 Index 的绝对路径。

        Returns:
            无；目标不存在时保持静默。
        """

        for path in (
            index_path,
            Path(f"{index_path}.lock"),
        ):
            try:
                path.unlink(
                    missing_ok=True,
                )
            except OSError:
                pass

    @staticmethod
    def _validate_tree_id(
        tree_id: str,
    ) -> None:
        """拒绝可能被解释为 Git 选项或修订表达式的外部输入。

        Args:
            tree_id: 待验证的 Git 对象 ID。

        Returns:
            格式正确时无返回值。

        Raises:
            GitRepositoryError: ID 不是完整十六进制对象 ID 时抛出。
        """

        if not TREE_ID_PATTERN.fullmatch(tree_id):
            raise GitRepositoryError(
                "快照 Tree ID 格式无效"
            )

    @staticmethod
    def _decode_git_path(
        path_bytes: bytes,
    ) -> str:
        """按文件系统可逆策略解码 Git 输出中的路径。

        Args:
            path_bytes: Git `-z` 输出中的路径字节。

        Returns:
            UTF-8 路径字符串，非法字节以代理字符保留。
        """

        return path_bytes.decode(
            "utf-8",
            errors="surrogateescape",
        )

    @classmethod
    def _parse_name_status(
        cls,
        output: bytes,
    ) -> list[tuple[str, str, str | None]]:
        """解析带 NUL 分隔路径的状态输出并保留重命名前后路径。

        Args:
            output: `git diff --name-status -z` 原始输出。

        Returns:
            由状态、目标路径和可选旧路径组成的列表。

        Raises:
            GitRepositoryError: Git 输出结构不符合预期时抛出。
        """

        tokens = output.split(b"\0")
        entries: list[tuple[str, str, str | None]] = []
        position = 0

        while position < len(tokens) and tokens[position]:
            status = tokens[position].decode(
                "ascii",
                errors="replace",
            )
            position += 1

            if status.startswith(
                (
                    "R",
                    "C",
                )
            ):
                if position + 1 >= len(tokens):
                    raise GitRepositoryError(
                        "Git 重命名状态输出不完整"
                    )

                old_path = cls._decode_git_path(
                    tokens[position]
                )
                new_path = cls._decode_git_path(
                    tokens[position + 1]
                )
                position += 2
                entries.append(
                    (
                        status,
                        new_path,
                        old_path,
                    )
                )
                continue

            if position >= len(tokens):
                raise GitRepositoryError(
                    "Git 文件状态输出不完整"
                )

            path = cls._decode_git_path(
                tokens[position]
            )
            position += 1
            entries.append(
                (
                    status,
                    path,
                    None,
                )
            )

        return entries

    @classmethod
    def _parse_numstat(
        cls,
        output: bytes,
    ) -> dict[str, tuple[int, int]]:
        """解析 `--no-renames` 行数统计，兼容制表符路径名。

        Args:
            output: `git diff --numstat -z --no-renames` 原始输出。

        Returns:
            路径到新增、删除行数的映射；二进制文件计数为零。
        """

        stats: dict[str, tuple[int, int]] = {}

        for record in output.split(b"\0"):
            if not record:
                continue

            fields = record.split(
                b"\t",
                2,
            )

            if len(fields) != 3:
                continue

            additions = cls._parse_line_count(fields[0])
            deletions = cls._parse_line_count(fields[1])
            path = cls._decode_git_path(fields[2])
            previous = stats.get(
                path,
                (
                    0,
                    0,
                ),
            )
            stats[path] = (
                previous[0] + additions,
                previous[1] + deletions,
            )

        return stats

    @staticmethod
    def _parse_line_count(
        value: bytes,
    ) -> int:
        """把 numstat 数值转换为整数，二进制标记转换为零。

        Args:
            value: Git numstat 中的单个行数字段。

        Returns:
            非负新增或删除行数；`-` 返回零。
        """

        try:
            return int(value)
        except ValueError:
            return 0

    @staticmethod
    def _merge_file_stats(
        statuses: list[tuple[str, str, str | None]],
        stats: dict[str, tuple[int, int]],
    ) -> list[DiffFile]:
        """将文件状态和 no-renames 行数统计合并。

        Args:
            statuses: 含重命名前后路径的状态记录。
            stats: 由 numstat 解析得到的路径行数映射。

        Returns:
            按 Diff 输出顺序排列的文件变化记录。
        """

        merged: list[DiffFile] = []

        for status, path, old_path in statuses:
            new_stats = stats.get(
                path,
                (
                    0,
                    0,
                ),
            )
            old_stats = stats.get(
                old_path or "",
                (
                    0,
                    0,
                ),
            )

            if old_path is not None:
                additions = new_stats[0]
                deletions = old_stats[1]
            else:
                additions = new_stats[0]
                deletions = new_stats[1]

            merged.append(
                DiffFile(
                    path=path,
                    status=status,
                    additions=additions,
                    deletions=deletions,
                    old_path=old_path,
                )
            )

        return merged

    @staticmethod
    def _safe_archive_path(
        root_path: Path,
        archive_name: str,
    ) -> Path:
        """确保归档成员解析后仍位于导出根目录中。

        Args:
            root_path: 已解析的导出目录。
            archive_name: tar 归档中的 POSIX 相对路径。

        Returns:
            位于导出目录内的成员目标路径。

        Raises:
            GitRepositoryError: 成员是绝对路径或试图离开导出目录时抛出。
        """

        relative_path = PurePosixPath(archive_name)

        if relative_path.is_absolute() or any(
            part in {
                "",
                ".",
                "..",
            }
            for part in relative_path.parts
        ):
            raise GitRepositoryError(
                f"拒绝不安全的 Git 归档路径: {archive_name}"
            )

        member_path = root_path.joinpath(
            *relative_path.parts
        )

        try:
            member_path.resolve(
                strict=False,
            ).relative_to(root_path)
        except ValueError as error:
            raise GitRepositoryError(
                f"Git 归档成员越过导出根目录: {archive_name}"
            ) from error

        return member_path

    @staticmethod
    def _create_safe_symlink(
        root_path: Path,
        link_path: Path,
        link_target: str,
    ) -> None:
        """仅创建指向导出根目录内部的相对符号链接。

        Args:
            root_path: 已解析的导出目录。
            link_path: 归档中的链接目标路径。
            link_target: 链接保存的目标字符串。

        Returns:
            无；链接目标在根目录内时创建链接。

        Raises:
            GitRepositoryError: 链接目标越界或操作系统拒绝创建链接时抛出。
        """

        target_path = Path(link_target)

        if target_path.is_absolute():
            raise GitRepositoryError(
                f"拒绝导出绝对符号链接: {link_path}"
            )

        resolved_target = (
            link_path.parent / target_path
        ).resolve(
            strict=False,
        )

        try:
            resolved_target.relative_to(root_path)
        except ValueError as error:
            raise GitRepositoryError(
                f"拒绝导出越界符号链接: {link_path} -> {link_target}"
            ) from error

        try:
            os.symlink(
                link_target,
                link_path,
            )
        except OSError as error:
            raise GitRepositoryError(
                f"无法创建 Git 符号链接 {link_path}: {error}"
            ) from error
