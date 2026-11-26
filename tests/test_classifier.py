"""本地确定性任务分类器行为测试。"""

from __future__ import annotations

import unittest

from codex_task_review.config import ReviewConfig
from codex_task_review.models import DiffFile
from codex_task_review.models import DiffResult


def make_diff(
    files: list[tuple[str, str, int, int]],
    patch_lines: list[str] | None = None,
) -> DiffResult:
    """构造分类器使用的轻量 Diff 模型。

    Args:
        files: 路径、状态、新增行数和删除行数元组。
        patch_lines: 可选的 Diff 文本行。

    Returns:
        汇总行数和补丁文本的 DiffResult。
    """

    diff_files = [
        DiffFile(
            path=path,
            status=status,
            additions=additions,
            deletions=deletions,
        )
        for path, status, additions, deletions in files
    ]

    return DiffResult(
        base_tree="a" * 40,
        final_tree="b" * 40,
        patch=(
            "\n".join(patch_lines)
            if patch_lines is not None
            else "\n".join(
                f"+line {index}"
                for index in range(
                    sum(item[2] for item in files)
                )
            )
        ),
        files=diff_files,
        additions=sum(item[2] for item in files),
        deletions=sum(item[3] for item in files),
    )


class ClassifierTests(unittest.TestCase):
    """验证 Review/skip 决策基于 Prompt 和本轮 Diff 证据。"""

    def test_no_changes_never_starts_review(self):
        """验证空 Diff 无论 Prompt 如何都直接跳过。"""

        from codex_task_review.classifier import classify_task

        result = classify_task(
            "[review:force] add a new feature",
            make_diff([]),
            ReviewConfig.defaults(),
        )

        self.assertFalse(result.should_review)
        self.assertEqual(
            result.kind,
            "no_changes",
        )

    def test_force_marker_overrides_bugfix_and_ui_skips(self):
        """验证强制标记对简单 Bug 与纯 UI 均触发 Review。"""

        from codex_task_review.classifier import classify_task

        config = ReviewConfig.defaults()
        bugfix = make_diff(
            [("src/math.py", "M", 1, 1)],
        )
        ui = make_diff(
            [("src/styles.css", "M", 1, 1)],
        )

        bugfix_result = classify_task(
            "[review:force] 修复 bug",
            bugfix,
            config,
        )
        ui_result = classify_task(
            "[review:force] 调整页面颜色",
            ui,
            config,
        )

        self.assertTrue(bugfix_result.should_review)
        self.assertTrue(ui_result.should_review)
        self.assertEqual(
            bugfix_result.kind,
            "forced_review",
        )

    def test_small_explicit_bugfix_within_threshold_is_skipped(self):
        """验证小型明确 Bug 修复在文件和行数阈值内跳过。"""

        from codex_task_review.classifier import classify_task

        diff = make_diff(
            [
                ("src/math.py", "M", 4, 3),
                ("tests/test_math.py", "M", 3, 2),
            ],
        )
        result = classify_task(
            "修复一个简单的计算 bug",
            diff,
            ReviewConfig.defaults(),
        )

        self.assertFalse(result.should_review)
        self.assertEqual(
            result.kind,
            "simple_bugfix",
        )
        self.assertEqual(
            result.changed_lines,
            12,
        )

    def test_bugfix_file_and_line_thresholds_force_review(self):
        """验证 Bug 修复超过文件数或总行数阈值时启动 Review。"""

        from codex_task_review.classifier import classify_task

        config = ReviewConfig.defaults()
        too_many_files = make_diff(
            [
                (f"src/file_{index}.py", "M", 1, 1)
                for index in range(4)
            ],
        )
        too_many_lines = make_diff(
            [("src/math.py", "M", 41, 40)],
        )

        files_result = classify_task(
            "fix bug",
            too_many_files,
            config,
        )
        lines_result = classify_task(
            "修复问题",
            too_many_lines,
            config,
        )

        self.assertTrue(files_result.should_review)
        self.assertTrue(lines_result.should_review)

    def test_three_files_and_exactly_eighty_changed_lines_can_skip(self):
        """验证文件数和行数阈值采用包含边界的判断。"""

        from codex_task_review.classifier import classify_task

        diff = make_diff(
            [
                ("src/a.py", "M", 20, 20),
                ("src/b.py", "M", 20, 20),
                ("tests/test_a.py", "M", 0, 0),
            ],
        )
        result = classify_task(
            "fix a small bug",
            diff,
            ReviewConfig.defaults(),
        )

        self.assertFalse(result.should_review)
        self.assertEqual(
            result.changed_files,
            3,
        )
        self.assertEqual(
            result.changed_lines,
            80,
        )

    def test_complex_bugfix_is_reviewed_even_when_small(self):
        """验证 Prompt 明确复杂的 Bug 修复不会走简单修复跳过。"""

        from codex_task_review.classifier import classify_task

        result = classify_task(
            "fix a complex parser bug across several modules",
            make_diff(
                [("src/worker.py", "M", 2, 2)],
            ),
            ReviewConfig.defaults(),
        )

        self.assertTrue(result.should_review)
        self.assertEqual(
            result.kind,
            "complex_bugfix",
        )

    def test_pure_stylesheet_and_svg_changes_are_skipped(self):
        """验证样式表和图标资源修改归类为纯视觉 UI。"""

        from codex_task_review.classifier import classify_task

        result = classify_task(
            "调整按钮颜色、间距和图标",
            make_diff(
                [
                    ("src/styles/main.scss", "M", 4, 2),
                    ("assets/icon.svg", "M", 1, 1),
                ],
            ),
            ReviewConfig.defaults(),
        )

        self.assertFalse(result.should_review)
        self.assertEqual(
            result.kind,
            "pure_ui",
        )

    def test_static_display_changes_in_tsx_and_vue_are_skipped(self):
        """验证仅静态文案和展示结构变化可归类为纯 UI。"""

        from codex_task_review.classifier import classify_task

        diff = make_diff(
            [
                ("src/components/Welcome.tsx", "M", 2, 1),
                ("src/views/home.vue", "M", 1, 1),
            ],
            [
                "-<h1>Old title</h1>",
                "+<h1>Welcome back</h1>",
                "+<p>Static display copy</p>",
                "-<span>Old</span>",
                "+<span>New</span>",
            ],
        )
        result = classify_task(
            "修改首页展示文案和静态结构",
            diff,
            ReviewConfig.defaults(),
        )

        self.assertFalse(result.should_review)
        self.assertEqual(
            result.kind,
            "pure_ui",
        )

    def test_ui_diff_with_api_state_validation_or_events_is_reviewed(self):
        """验证 UI 文件中的 API、状态、校验和事件逻辑触发 Review。"""

        from codex_task_review.classifier import classify_task

        business_lines = [
            "+const [value, setValue] = useState("
            "initialValue"
            ");",
            "+const response = await fetch(\"/api/items\");",
            "+function validateForm(values) {",
            "+return values.map((value) => normalize(value));",
            "+<button onClick={handleSave}>Save</button>",
            "+localStorage.setItem(\"value\", value);",
        ]

        for line in business_lines:
            with self.subTest(line=line):
                result = classify_task(
                    "调整设置面板 UI",
                    make_diff(
                        [("src/components/Settings.tsx", "M", 1, 0)],
                        [line],
                    ),
                    ReviewConfig.defaults(),
                )

                self.assertTrue(result.should_review)
                self.assertEqual(
                    result.kind,
                    "ui_logic",
                )

    def test_high_risk_path_overrides_simple_bugfix_skip(self):
        """验证权限、支付和数据库路径优先触发 Review。"""

        from codex_task_review.classifier import classify_task

        for path in (
            "src/auth/session.py",
            "src/payment/checkout.py",
            "database/migrations/001.sql",
        ):
            with self.subTest(path=path):
                result = classify_task(
                    "修复简单 bug",
                    make_diff(
                        [(path, "M", 1, 1)],
                    ),
                    ReviewConfig.defaults(),
                )

                self.assertTrue(result.should_review)
                self.assertEqual(
                    result.kind,
                    "high_risk",
                )
                self.assertTrue(result.risk_evidence)

    def test_high_risk_prompt_and_diff_keywords_trigger_review(self):
        """验证 Prompt 或修改代码中的风险关键字触发 Review。"""

        from codex_task_review.classifier import classify_task

        prompt_result = classify_task(
            "修复一个简单 bug 并检查权限控制",
            make_diff(
                [("src/basic.py", "M", 1, 1)],
            ),
            ReviewConfig.defaults(),
        )
        diff_result = classify_task(
            "修复一个简单 bug",
            make_diff(
                [("src/basic.py", "M", 1, 1)],
                ["+if user.has_payment_permission:",],
            ),
            ReviewConfig.defaults(),
        )

        self.assertTrue(prompt_result.should_review)
        self.assertTrue(diff_result.should_review)
        self.assertTrue(diff_result.risk_evidence)

    def test_new_features_refactors_and_unknown_changes_are_reviewed(self):
        """验证新功能、重构和不能确定的变更默认启动 Review。"""

        from codex_task_review.classifier import classify_task

        diff = make_diff(
            [("src/core.py", "M", 2, 1)],
        )

        for prompt in (
            "add a new feature",
            "重构核心模块",
            "改一下这个文件",
        ):
            with self.subTest(prompt=prompt):
                result = classify_task(
                    prompt,
                    diff,
                    ReviewConfig.defaults(),
                )

                self.assertTrue(result.should_review)
                self.assertEqual(
                    result.kind,
                    "review_required",
                )

    def test_disabled_skip_configuration_causes_review(self):
        """验证关闭简单 Bug 跳过配置后继续启动 Review。"""

        from codex_task_review.classifier import classify_task

        config = ReviewConfig.defaults()
        config.skip_simple_bugfix = False
        result = classify_task(
            "fix bug",
            make_diff(
                [("src/math.py", "M", 1, 1)],
            ),
            config,
        )

        self.assertTrue(result.should_review)
        self.assertEqual(
            result.kind,
            "simple_bugfix_reviewed",
        )


if __name__ == "__main__":
    unittest.main()
