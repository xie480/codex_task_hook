"""临时 Git 仓库中的工作区快照集成测试。"""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.git_helpers import temporary_git_repository


class GitSnapshotTests(unittest.TestCase):
    """验证临时 Index 只记录任务间工作区变化。"""

    def test_start_dirty_files_are_excluded_from_task_diff(
        self,
    ):
        """验证任务开始前已有脏文件不会进入任务 Diff。"""

        from codex_task_review.git_snapshot import GitRepository
        from codex_task_review.git_snapshot import GitSnapshotter

        with temporary_git_repository() as repo_root:
            dirty_path = repo_root / "preexisting.txt"
            dirty_path.write_text(
                "before task\n",
                encoding="utf-8",
            )
            snapshotter = GitSnapshotter(
                GitRepository.find(repo_root),
            )
            base = snapshotter.capture()
            dirty_path.write_text(
                "changed during task\n",
                encoding="utf-8",
            )
            final = snapshotter.capture()

            diff = snapshotter.diff(
                base.tree_id,
                final.tree_id,
            )

        self.assertEqual(
            [item.path for item in diff.files],
            ["preexisting.txt"],
        )
        self.assertIn("changed during task", diff.patch)
        self.assertNotIn("baseline.txt", diff.patch)

    def test_new_modified_deleted_staged_and_unstaged_files_are_included(
        self,
    ):
        """验证暂存、未暂存、新增、修改和删除均写入快照。"""

        from codex_task_review.git_snapshot import GitRepository
        from codex_task_review.git_snapshot import GitSnapshotter

        with temporary_git_repository() as repo_root:
            deleted_path = repo_root / "deleted.txt"
            deleted_path.write_text(
                "delete me\n",
                encoding="utf-8",
            )
            subprocess.run(
                [
                    "git",
                    "add",
                    "deleted.txt",
                ],
                cwd=repo_root,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                [
                    "git",
                    "commit",
                    "-m",
                    "add deletion fixture",
                ],
                cwd=repo_root,
                check=True,
                capture_output=True,
            )
            snapshotter = GitSnapshotter(
                GitRepository.find(repo_root),
            )
            base = snapshotter.capture()

            staged_path = repo_root / "staged.txt"
            staged_path.write_text(
                "staged change\n",
                encoding="utf-8",
            )
            subprocess.run(
                [
                    "git",
                    "add",
                    "staged.txt",
                ],
                cwd=repo_root,
                check=True,
                capture_output=True,
            )

            unstaged_path = repo_root / "baseline.txt"
            unstaged_path.write_text(
                "unstaged change\n",
                encoding="utf-8",
            )
            deleted_path.unlink()

            final = snapshotter.capture()
            diff = snapshotter.diff(
                base.tree_id,
                final.tree_id,
            )

        statuses = {
            item.path: item.status
            for item in diff.files
        }
        self.assertEqual(
            statuses["staged.txt"],
            "A",
        )
        self.assertEqual(
            statuses["baseline.txt"],
            "M",
        )
        self.assertEqual(
            statuses["deleted.txt"],
            "D",
        )
        self.assertIn("staged change", diff.patch)
        self.assertIn("unstaged change", diff.patch)

    def test_rename_is_reported_with_similarity_detection(
        self,
    ):
        """验证相同内容的路径移动被识别为重命名。"""

        from codex_task_review.git_snapshot import GitRepository
        from codex_task_review.git_snapshot import GitSnapshotter

        with temporary_git_repository() as repo_root:
            old_path = repo_root / "old-name.txt"
            old_path.write_text(
                "rename content\n",
                encoding="utf-8",
            )
            subprocess.run(
                [
                    "git",
                    "add",
                    "old-name.txt",
                ],
                cwd=repo_root,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                [
                    "git",
                    "commit",
                    "-m",
                    "add rename fixture",
                ],
                cwd=repo_root,
                check=True,
                capture_output=True,
            )

            snapshotter = GitSnapshotter(
                GitRepository.find(repo_root),
            )
            base = snapshotter.capture()
            old_path.rename(repo_root / "new-name.txt")
            final = snapshotter.capture()
            diff = snapshotter.diff(
                base.tree_id,
                final.tree_id,
            )

        rename = diff.files[0]
        self.assertEqual(
            rename.status,
            "R100",
        )
        self.assertEqual(
            rename.old_path,
            "old-name.txt",
        )
        self.assertEqual(
            rename.path,
            "new-name.txt",
        )

    def test_snapshot_does_not_change_real_index(
        self,
    ):
        """验证快照不会触碰仓库真实 Git Index。"""

        from codex_task_review.git_snapshot import GitRepository
        from codex_task_review.git_snapshot import GitSnapshotter

        with temporary_git_repository() as repo_root:
            staged_path = repo_root / "staged.txt"
            staged_path.write_text(
                "staged\n",
                encoding="utf-8",
            )
            subprocess.run(
                [
                    "git",
                    "add",
                    "staged.txt",
                ],
                cwd=repo_root,
                check=True,
                capture_output=True,
            )
            index_path = Path(
                subprocess.run(
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
            )
            if not index_path.is_absolute():
                index_path = repo_root / index_path

            index_before = index_path.read_bytes()
            snapshotter = GitSnapshotter(
                GitRepository.find(repo_root),
            )
            snapshotter.capture()
            index_after = index_path.read_bytes()

        self.assertEqual(
            index_before,
            index_after,
        )

    def test_chinese_and_space_path_is_supported(
        self,
    ):
        """验证中文与空格文件名可被 Diff 正确读取。"""

        from codex_task_review.git_snapshot import GitRepository
        from codex_task_review.git_snapshot import GitSnapshotter

        with temporary_git_repository() as repo_root:
            snapshotter = GitSnapshotter(
                GitRepository.find(repo_root),
            )
            base = snapshotter.capture()
            target_path = repo_root / "中文 文件.txt"
            target_path.write_text(
                "中文内容\n",
                encoding="utf-8",
            )
            final = snapshotter.capture()
            diff = snapshotter.diff(
                base.tree_id,
                final.tree_id,
            )

        self.assertEqual(
            diff.files[0].path,
            "中文 文件.txt",
        )
        self.assertIn(
            "中文内容",
            diff.patch,
        )

    def test_diff_patch_preserves_non_utf8_bytes_for_reviewer_stdin(
        self,
    ):
        """验证补丁文本可无损编码回原始 Git Diff 字节。"""

        from codex_task_review.git_snapshot import GitRepository
        from codex_task_review.git_snapshot import GitSnapshotter

        with temporary_git_repository() as repo_root:
            repository = GitRepository.find(repo_root)
            snapshotter = GitSnapshotter(repository)
            base = snapshotter.capture()
            (repo_root / "invalid-utf8.txt").write_bytes(
                b"invalid byte: \xff\n",
            )
            final = snapshotter.capture()
            diff = snapshotter.diff(
                base.tree_id,
                final.tree_id,
            )
            raw_diff = repository.run_bytes(
                [
                    "diff",
                    "--binary",
                    "--no-ext-diff",
                    "--no-color",
                    "-M",
                    base.tree_id,
                    final.tree_id,
                ]
            )

        self.assertEqual(
            diff.patch.encode(
                "utf-8",
                errors="surrogateescape",
            ),
            raw_diff,
        )

    def test_repository_without_head_returns_explicit_error(
        self,
    ):
        """验证没有初始提交时快照返回明确错误。"""

        from codex_task_review.git_snapshot import GitRepository
        from codex_task_review.git_snapshot import GitRepositoryError
        from codex_task_review.git_snapshot import GitSnapshotter

        with temporary_git_repository() as repo_root:
            empty_repo = repo_root / "empty repository"
            empty_repo.mkdir()
            subprocess.run(
                [
                    "git",
                    "init",
                    "--initial-branch=main",
                ],
                cwd=empty_repo,
                check=True,
                capture_output=True,
            )
            snapshotter = GitSnapshotter(
                GitRepository.find(empty_repo),
            )

            with self.assertRaisesRegex(
                GitRepositoryError,
                "HEAD",
            ):
                snapshotter.capture()

    @unittest.skipUnless(
        os.name == "nt",
        "Windows 路径长度诊断仅适用于 Windows",
    )
    def test_export_error_explains_windows_max_path_limit(
        self,
    ):
        """验证超长 Windows 导出路径返回可操作的错误说明。"""

        from codex_task_review.git_snapshot import GitRepository
        from codex_task_review.git_snapshot import GitRepositoryError
        from codex_task_review.git_snapshot import GitSnapshotter
        from codex_task_review.git_snapshot import WINDOWS_MAX_PATH

        with temporary_git_repository(
            Path(tempfile.gettempdir()),
        ) as repo_root:
            snapshotter = GitSnapshotter(
                GitRepository.find(repo_root),
            )
            snapshot = snapshotter.capture()
            long_path = "C:\\" + ("x" * (WINDOWS_MAX_PATH - len("C:\\")))
            expected_path_length = len(long_path) + 1

            with patch(
                "pathlib.Path.write_bytes",
                side_effect=FileNotFoundError(
                    2,
                    "No such file or directory",
                    long_path,
                ),
            ):
                with self.assertRaisesRegex(
                    GitRepositoryError,
                    "MAX_PATH",
                ) as error_context:
                    snapshotter.export_tree(
                        snapshot.tree_id,
                        repo_root.parent / "long-path-export",
                    )

        self.assertIn(
            str(expected_path_length),
            str(error_context.exception),
        )
        self.assertIn(
            long_path,
            str(error_context.exception),
        )


if __name__ == "__main__":
    unittest.main()
