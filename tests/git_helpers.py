"""创建不接触用户仓库的临时 Git 集成测试夹具。"""

from __future__ import annotations

import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from tests.temp_utils import temporary_workspace


@contextmanager
def temporary_git_repository(
) -> Iterator[Path]:
    """创建含有初始提交的临时 Git 仓库并在测试后回收。

    Returns:
        上下文管理器，进入时返回临时仓库根目录。

    Raises:
        subprocess.CalledProcessError: Git 初始化或提交命令失败时抛出。
    """

    with temporary_workspace() as workspace:
        repo_root = workspace / "临时 Git 仓库"
        repo_root.mkdir()

        commands = [
            [
                "git",
                "init",
                "--initial-branch=main",
            ],
            [
                "git",
                "config",
                "user.name",
                "Codex Task Review Tests",
            ],
            [
                "git",
                "config",
                "user.email",
                "codex-task-review@example.invalid",
            ],
        ]

        for command in commands:
            subprocess.run(
                command,
                cwd=repo_root,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )

        baseline_file = repo_root / "baseline.txt"
        baseline_file.write_text(
            "baseline\n",
            encoding="utf-8",
        )
        subprocess.run(
            [
                "git",
                "add",
                "baseline.txt",
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
                "baseline",
            ],
            cwd=repo_root,
            check=True,
            capture_output=True,
        )

        yield repo_root
