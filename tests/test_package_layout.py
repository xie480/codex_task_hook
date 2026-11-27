"""Codex Task Review 插件清单、Hooks 与发布资料的契约测试。"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class PackageLayoutTests(unittest.TestCase):
    """验证 GitHub 仓库包含可安装且不依赖本机路径的插件包。"""

    def load_json(
        self,
        relative_path: str,
    ) -> dict[str, Any]:
        """读取仓库内 JSON 配置并确保顶层是对象。

        Args:
            relative_path: 相对于项目根目录的 JSON 文件路径。

        Returns:
            文件解析出的 JSON 对象。
        """

        payload = json.loads(
            (PROJECT_ROOT / relative_path).read_text(
                encoding="utf-8",
            )
        )

        self.assertIsInstance(
            payload,
            dict,
        )

        return payload

    def test_codex_manifest_is_primary_and_references_hooks(self):
        """验证 Codex 兼容清单作为唯一插件入口并声明 Hooks。"""

        manifest = self.load_json(
            ".codex-plugin/plugin.json",
        )

        self.assertEqual(
            manifest["name"],
            "codex-task-review",
        )
        self.assertEqual(
            manifest["version"],
            "0.1.0",
        )
        self.assertEqual(
            manifest["hooks"],
            "./hooks/hooks.json",
        )
        self.assertEqual(
            manifest["author"]["name"],
            "Yilena",
        )
        self.assertEqual(
            manifest["author"]["url"],
            "https://github.com/xie480",
        )
        self.assertEqual(
            manifest["homepage"],
            "https://github.com/xie480/codex_task_hook",
        )
        self.assertEqual(
            manifest["repository"],
            "https://github.com/xie480/codex_task_hook",
        )

        interface = manifest["interface"]

        self.assertIn(
            "Read-only code review",
            interface["capabilities"],
        )
        self.assertEqual(
            interface["composerIcon"],
            "./assets/codex-task-review.svg",
        )
        self.assertEqual(
            interface["logo"],
            "./assets/codex-task-review.svg",
        )
        self.assertEqual(
            interface["developerName"],
            "Yilena",
        )
        self.assertEqual(
            interface["websiteURL"],
            "https://github.com/xie480/codex_task_hook",
        )
        self.assertFalse(
            (PROJECT_ROOT / "plugin.json").exists(),
        )

    def test_hook_events_have_portable_and_windows_commands(self):
        """验证两个事件均配置 Unix 和 Windows Python 入口。"""

        hooks_config = self.load_json(
            "hooks/hooks.json",
        )
        event_hooks = hooks_config["hooks"]

        self.assertEqual(
            set(event_hooks),
            {
                "UserPromptSubmit",
                "Stop",
            },
        )

        for event_name in (
            "UserPromptSubmit",
            "Stop",
        ):
            with self.subTest(event=event_name):
                command_hook = event_hooks[event_name][0]["hooks"][0]
                self.assertEqual(
                    command_hook["type"],
                    "command",
                )
                self.assertIn(
                    "${PLUGIN_ROOT}/hooks/task_review.py",
                    command_hook["command"],
                )
                self.assertIn(
                    "py -3",
                    command_hook["commandWindows"],
                )
                self.assertIn(
                    "${PLUGIN_ROOT}",
                    command_hook["commandWindows"],
                )
                self.assertGreater(
                    command_hook["timeout"],
                    0,
                )

        stop_hook = event_hooks["Stop"][0]["hooks"][0]
        self.assertIn(
            "正在检查本轮变更并进行只读审查",
            stop_hook["statusMessage"],
        )
        self.assertFalse(
            stop_hook.get("async", False),
        )

    def test_marketplace_references_the_github_repository_root(self):
        """验证 Marketplace 使用 Codex 支持的 Git URL 根目录源。"""

        marketplace = self.load_json(
            ".agents/plugins/marketplace.json",
        )
        plugin_entry = marketplace["plugins"][0]
        source = plugin_entry["source"]

        self.assertEqual(
            marketplace["name"],
            "codex-task-review-marketplace",
        )
        self.assertEqual(
            plugin_entry["name"],
            "codex-task-review",
        )
        self.assertEqual(
            source["source"],
            "url",
        )
        self.assertEqual(
            source["url"],
            "https://github.com/xie480/codex_task_hook.git",
        )
        self.assertEqual(
            source["ref"],
            "main",
        )
        self.assertEqual(
            plugin_entry["policy"]["installation"],
            "AVAILABLE",
        )
        self.assertEqual(
            plugin_entry["policy"]["authentication"],
            "ON_INSTALL",
        )
        self.assertIn(
            "category",
            plugin_entry,
        )

    def test_examples_and_readme_are_complete_and_path_independent(self):
        """验证配置、报告示例、README 操作命令和路径不含本机位置。"""

        config_example = self.load_json(
            "examples/task-review.json",
        )
        report_example = (
            PROJECT_ROOT / "examples" / "code-review-example.md"
        ).read_text(
            encoding="utf-8",
        )
        readme = (
            PROJECT_ROOT / "README.md"
        ).read_text(
            encoding="utf-8",
        )

        self.assertEqual(
            config_example["report_directory"],
            ".codex/reviews",
        )
        self.assertEqual(
            config_example["force_review_marker"],
            "[review:force]",
        )

        for heading in (
            "## P0",
            "## P1",
            "## P2",
            "## P3",
            "## 已检查且未发现问题",
            "## 未能检查",
            "## 修复建议汇总",
        ):
            with self.subTest(heading=heading):
                self.assertIn(
                    heading,
                    report_example,
                )

        for command in (
            "codex plugin marketplace add https://github.com/xie480/codex_task_hook --ref main",
            "codex plugin add codex-task-review@codex-task-review-marketplace",
            "codex plugin marketplace upgrade codex-task-review-marketplace",
            "codex plugin remove codex-task-review@codex-task-review-marketplace",
            "codex plugin marketplace remove codex-task-review-marketplace",
            "git remote set-url origin https://github.com/xie480/codex_task_hook.git",
            "git push -u origin main",
        ):
            with self.subTest(command=command):
                self.assertIn(
                    command,
                    readme,
                )

        self.assertNotRegex(
            readme,
            r"YOUR_[A-Z_]+",
        )

        for section in (
            "工作流程",
            "环境要求",
            "安装",
            "更新",
            "卸载",
            "配置",
            "跳过规则",
            "报告示例",
            "当前会话反馈",
            "常见问题",
            "Windows",
            "GitHub",
            "信任流程",
            "公共插件目录",
        ):
            with self.subTest(section=section):
                self.assertIn(
                    section,
                    readme,
                )

        checked_files = [
            ".codex-plugin/plugin.json",
            "hooks/hooks.json",
            ".agents/plugins/marketplace.json",
            "examples/task-review.json",
            "examples/code-review-example.md",
            "assets/codex-task-review.svg",
            "README.md",
        ]

        for relative_path in checked_files:
            with self.subTest(path=relative_path):
                content = (
                    PROJECT_ROOT / relative_path
                ).read_text(
                    encoding="utf-8",
                )
                self.assertNotIn(
                    "C:\\Users\\",
                    content,
                )


if __name__ == "__main__":
    unittest.main()
