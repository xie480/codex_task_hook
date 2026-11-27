"""只读 Reviewer 隔离、输入边界和失败安全测试。"""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codex_task_review.config import ReviewConfig
from codex_task_review.models import DiffResult
from tests.git_helpers import temporary_git_repository
from tests.temp_utils import temporary_workspace


def prepare_review_data(
    repo_root: Path,
) -> tuple[Path, str, DiffResult]:
    """在测试仓库中准备 BASE、FINAL 和任务 Diff。

    Args:
        repo_root: 已初始化并含有基线提交的临时仓库目录。

    Returns:
        原仓库根路径、FINAL Tree ID 和新增文件对应的 Diff。
    """

    from codex_task_review.git_snapshot import GitRepository
    from codex_task_review.git_snapshot import GitSnapshotter

    repository = GitRepository.find(repo_root)
    snapshotter = GitSnapshotter(repository)
    base_tree = snapshotter.capture().tree_id
    (repo_root / "change.py").write_text(
        "def changed():\n    return 1\n",
        encoding="utf-8",
    )
    final_tree = snapshotter.capture().tree_id
    diff = snapshotter.diff(
        base_tree,
        final_tree,
    )

    return repository, final_tree, diff


class ReviewerTests(unittest.TestCase):
    """验证 Reviewer 只读取隔离快照并对所有失败安全降级。"""

    def test_runs_read_only_review_in_final_snapshot_workspace(
        self,
    ):
        """验证 CLI 只收到完整任务 Diff 且运行目录不是用户仓库。"""

        from codex_task_review.reviewer import ReviewRunner

        with temporary_workspace() as workspace:
            with temporary_git_repository() as repo_root:
                (repo_root / ".gitignore").write_text(
                    "review-hidden.txt\n",
                    encoding="utf-8",
                )
                (repo_root / "review-hidden.txt").write_text(
                    "tracked and ignored\n",
                    encoding="utf-8",
                )
                subprocess.run(
                    [
                        "git",
                        "add",
                        "-f",
                        ".gitignore",
                        "review-hidden.txt",
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
                        "add ignored tracked fixture",
                    ],
                    cwd=repo_root,
                    check=True,
                    capture_output=True,
                )
                repository, final_tree, diff = prepare_review_data(
                    repo_root,
                )
                temporary_root = workspace / "review-workspaces"
                calls: list[dict[str, object]] = []
                review_config = ReviewConfig.defaults()
                review_config.review_model = "gpt-5-codex"
                review_config.review_reasoning_effort = "high"

                def fake_process(
                    command,
                    *,
                    cwd,
                    input,
                    capture_output,
                    timeout,
                    env,
                    check,
                ):
                    calls.append(
                        {
                            "command": command,
                            "cwd": Path(cwd),
                            "input": input,
                            "capture_output": capture_output,
                            "timeout": timeout,
                            "env": env,
                            "check": check,
                            "files": {
                                path.name
                                for path in Path(cwd).iterdir()
                            },
                            "tracked_files": subprocess.run(
                                [
                                    "git",
                                    "ls-tree",
                                    "-r",
                                    "--name-only",
                                    "HEAD",
                                ],
                                cwd=cwd,
                                env=env,
                                check=True,
                                capture_output=True,
                                text=True,
                                encoding="utf-8",
                            ).stdout.splitlines(),
                        }
                    )

                    return subprocess.CompletedProcess(
                        command,
                        0,
                        b"No findings",
                        b"",
                    )

                runner = ReviewRunner(
                    temporary_root,
                    process_runner=fake_process,
                    codex_path="codex-test",
                )
                original_status = subprocess.run(
                    [
                        "git",
                        "status",
                        "--porcelain",
                    ],
                    cwd=repo_root,
                    check=True,
                    capture_output=True,
                ).stdout
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

                original_index = index_path.read_bytes()
                original_change = (repo_root / "change.py").read_bytes()

                result = runner.run(
                    repository.root,
                    final_tree,
                    diff,
                    "add a feature",
                    review_config,
                )

                final_status = subprocess.run(
                    [
                        "git",
                        "status",
                        "--porcelain",
                    ],
                    cwd=repo_root,
                    check=True,
                    capture_output=True,
                ).stdout
                final_index = index_path.read_bytes()
                final_change = (repo_root / "change.py").read_bytes()
                review_workspace_entries = list(
                    temporary_root.iterdir(),
                )

        self.assertEqual(
            result.status,
            "completed",
            result.error,
        )
        self.assertEqual(
            result.raw_output,
            "No findings",
        )
        self.assertEqual(
            len(calls),
            1,
        )
        invocation = calls[0]
        command = invocation["command"]
        self.assertEqual(
            command[-2:],
            [
                "review",
                "-",
            ],
        )
        sandbox_position = command.index(
            "--sandbox",
        )
        self.assertEqual(
            command[sandbox_position + 1],
            "read-only",
        )
        self.assertEqual(
            command[1:5],
            [
                "-c",
                'review_model="gpt-5-codex"',
                "-c",
                'model_reasoning_effort="high"',
            ],
        )
        self.assertNotEqual(
            invocation["cwd"],
            repo_root.resolve(),
        )
        self.assertEqual(
            invocation["cwd"].parent.parent,
            temporary_root.resolve(),
        )
        self.assertIn(
            "change.py",
            invocation["files"],
        )
        self.assertIn(
            "review-hidden.txt",
            invocation["files"],
        )
        self.assertIn(
            "review-hidden.txt",
            invocation["tracked_files"],
        )
        self.assertIn(
            diff.patch.encode(
                "utf-8",
                errors="surrogateescape",
            ),
            invocation["input"],
        )
        self.assertEqual(
            invocation["timeout"],
            ReviewConfig.defaults().review_timeout,
        )
        self.assertEqual(
            invocation["env"]["CODEX_TASK_REVIEW_ACTIVE"],
            "1",
        )
        self.assertFalse(
            invocation["check"],
        )
        self.assertEqual(
            original_status,
            final_status,
        )
        self.assertEqual(
            original_index,
            final_index,
        )
        self.assertEqual(
            final_change,
            original_change,
        )
        self.assertEqual(
            review_workspace_entries,
            [],
        )

    def test_default_review_does_not_add_cli_config_overrides(
        self,
    ):
        """验证默认配置不向 Codex CLI 追加模型或推理强度覆盖。"""

        from codex_task_review.reviewer import ReviewRunner

        with temporary_workspace() as workspace:
            with temporary_git_repository() as repo_root:
                repository, final_tree, diff = prepare_review_data(
                    repo_root,
                )
                commands: list[list[str]] = []

                def fake_process(command, **kwargs):
                    commands.append(command)
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        b"No findings",
                        b"",
                    )

                result = ReviewRunner(
                    workspace / "review-workspaces",
                    process_runner=fake_process,
                    codex_path="codex-test",
                ).run(
                    repository.root,
                    final_tree,
                    diff,
                    "add a feature",
                    ReviewConfig.defaults(),
                )

        self.assertEqual(result.status, "completed")
        self.assertEqual(len(commands), 1)
        self.assertNotIn("-c", commands[0])

    def test_missing_codex_returns_failed_result_without_launching(
        self,
    ):
        """验证 CLI 不存在时返回失败结果而不抛出到 Hook。"""

        from codex_task_review.git_snapshot import GitRepository
        from codex_task_review.git_snapshot import GitSnapshotter
        from codex_task_review.reviewer import ReviewRunner

        with temporary_workspace() as workspace:
            with temporary_git_repository() as repo_root:
                repository, final_tree, diff = prepare_review_data(
                    repo_root,
                )
                calls: list[object] = []
                runner = ReviewRunner(
                    workspace / "review-workspaces",
                    process_runner=lambda *args, **kwargs: calls.append(args),
                )

                with patch(
                    "codex_task_review.reviewer.shutil.which",
                    return_value=None,
                ):
                    result = runner.run(
                        repository,
                        final_tree,
                        diff,
                        "review task",
                        ReviewConfig.defaults(),
                    )

        self.assertEqual(
            result.status,
            "failed",
        )
        self.assertIn(
            "codex",
            result.error.casefold(),
        )
        self.assertEqual(
            calls,
            [],
        )

    def test_review_timeout_returns_failed_result_and_cleans_workspace(
        self,
    ):
        """验证 CLI 超时转换成失败结果并回收临时目录。"""

        from codex_task_review.reviewer import ReviewRunner

        with temporary_workspace() as workspace:
            with temporary_git_repository() as repo_root:
                repository, final_tree, diff = prepare_review_data(
                    repo_root,
                )
                temporary_root = workspace / "review-workspaces"

                def timeout_process(
                    command,
                    **kwargs,
                ):
                    raise subprocess.TimeoutExpired(
                        command,
                        kwargs["timeout"],
                        output=b"partial",
                    )

                runner = ReviewRunner(
                    temporary_root,
                    process_runner=timeout_process,
                    codex_path="codex-test",
                )

                result = runner.run(
                    repository.root,
                    final_tree,
                    diff,
                    "add a feature",
                    ReviewConfig.defaults(),
                )
                review_workspace_entries = list(
                    temporary_root.iterdir(),
                )

        self.assertEqual(
            result.status,
            "failed",
        )
        self.assertEqual(
            result.raw_output,
            "partial",
        )
        self.assertIn(
            "超时",
            result.error,
        )
        self.assertEqual(
            review_workspace_entries,
            [],
        )

    def test_nonzero_exit_returns_failed_result_with_cli_error(
        self,
    ):
        """验证 CLI 非零退出码保留 stderr 作为失败原因。"""

        from codex_task_review.reviewer import ReviewRunner

        with temporary_workspace() as workspace:
            with temporary_git_repository() as repo_root:
                repository, final_tree, diff = prepare_review_data(
                    repo_root,
                )
                runner = ReviewRunner(
                    workspace / "review-workspaces",
                    process_runner=lambda command, **kwargs: (
                        subprocess.CompletedProcess(
                            command,
                            7,
                            b"partial output",
                            b"authentication failed",
                        )
                    ),
                    codex_path="codex-test",
                )

                result = runner.run(
                    repository.root,
                    final_tree,
                    diff,
                    "add a feature",
                    ReviewConfig.defaults(),
                )

        self.assertEqual(
            result.status,
            "failed",
        )
        self.assertEqual(
            result.raw_output,
            "partial output",
        )
        self.assertIn(
            "authentication failed",
            result.error,
        )

    def test_oversized_diff_is_rejected_before_workspace_or_cli(
        self,
    ):
        """验证超过配置上限的 Diff 不写临时文件也不启动 CLI。"""

        from codex_task_review.reviewer import ReviewRunner

        with temporary_workspace() as workspace:
            with temporary_git_repository() as repo_root:
                temporary_root = workspace / "review-workspaces"
                calls: list[object] = []
                runner = ReviewRunner(
                    temporary_root,
                    process_runner=lambda *args, **kwargs: calls.append(args),
                    codex_path="codex-test",
                )
                config = ReviewConfig.defaults()
                config.max_diff_bytes = 4
                oversized_diff = DiffResult(
                    base_tree="a" * 40,
                    final_tree="b" * 40,
                    patch="12345",
                    files=[],
                    additions=0,
                    deletions=0,
                )

                result = runner.run(
                    repo_root,
                    "b" * 40,
                    oversized_diff,
                    "review task",
                    config,
                )

        self.assertEqual(
            result.status,
            "failed",
        )
        self.assertIn(
            "Diff",
            result.error,
        )
        self.assertEqual(
            calls,
            [],
        )
        self.assertFalse(
            temporary_root.exists(),
        )

    def test_recursive_environment_skips_without_launching_cli(
        self,
    ):
        """验证递归标记存在时 Reviewer 立即安全跳过。"""

        from codex_task_review.git_snapshot import GitRepository
        from codex_task_review.git_snapshot import GitSnapshotter
        from codex_task_review.reviewer import ReviewRunner

        with temporary_workspace() as workspace:
            with temporary_git_repository() as repo_root:
                snapshotter = GitSnapshotter(
                    GitRepository.find(repo_root),
                )
                snapshot = snapshotter.capture()
                calls: list[object] = []
                runner = ReviewRunner(
                    workspace / "review-workspaces",
                    process_runner=lambda *args, **kwargs: calls.append(args),
                    codex_path="codex-test",
                )

                previous_marker = os.environ.get(
                    "CODEX_TASK_REVIEW_ACTIVE",
                )
                os.environ["CODEX_TASK_REVIEW_ACTIVE"] = "1"

                try:
                    result = runner.run(
                        repo_root,
                        snapshot.tree_id,
                        snapshotter.diff(
                            snapshot.tree_id,
                            snapshot.tree_id,
                        ),
                        "review task",
                        ReviewConfig.defaults(),
                    )
                finally:
                    if previous_marker is None:
                        os.environ.pop(
                            "CODEX_TASK_REVIEW_ACTIVE",
                            None,
                        )
                    else:
                        os.environ["CODEX_TASK_REVIEW_ACTIVE"] = previous_marker

        self.assertEqual(
            result.status,
            "skipped",
        )
        self.assertIn(
            "递归",
            result.error,
        )
        self.assertEqual(
            calls,
            [],
        )

    def test_review_exports_deep_tree_file_with_short_workspace_path(
        self,
    ):
        """验证默认 Windows 路径限制下也能导出深层仓库文件。"""

        from codex_task_review.git_snapshot import GitRepository
        from codex_task_review.git_snapshot import GitSnapshotter
        from codex_task_review.git_snapshot import WINDOWS_MAX_PATH
        from codex_task_review.reviewer import ReviewRunner

        relative_path = Path(
            "aiep/aiep_k12/server/agents/new/skills/releases/"
            "2ca20bb34dcf7a68bfcf4b261f3b9f5d7c9bbd34473065ed96f863b2591b7f53/"
            "package/examples/arcade-cabinet/arcade-cabinet.css"
        )
        temporary_root = Path(
            tempfile.gettempdir(),
        )
        observed_files: list[tuple[bool, int, bytes]] = []

        with temporary_git_repository(temporary_root) as repo_root:
            deep_file = repo_root / relative_path
            deep_file.parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            deep_file.write_bytes(
                b".arcade-cabinet { color: blue; }\n",
            )
            subprocess.run(
                [
                    "git",
                    "add",
                    "--",
                    relative_path.as_posix(),
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
                    "add deep path fixture",
                ],
                cwd=repo_root,
                check=True,
                capture_output=True,
            )

            snapshotter = GitSnapshotter(
                GitRepository.find(repo_root),
            )
            base_snapshot = snapshotter.capture()
            (repo_root / "baseline.txt").write_text(
                "review task change\n",
                encoding="utf-8",
            )
            final_snapshot = snapshotter.capture()
            diff = snapshotter.diff(
                base_snapshot.tree_id,
                final_snapshot.tree_id,
            )

            def fake_process(
                command,
                *,
                cwd,
                input,
                capture_output,
                timeout,
                env,
                check,
            ):
                exported_file = Path(cwd) / relative_path
                observed_files.append(
                    (
                        exported_file.is_file(),
                        len(str(exported_file)) + 1,
                        exported_file.read_bytes(),
                    )
                )

                return subprocess.CompletedProcess(
                    command,
                    0,
                    b"No findings",
                    b"",
                )

            result = ReviewRunner(
                temporary_root,
                process_runner=fake_process,
                codex_path="codex-test",
            ).run(
                repo_root,
                final_snapshot.tree_id,
                diff,
                "review deep path fixture",
                ReviewConfig.defaults(),
            )

        self.assertEqual(
            result.status,
            "completed",
            result.error,
        )
        self.assertEqual(
            len(observed_files),
            1,
        )
        self.assertTrue(
            observed_files[0][0],
        )
        self.assertLessEqual(
            observed_files[0][1],
            WINDOWS_MAX_PATH,
        )
        self.assertIn(
            b".arcade-cabinet { color: blue; }",
            observed_files[0][2],
        )


if __name__ == "__main__":
    unittest.main()
