"""插件配置的默认值和项目级覆盖读取。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_HIGH_RISK_KEYWORDS = [
    "security",
    "permission",
    "auth",
    "authorization",
    "authentication",
    "payment",
    "order",
    "finance",
    "database",
    "migration",
    "concurrency",
    "thread",
    "cache",
    "lock",
    "ci",
    "cd",
    "workflow",
    "deployment",
    "dependency",
    "安全",
    "权限",
    "认证",
    "鉴权",
    "支付",
    "订单",
    "财务",
    "数据库",
    "迁移",
    "并发",
    "缓存",
    "依赖",
]

DEFAULT_HIGH_RISK_PATHS = [
    ".github/",
    ".gitlab/",
    "auth/",
    "security/",
    "payment/",
    "billing/",
    "database/",
    "db/",
    "migrations/",
    "deploy/",
    "infra/",
    "dockerfile",
    "requirements",
    "package.json",
    "package-lock",
    "pnpm-lock",
    "yarn.lock",
    "poetry.lock",
    "pyproject.toml",
    "go.mod",
    "go.sum",
    "cargo.toml",
    "cargo.lock",
]


class InvalidReviewConfigError(ValueError):
    """表示 Reviewer 的显式模型或推理强度配置无效。"""


@dataclass
class ReviewConfig:
    """保存任务分类、Reviewer 和报告输出所需的可配置参数。"""

    skip_simple_bugfix: bool = True
    skip_pure_ui: bool = True
    max_bugfix_files: int = 3
    max_bugfix_changed_lines: int = 80
    force_review_marker: str = "[review:force]"
    report_directory: str = ".codex/reviews"
    review_timeout: int = 600
    review_model: str | None = None
    review_reasoning_effort: str | None = None
    max_diff_bytes: int = 1024 * 1024
    high_risk_keywords: list[str] = field(
        default_factory=lambda: list(DEFAULT_HIGH_RISK_KEYWORDS)
    )
    high_risk_paths: list[str] = field(
        default_factory=lambda: list(DEFAULT_HIGH_RISK_PATHS)
    )

    @classmethod
    def defaults(
        cls,
    ) -> "ReviewConfig":
        """返回一份独立的安全默认配置。

        Returns:
            含默认值和独立可变列表的新配置对象。
        """

        return cls()

    @classmethod
    def from_repo(
        cls,
        repo_root: Path,
    ) -> "ReviewConfig":
        """从仓库配置文件加载有效覆盖项。

        Args:
            repo_root: 当前 Git 仓库的根目录。

        Returns:
            项目配置和安全默认值合并后的配置对象。
        """

        config = cls.defaults()
        config_path = repo_root / ".codex" / "task-review.json"

        try:
            raw_config = json.loads(config_path.read_text(encoding="utf-8"))
        except (
            OSError,
            json.JSONDecodeError,
        ):
            return config

        if not isinstance(raw_config, dict):
            return config

        for field_name in (
            "review_model",
            "review_reasoning_effort",
        ):
            value = raw_config.get(field_name)

            if value is None:
                continue

            if not isinstance(value, str) or not value.strip():
                raise InvalidReviewConfigError(
                    f"{field_name} 必须是非空字符串或 null"
                )

            setattr(
                config,
                field_name,
                value.strip(),
            )

        scalar_types: dict[str, type[Any]] = {
            "skip_simple_bugfix": bool,
            "skip_pure_ui": bool,
            "max_bugfix_files": int,
            "max_bugfix_changed_lines": int,
            "force_review_marker": str,
            "report_directory": str,
            "review_timeout": int,
            "max_diff_bytes": int,
        }

        for field_name, expected_type in scalar_types.items():
            value = raw_config.get(field_name)

            if isinstance(value, expected_type) and not (
                expected_type is int and isinstance(value, bool)
            ):
                if expected_type is int and value < 0:
                    continue

                if expected_type is str and not value.strip():
                    continue

                setattr(config, field_name, value)

        for field_name in (
            "high_risk_keywords",
            "high_risk_paths",
        ):
            value = raw_config.get(field_name)

            if isinstance(value, list) and all(
                isinstance(item, str) and item.strip()
                for item in value
            ):
                setattr(config, field_name, value)

        return config
