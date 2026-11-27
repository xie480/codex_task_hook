"""通过真实 Hook 进程验证任务快照、审查和报告完整链路。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from tests.git_helpers import temporary_git_repository
from tests.temp_utils import temporary_workspace


PROJECT_ROOT = Path(__file__).resolve().parents[1]
HOOK_ENTRY = PROJECT_ROOT / "hooks" / "task_review.py"
FAKE_REVIEWER_OUTPUT = "No findings"


class HookIntegrationTests(unittest.TestCase):
    """验证 Codex Hook 从任务开始到 Markdown 报告的端到端行为。"""

    def test_each_turn_report_contains_only_changes_since_its_snapshot(
        self,
    ) -> None:
        """确认脏文件隔离、暂存状态只读及报告在 Diff 之后生成。

        Args:
            self: 当前集成测试实例。

        Returns:
            无；断言 Hook 输出、报告内容及 Git Index 保持符合契约。
        """

        with temporary_workspace() as workspace:
            fake_bin = self._install_fake_codex(
                workspace,
            )
            data_root = workspace / "plugin-data"

            with temporary_git_repository() as repo_root:
                (repo_root / "baseline.txt").write_text(
                    "pre-existing dirty change\n",
                    encoding="utf-8",
                )
                dirty_status = self._run_git(
                    repo_root,
                    [
                        "status",
                        "--short",
                    ],
                ).decode(
                    "utf-8",
                    errors="replace",
                )
                self.assertIn(
                    "baseline.txt",
                    dirty_status,
                )

                first_start = self._invoke_hook(
                    "UserPromptSubmit",
                    repo_root,
                    data_root,
                    fake_bin,
                    "integration-session",
                    "turn-one",
                    "Add an authentication validator.",
                )
                self.assertIn(
                    "snapshot_recorded",
                    first_start["systemMessage"],
                )
                task_one = repo_root / "task_one.py"
                task_one.write_text(
                    "def validate_token(value):\n"
                    "    return bool(value)\n",
                    encoding="utf-8",
                )
                self._run_git(
                    repo_root,
                    [
                        "add",
                        "--",
                        "task_one.py",
                    ],
                )
                staged_files = self._run_git(
                    repo_root,
                    [
                        "diff",
                        "--cached",
                        "--name-only",
                    ],
                ).decode(
                    "utf-8",
                    errors="replace",
                )
                self.assertEqual(
                    staged_files.strip(),
                    "task_one.py",
                )
                first_index = (repo_root / ".git" / "index").read_bytes()
                first_stop = self._invoke_hook(
                    "Stop",
                    repo_root,
                    data_root,
                    fake_bin,
                    "integration-session",
                    "turn-one",
                    "Add an authentication validator.",
                )
                self.assertIn(
                    "review_completed",
                    first_stop["systemMessage"],
                )
                self.assertEqual(
                    first_stop["decision"],
                    "block",
                )
                self.assertIn(
                    "未发现可操作问题",
                    first_stop["reason"],
                )
                self.assertEqual(
                    first_index,
                    (repo_root / ".git" / "index").read_bytes(),
                )

                report_root = repo_root / ".codex" / "reviews"
                first_reports = list(
                    report_root.glob("*.md"),
                )
                self.assertEqual(
                    len(first_reports),
                    1,
                )
                first_report = first_reports[0].read_text(
                    encoding="utf-8",
                )
                self.assertIn(
                    "task_one.py",
                    first_report,
                )
                self.assertNotIn(
                    "baseline.txt",
                    first_report,
                )
                self.assertNotIn(
                    "code-review-",
                    first_report,
                )
                self.assertIn(
                    FAKE_REVIEWER_OUTPUT,
                    first_report,
                )
                self.assertIn(
                    str(first_reports[0]),
                    first_stop["reason"],
                )

                continuation_stop = self._invoke_hook(
                    "Stop",
                    repo_root,
                    data_root,
                    fake_bin,
                    "integration-session",
                    "turn-one",
                    "Add an authentication validator.",
                    stop_hook_active=True,
                )
                self.assertNotIn(
                    "decision",
                    continuation_stop,
                )
                self.assertIn(
                    "stop_hook_active",
                    continuation_stop["systemMessage"],
                )
                self.assertEqual(
                    len(list(report_root.glob("*.md"))),
                    1,
                )

                second_start = self._invoke_hook(
                    "UserPromptSubmit",
                    repo_root,
                    data_root,
                    fake_bin,
                    "integration-session",
                    "turn-two",
                    "Implement cache invalidation.",
                )
                self.assertIn(
                    "snapshot_recorded",
                    second_start["systemMessage"],
                )
                task_two = repo_root / "task_two.py"
                task_two.write_text(
                    "def invalidate_cache(cache, key):\n"
                    "    cache.pop(key, None)\n",
                    encoding="utf-8",
                )
                unstaged_status = self._run_git(
                    repo_root,
                    [
                        "status",
                        "--short",
                    ],
                ).decode(
                    "utf-8",
                    errors="replace",
                )
                self.assertIn(
                    "?? task_two.py",
                    unstaged_status,
                )
                staged_files = self._run_git(
                    repo_root,
                    [
                        "diff",
                        "--cached",
                        "--name-only",
                    ],
                ).decode(
                    "utf-8",
                    errors="replace",
                )
                self.assertNotIn(
                    "task_two.py",
                    staged_files,
                )
                second_index = (repo_root / ".git" / "index").read_bytes()
                second_stop = self._invoke_hook(
                    "Stop",
                    repo_root,
                    data_root,
                    fake_bin,
                    "integration-session",
                    "turn-two",
                    "Implement cache invalidation.",
                )
                self.assertIn(
                    "review_completed",
                    second_stop["systemMessage"],
                )
                self.assertEqual(
                    second_index,
                    (repo_root / ".git" / "index").read_bytes(),
                )

                reports = list(
                    report_root.glob("*.md"),
                )
                self.assertEqual(
                    len(reports),
                    2,
                )
                report_contents = [
                    report.read_text(
                        encoding="utf-8",
                    )
                    for report in reports
                ]
                second_report = next(
                    content
                    for content in report_contents
                    if "`turn-two`" in content
                )
                self.assertIn(
                    "task_two.py",
                    second_report,
                )
                self.assertNotIn(
                    "task_one.py",
                    second_report,
                )
                self.assertNotIn(
                    "baseline.txt",
                    second_report,
                )
                self.assertNotIn(
                    "code-review-",
                    second_report,
                )
                self.assertIn(
                    FAKE_REVIEWER_OUTPUT,
                    second_report,
                )

    def _install_fake_codex(
        self,
        workspace: Path,
    ) -> Path:
        """创建通过 PATH 调用的跨平台固定输出 Reviewer。

        Args:
            self: 当前集成测试实例。
            workspace: 当前测试独占的临时工作区。

        Returns:
            包含 `codex` 假命令的独立目录。
        """

        fake_bin = workspace / "fake-codex-bin"
        fake_bin.mkdir()
        fake_script = fake_bin / "fake_codex.py"
        fake_script.write_text(
            "import sys\n"
            "sys.stdin.buffer.read()\n"
            f"sys.stdout.write({FAKE_REVIEWER_OUTPUT!r} + '\\n')\n",
            encoding="utf-8",
        )

        if os.name == "nt":
            codex_command = fake_bin / "codex.cmd"
            codex_command.write_text(
                "@echo off\r\n"
                "\"%CODEX_TASK_REVIEW_TEST_PYTHON%\" "
                "\"%~dp0fake_codex.py\"\r\n"
                "exit /b %ERRORLEVEL%\r\n",
                encoding="ascii",
            )
        else:
            codex_command = fake_bin / "codex"
            codex_command.write_text(
                "#!/usr/bin/env python3\n"
                "import runpy\n"
                f"runpy.run_path({str(fake_script)!r}, run_name='__main__')\n",
                encoding="utf-8",
            )
            codex_command.chmod(
                0o755,
            )

        return fake_bin

    def _invoke_hook(
        self,
        event_name: str,
        repo_root: Path,
        data_root: Path,
        fake_bin: Path,
        session_id: str,
        turn_id: str,
        prompt: str,
        stop_hook_active: bool = False,
    ) -> dict[str, object]:
        """以 Codex 的 stdin 和插件环境变量调用实际 Hook 入口。

        Args:
            self: 当前集成测试实例。
            event_name: `UserPromptSubmit` 或 `Stop` 生命周期名称。
            repo_root: Hook 应处理的临时 Git 仓库根目录。
            data_root: 插件任务状态目录。
            fake_bin: 含离线 Reviewer 命令的 PATH 前置目录。
            session_id: 本轮 Codex 会话身份。
            turn_id: 本轮 Codex 任务身份。
            prompt: 供任务分类与报告使用的原始请求。

        Returns:
            Hook stdout 解码得到的 JSON 对象。
        """

        payload: dict[str, object] = {
            "hook_event_name": event_name,
            "session_id": session_id,
            "turn_id": turn_id,
            "cwd": str(repo_root),
            "prompt": prompt,
            "stop_hook_active": stop_hook_active,
            "last_assistant_message": "Task finished.",
        }
        environment = os.environ.copy()
        environment["PLUGIN_ROOT"] = str(PROJECT_ROOT)
        environment["PLUGIN_DATA"] = str(data_root)
        environment["CODEX_TASK_REVIEW_TEST_PYTHON"] = sys.executable
        environment.pop(
            "CODEX_TASK_REVIEW_ACTIVE",
            None,
        )
        current_path = environment.get(
            "PATH",
            "",
        )
        environment["PATH"] = os.pathsep.join(
            value
            for value in (
                str(fake_bin),
                current_path,
            )
            if value
        )
        process = subprocess.run(
            [
                sys.executable,
                str(HOOK_ENTRY),
            ],
            cwd=repo_root,
            input=json.dumps(
                payload,
                ensure_ascii=False,
            ).encode("utf-8"),
            capture_output=True,
            env=environment,
            check=False,
            timeout=30,
        )
        self.assertEqual(
            process.returncode,
            0,
            process.stderr.decode(
                "utf-8",
                errors="replace",
            ),
        )

        return json.loads(
            process.stdout.decode(
                "utf-8",
            )
        )

    def _run_git(
        self,
        repo_root: Path,
        arguments: list[str],
    ) -> bytes:
        """在隔离的临时仓库中执行 Git 命令并检查退出状态。

        Args:
            self: 当前集成测试实例。
            repo_root: 临时 Git 仓库根目录。
            arguments: Git 可执行文件后的参数。

        Returns:
            Git 命令的标准输出字节。
        """

        process = subprocess.run(
            [
                "git",
                *arguments,
            ],
            cwd=repo_root,
            capture_output=True,
            check=False,
        )
        self.assertEqual(
            process.returncode,
            0,
            process.stderr.decode(
                "utf-8",
                errors="replace",
            ),
        )

        return process.stdout


if __name__ == "__main__":
    unittest.main()
