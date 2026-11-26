"""Codex UserPromptSubmit 与 Stop 的跨平台 JSON Hook 入口。"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def _load_plugin_package() -> None:
    """将安装目录放入 Python 导入路径。

    Returns:
        无；插件根目录确保位于 `sys.path` 首位。
    """

    configured_root = os.environ.get("PLUGIN_ROOT")
    plugin_root = (
        Path(configured_root)
        if configured_root
        else Path(__file__).resolve().parents[1]
    ).resolve()
    root_text = str(plugin_root)

    if root_text not in sys.path:
        sys.path.insert(
            0,
            root_text,
        )


def _serialize_output(
    output: dict[str, Any],
) -> None:
    """把单个 Codex Hook JSON 对象写入 stdout。

    Args:
        output: 符合 Codex 通用 Hook 输出字段的字典。

    Returns:
        无；stdout 只写入一个 JSON 行。
    """

    output_text = json.dumps(
        output,
        ensure_ascii=False,
        separators=(
            ",",
            ":",
        ),
    )
    sys.stdout.buffer.write(
        output_text.encode("utf-8") + b"\n"
    )
    sys.stdout.buffer.flush()


def _safe_error_output(
    status: str,
    reason_code: str,
    message: str,
) -> dict[str, Any]:
    """创建不会阻塞主 Agent 的统一错误输出。

    Args:
        status: 人类可读的处理状态。
        reason_code: 稳定的诊断原因代码。
        message: 不含堆栈的简短说明。

    Returns:
        只包含 `continue` 与 `systemMessage` 字段的 Hook JSON 对象。
    """

    from codex_task_review.hook_io import HookOutput

    return HookOutput(
        status,
        reason_code,
        message,
    ).to_dict()


def main() -> int:
    """读取 Hook stdin、运行处理器并输出安全 JSON。

    Returns:
        始终返回零，避免审查插件故障阻止主 Agent 完成任务。
    """

    _load_plugin_package()

    try:
        payload_text = sys.stdin.buffer.read().decode("utf-8")
        payload = json.loads(payload_text)
    except (
        json.JSONDecodeError,
        UnicodeDecodeError,
    ):
        _serialize_output(
            _safe_error_output(
                "skipped",
                "invalid_hook_input",
                "Hook stdin 不是有效 JSON，插件已安全跳过",
            )
        )

        return 0

    try:
        from codex_task_review.hook_io import HookInput

        hook_input = HookInput.from_payload(payload)
    except (
        ImportError,
        TypeError,
        ValueError,
    ) as error:
        _serialize_output(
            _safe_error_output(
                "skipped",
                "invalid_hook_input",
                f"Hook 输入无法处理: {error}",
            )
        )

        return 0

    if os.environ.get("CODEX_TASK_REVIEW_ACTIVE") == "1":
        _serialize_output(
            _safe_error_output(
                "skipped",
                "recursive_review",
                "检测到 Reviewer 递归调用标记，插件已安全跳过",
            )
        )

        return 0

    data_root_value = os.environ.get("PLUGIN_DATA")

    if not data_root_value:
        _serialize_output(
            _safe_error_output(
                "skipped",
                "plugin_data_missing",
                "Codex 未提供 PLUGIN_DATA，无法保存任务状态",
            )
        )

        return 0

    try:
        from codex_task_review.orchestrator import TaskOrchestrator

        orchestrator = TaskOrchestrator(
            Path(data_root_value),
        )

        if hook_input.hook_event_name == "UserPromptSubmit":
            output = orchestrator.handle_user_prompt_submit(
                hook_input,
            )
        else:
            output = orchestrator.handle_stop(
                hook_input,
            )
    except Exception as error:
        output = None
        message = f"Hook 执行失败，主任务不受影响: {error}"
        _serialize_output(
            _safe_error_output(
                "skipped",
                "hook_execution_failed",
                message,
            )
        )

        return 0

    if output is None:
        _serialize_output(
            _safe_error_output(
                "skipped",
                "hook_execution_failed",
                "Hook 未生成处理结果，主任务不受影响",
            )
        )

        return 0

    _serialize_output(
        output.to_dict()
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
