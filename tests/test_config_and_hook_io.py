import json
import unittest
from pathlib import Path

from tests.temp_utils import temporary_workspace


class ConfigAndHookIoTests(unittest.TestCase):
    """验证配置默认值和 Hook JSON 输入输出契约。"""

    def test_default_config_matches_project_contract(
        self,
    ):
        """验证未配置时使用需求定义的安全默认值。"""

        from codex_task_review.config import ReviewConfig

        config = ReviewConfig.defaults()

        self.assertTrue(config.skip_simple_bugfix)
        self.assertTrue(config.skip_pure_ui)
        self.assertEqual(config.max_bugfix_files, 3)
        self.assertEqual(config.max_bugfix_changed_lines, 80)
        self.assertEqual(config.force_review_marker, "[review:force]")
        self.assertEqual(config.report_directory, ".codex/reviews")
        self.assertEqual(config.review_timeout, 600)
        self.assertIsNone(config.review_model)
        self.assertIsNone(config.review_reasoning_effort)

    def test_config_loads_valid_project_overrides(
        self,
    ):
        """验证项目级 JSON 配置覆盖指定默认字段。"""

        from codex_task_review.config import ReviewConfig

        with temporary_workspace() as repo_root:
            config_directory = repo_root / ".codex"
            config_directory.mkdir()
            config_path = config_directory / "task-review.json"
            config_path.write_text(
                json.dumps(
                    {
                        "max_bugfix_files": 5,
                        "high_risk_paths": ["billing/", "migrations/"],
                        "review_model": "gpt-5-codex",
                        "review_reasoning_effort": "high",
                    }
                ),
                encoding="utf-8",
            )

            config = ReviewConfig.from_repo(repo_root)

        self.assertEqual(config.max_bugfix_files, 5)
        self.assertEqual(config.high_risk_paths, ["billing/", "migrations/"])
        self.assertEqual(config.max_bugfix_changed_lines, 80)
        self.assertEqual(config.review_model, "gpt-5-codex")
        self.assertEqual(config.review_reasoning_effort, "high")

    def test_null_reviewer_overrides_keep_codex_defaults(
        self,
    ):
        """验证模型与推理强度为 null 时不覆盖 Codex CLI 默认值。"""

        from codex_task_review.config import ReviewConfig

        with temporary_workspace() as repo_root:
            config_directory = repo_root / ".codex"
            config_directory.mkdir()
            (config_directory / "task-review.json").write_text(
                json.dumps(
                    {
                        "review_model": None,
                        "review_reasoning_effort": None,
                    }
                ),
                encoding="utf-8",
            )

            config = ReviewConfig.from_repo(repo_root)

        self.assertIsNone(config.review_model)
        self.assertIsNone(config.review_reasoning_effort)

    def test_invalid_reviewer_overrides_are_reported(
        self,
    ):
        """验证显式空值或非字符串 Reviewer 配置不会被静默忽略。"""

        from codex_task_review.config import InvalidReviewConfigError
        from codex_task_review.config import ReviewConfig

        invalid_values = (
            {"review_model": ""},
            {"review_model": 7},
            {"review_reasoning_effort": "  "},
            {"review_reasoning_effort": False},
        )

        for invalid_config in invalid_values:
            with self.subTest(config=invalid_config):
                with temporary_workspace() as repo_root:
                    config_directory = repo_root / ".codex"
                    config_directory.mkdir()
                    (config_directory / "task-review.json").write_text(
                        json.dumps(invalid_config),
                        encoding="utf-8",
                    )

                    with self.assertRaises(InvalidReviewConfigError):
                        ReviewConfig.from_repo(repo_root)

    def test_invalid_config_keeps_safe_defaults(
        self,
    ):
        """验证错误字段不会覆盖其对应默认值。"""

        from codex_task_review.config import ReviewConfig

        with temporary_workspace() as repo_root:
            config_directory = repo_root / ".codex"
            config_directory.mkdir()
            config_path = config_directory / "task-review.json"
            config_path.write_text(
                "{\"max_bugfix_files\": \"many\"}",
                encoding="utf-8",
            )

            config = ReviewConfig.from_repo(repo_root)

        self.assertEqual(config.max_bugfix_files, 3)

    def test_user_prompt_submit_requires_prompt_and_identity(
        self,
    ):
        """验证提交用户 Prompt 时必须提供任务身份和 Prompt。"""

        from codex_task_review.hook_io import HookInput
        from codex_task_review.hook_io import InvalidHookInput

        payload = {
            "hook_event_name": "UserPromptSubmit",
            "cwd": ".",
        }

        with self.assertRaises(InvalidHookInput):
            HookInput.from_payload(payload)

    def test_stop_accepts_null_last_assistant_message(
        self,
    ):
        """验证 Stop Hook 的可空消息会标准化为空字符串。"""

        from codex_task_review.hook_io import HookInput

        hook_input = HookInput.from_payload(
            {
                "hook_event_name": "Stop",
                "session_id": "session-a",
                "turn_id": "turn-1",
                "cwd": "C:/work",
                "stop_hook_active": False,
                "last_assistant_message": None,
            }
        )

        self.assertFalse(hook_input.stop_hook_active)
        self.assertEqual(hook_input.last_assistant_message, "")

    def test_hook_output_is_codex_compatible_and_always_continues(
        self,
    ):
        """验证 Hook 输出只包含通用字段且始终允许 Agent 继续。"""

        from codex_task_review.hook_io import HookOutput

        output = HookOutput(
            "skipped",
            "no_changes",
            "没有代码变化",
        ).to_dict()

        self.assertEqual(output["continue"], True)
        self.assertEqual(
            set(output),
            {
                "continue",
                "systemMessage",
            },
        )


if __name__ == "__main__":
    unittest.main()
