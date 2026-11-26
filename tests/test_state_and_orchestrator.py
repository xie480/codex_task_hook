"""任务状态隔离与 Hook 生命周期编排测试。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from codex_task_review.hook_io import HookInput
from codex_task_review.models import TaskIdentity
from codex_task_review.models import TaskState
from tests.git_helpers import temporary_git_repository
from tests.temp_utils import temporary_workspace


def make_task_state(
    session_id: str,
    turn_id: str,
    repo_root: Path,
    prompt: str,
) -> TaskState:
    """构造带固定测试时间的任务状态。

    Args:
        session_id: 测试会话标识。
        turn_id: 测试轮次标识。
        repo_root: 临时 Git 仓库根目录。
        prompt: 任务描述。

    Returns:
        用于状态存储测试的任务模型。
    """

    return TaskState(
        identity=TaskIdentity(
            session_id=session_id,
            turn_id=turn_id,
        ),
        repo_root=repo_root,
        base_tree="a" * 40,
        prompt=prompt,
        created_at="2026-11-26T00:00:00+00:00",
    )


class StateAndOrchestratorTests(unittest.TestCase):
    """验证每轮任务状态独立，Hook 故障时安全放行。"""

    def test_different_sessions_and_turns_have_isolated_state(
        self,
    ):
        """验证会话或轮次不同的任务不会覆盖彼此状态。"""

        from codex_task_review.state import TaskStateStore

        with temporary_workspace() as workspace:
            repo_root = workspace / "repo"
            repo_root.mkdir()
            store = TaskStateStore(
                workspace / "plugin-data",
            )
            states = [
                make_task_state(
                    "session-a",
                    "turn-1",
                    repo_root,
                    "first task",
                ),
                make_task_state(
                    "session-a",
                    "turn-2",
                    repo_root,
                    "second turn",
                ),
                make_task_state(
                    "session-b",
                    "turn-1",
                    repo_root,
                    "second session",
                ),
            ]

            for state in states:
                store.save(state)

            loaded = [
                store.load(state.identity)
                for state in states
            ]

        self.assertEqual(
            [state.prompt for state in loaded if state is not None],
            [
                "first task",
                "second turn",
                "second session",
            ],
        )

    def test_parallel_state_writes_do_not_overwrite_other_tasks(
        self,
    ):
        """验证并行写入使用独立文件且任务状态均可读取。"""

        from codex_task_review.state import TaskStateStore

        with temporary_workspace() as workspace:
            repo_root = workspace / "repo"
            repo_root.mkdir()
            store = TaskStateStore(
                workspace / "plugin-data",
            )
            states = [
                make_task_state(
                    "session-parallel",
                    f"turn-{index}",
                    repo_root,
                    f"prompt-{index}",
                )
                for index in range(8)
            ]

            with ThreadPoolExecutor(
                max_workers=4,
            ) as executor:
                list(
                    executor.map(
                        store.save,
                        states,
                    )
                )

            loaded = [
                store.load(state.identity)
                for state in states
            ]

        self.assertEqual(
            [state.prompt for state in loaded if state is not None],
            [
                state.prompt
                for state in states
            ],
        )

    def test_corrupt_state_is_treated_as_missing(
        self,
    ):
        """验证损坏状态文件不会触发 Git Diff 回退。"""

        from codex_task_review.state import TaskStateStore

        with temporary_workspace() as workspace:
            data_root = workspace / "plugin-data"
            store = TaskStateStore(data_root)
            identity = TaskIdentity(
                "session-corrupt",
                "turn-1",
            )
            state_path = store.path_for(identity)
            state_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            state_path.write_text(
                "{not-json",
                encoding="utf-8",
            )

            loaded = store.load(identity)

        self.assertIsNone(loaded)

    def test_stop_without_matching_state_never_runs_git_or_diff(
        self,
    ):
        """验证缺少对应状态时 Stop 不查仓库也不生成整个分支 Diff。"""

        from codex_task_review.orchestrator import TaskOrchestrator

        with temporary_workspace() as workspace:
            orchestrator = TaskOrchestrator(
                workspace / "plugin-data",
            )
            hook_input = HookInput.from_payload(
                {
                    "hook_event_name": "Stop",
                    "session_id": "missing-session",
                    "turn_id": "missing-turn",
                    "cwd": str(workspace / "not-a-git-repository"),
                    "stop_hook_active": False,
                    "last_assistant_message": None,
                }
            )

            output = orchestrator.handle_stop(hook_input)

        result = output.to_dict()
        self.assertTrue(result["continue"])
        self.assertIn(
            "missing_task_state",
            result["systemMessage"],
        )

    def test_stop_hook_active_is_a_safe_no_op(
        self,
    ):
        """验证 Stop 重入时立即放行且不执行快照。"""

        from codex_task_review.orchestrator import TaskOrchestrator

        with temporary_workspace() as workspace:
            orchestrator = TaskOrchestrator(
                workspace / "plugin-data",
            )
            hook_input = HookInput.from_payload(
                {
                    "hook_event_name": "Stop",
                    "session_id": "active-session",
                    "turn_id": "active-turn",
                    "cwd": str(workspace / "not-a-git-repository"),
                    "stop_hook_active": True,
                    "last_assistant_message": "",
                }
            )

            output = orchestrator.handle_stop(hook_input)

        self.assertIn(
            "stop_hook_active",
            output.to_dict()["systemMessage"],
        )

    def test_prompt_submit_stores_snapshot_and_stop_invokes_reviewer(
        self,
    ):
        """验证任务快照驱动 Reviewer 只审查本轮 Diff。"""

        from unittest.mock import Mock

        from codex_task_review.models import ReviewResult
        from codex_task_review.orchestrator import TaskOrchestrator
        from codex_task_review.state import TaskStateStore

        with temporary_workspace() as workspace:
            with temporary_git_repository() as repo_root:
                data_root = workspace / "plugin-data"
                review_runner = Mock()
                review_runner.run.return_value = ReviewResult(
                    status="completed",
                    raw_output="No findings",
                )
                orchestrator = TaskOrchestrator(
                    data_root,
                    review_runner=review_runner,
                )
                prompt_input = HookInput.from_payload(
                    {
                        "hook_event_name": "UserPromptSubmit",
                        "session_id": "session-flow",
                        "turn_id": "turn-flow",
                        "cwd": str(repo_root),
                        "prompt": "add a feature",
                    }
                )

                prompt_output = orchestrator.handle_user_prompt_submit(
                    prompt_input,
                )
                self.assertIn(
                    "snapshot_recorded",
                    prompt_output.to_dict()["systemMessage"],
                )

                new_file = repo_root / "new feature.txt"
                new_file.write_text(
                    "feature change\n",
                    encoding="utf-8",
                )
                stop_input = HookInput.from_payload(
                    {
                        "hook_event_name": "Stop",
                        "session_id": "session-flow",
                        "turn_id": "turn-flow",
                        "cwd": str(repo_root),
                        "stop_hook_active": False,
                        "last_assistant_message": "finished",
                    }
                )

                stop_output = orchestrator.handle_stop(stop_input)
                stored = TaskStateStore(data_root).load(
                    stop_input.identity,
                )

        self.assertIn(
            "review_completed",
            stop_output.to_dict()["systemMessage"],
        )
        self.assertIsNone(stored)
        review_runner.run.assert_called_once()

    def test_stop_skips_small_bugfix_and_removes_only_its_state(
        self,
    ):
        """验证简单 Bug 修复跳过 Reviewer 并仅清理当前任务状态。"""

        from unittest.mock import Mock

        from codex_task_review.orchestrator import TaskOrchestrator
        from codex_task_review.state import TaskStateStore

        with temporary_workspace() as workspace:
            with temporary_git_repository() as repo_root:
                data_root = workspace / "plugin-data"
                review_runner = Mock()
                orchestrator = TaskOrchestrator(
                    data_root,
                    review_runner=review_runner,
                )
                prompt_input = HookInput.from_payload(
                    {
                        "hook_event_name": "UserPromptSubmit",
                        "session_id": "session-skip",
                        "turn_id": "turn-skip",
                        "cwd": str(repo_root),
                        "prompt": "fix a small bug",
                    }
                )
                orchestrator.handle_user_prompt_submit(prompt_input)
                (repo_root / "src.py").write_text(
                    "value = 2\n",
                    encoding="utf-8",
                )
                stop_input = HookInput.from_payload(
                    {
                        "hook_event_name": "Stop",
                        "session_id": "session-skip",
                        "turn_id": "turn-skip",
                        "cwd": str(repo_root),
                        "stop_hook_active": False,
                        "last_assistant_message": "done",
                    }
                )

                stop_output = orchestrator.handle_stop(stop_input)
                stored = TaskStateStore(data_root).load(
                    stop_input.identity,
                )

        result = stop_output.to_dict()
        self.assertIn(
            "simple_bugfix",
            result["systemMessage"],
        )
        self.assertIsNone(stored)
        review_runner.run.assert_not_called()

    def test_stop_reports_reviewer_failure_without_blocking_and_cleans_state(
        self,
    ):
        """验证 Reviewer 失败时 Hook 放行并清理本轮状态。"""

        from unittest.mock import Mock

        from codex_task_review.models import ReviewResult
        from codex_task_review.orchestrator import TaskOrchestrator
        from codex_task_review.state import TaskStateStore

        with temporary_workspace() as workspace:
            with temporary_git_repository() as repo_root:
                data_root = workspace / "plugin-data"
                review_runner = Mock()
                review_runner.run.return_value = ReviewResult(
                    status="failed",
                    raw_output="",
                    error="Codex CLI unavailable",
                )
                orchestrator = TaskOrchestrator(
                    data_root,
                    review_runner=review_runner,
                )
                prompt_input = HookInput.from_payload(
                    {
                        "hook_event_name": "UserPromptSubmit",
                        "session_id": "session-review",
                        "turn_id": "turn-review",
                        "cwd": str(repo_root),
                        "prompt": "add a new feature",
                    }
                )
                orchestrator.handle_user_prompt_submit(prompt_input)
                (repo_root / "feature.py").write_text(
                    "def feature():\n    return True\n",
                    encoding="utf-8",
                )
                stop_input = HookInput.from_payload(
                    {
                        "hook_event_name": "Stop",
                        "session_id": "session-review",
                        "turn_id": "turn-review",
                        "cwd": str(repo_root),
                        "stop_hook_active": False,
                        "last_assistant_message": "done",
                    }
                )

                stop_output = orchestrator.handle_stop(stop_input)
                stored = TaskStateStore(data_root).load(
                    stop_input.identity,
                )

        self.assertIn(
            "review_failed",
            stop_output.to_dict()["systemMessage"],
        )
        self.assertTrue(
            stop_output.to_dict()["continue"],
        )
        self.assertIsNone(stored)
        review_runner.run.assert_called_once()

    def test_hook_entrypoint_returns_one_json_object_for_invalid_input(
        self,
    ):
        """验证 Hook 入口收到无效 JSON 时仍只输出合法 JSON。"""

        project_root = Path(__file__).resolve().parents[1]
        script_path = project_root / "hooks" / "task_review.py"
        process = subprocess.run(
            [
                sys.executable,
                str(script_path),
            ],
            cwd=project_root,
            input="not-json",
            capture_output=True,
            text=True,
            encoding="utf-8",
            env={
                **os.environ,
                "PLUGIN_ROOT": str(project_root),
                "PLUGIN_DATA": str(project_root / ".test-tmp" / "plugin-data"),
            },
            check=False,
        )

        output = json.loads(process.stdout)
        self.assertEqual(
            process.returncode,
            0,
        )
        self.assertTrue(output["continue"])
        self.assertIn(
            "invalid_hook_input",
            output["systemMessage"],
        )

    def test_hook_entrypoint_skips_recursive_reviewer_environment(
        self,
    ):
        """验证 Reviewer 子进程继承递归标记后 Hook 立即跳过。"""

        project_root = Path(__file__).resolve().parents[1]
        script_path = project_root / "hooks" / "task_review.py"
        hook_payload = json.dumps(
            {
                "hook_event_name": "Stop",
                "session_id": "recursive-session",
                "turn_id": "recursive-turn",
                "cwd": str(project_root),
                "stop_hook_active": False,
                "last_assistant_message": "reviewing",
            }
        )
        process = subprocess.run(
            [
                sys.executable,
                str(script_path),
            ],
            cwd=project_root,
            input=hook_payload,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env={
                **os.environ,
                "PLUGIN_ROOT": str(project_root),
                "PLUGIN_DATA": str(project_root / ".test-tmp" / "plugin-data"),
                "CODEX_TASK_REVIEW_ACTIVE": "1",
            },
            check=False,
        )

        output = json.loads(process.stdout)
        self.assertEqual(
            process.returncode,
            0,
        )
        self.assertTrue(
            output["continue"],
        )
        self.assertIn(
            "recursive_review",
            output["systemMessage"],
        )


if __name__ == "__main__":
    unittest.main()
