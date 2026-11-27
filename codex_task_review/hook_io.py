"""Codex Hook stdin/stdout 的严格 JSON 适配层。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .models import TaskIdentity


class InvalidHookInput(ValueError):
    """表示 Codex Hook 输入缺少必要字段或字段类型错误。"""


@dataclass(frozen=True)
class HookInput:
    """保存 UserPromptSubmit 或 Stop Hook 的标准化输入。"""

    hook_event_name: str
    identity: TaskIdentity
    cwd: Path
    prompt: str
    stop_hook_active: bool
    last_assistant_message: str

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
    ) -> "HookInput":
        """校验并标准化 Codex Hook JSON 对象。

        Args:
            payload: Codex 通过 stdin 传入的 JSON 字段映射。

        Returns:
            供生命周期处理器使用的标准输入模型。

        Raises:
            InvalidHookInput: 事件类型、必填字段或字段值类型无效时抛出。
        """

        if not isinstance(payload, Mapping):
            raise InvalidHookInput("Hook 输入必须是 JSON 对象")

        event_name = payload.get("hook_event_name")

        if event_name not in {
            "UserPromptSubmit",
            "Stop",
        }:
            raise InvalidHookInput("不支持的 hook_event_name")

        session_id = cls._required_string(
            payload,
            "session_id",
        )
        turn_id = cls._required_string(
            payload,
            "turn_id",
        )
        cwd_value = cls._required_string(
            payload,
            "cwd",
        )

        prompt = payload.get("prompt", "")

        if not isinstance(prompt, str):
            raise InvalidHookInput("prompt 必须是字符串")

        stop_hook_active = payload.get(
            "stop_hook_active",
            False,
        )

        if not isinstance(stop_hook_active, bool):
            raise InvalidHookInput("stop_hook_active 必须是布尔值")

        last_assistant_message = payload.get(
            "last_assistant_message",
            "",
        )

        if last_assistant_message is None:
            last_assistant_message = ""

        if not isinstance(last_assistant_message, str):
            raise InvalidHookInput("last_assistant_message 必须是字符串或 null")

        if event_name == "UserPromptSubmit" and "prompt" not in payload:
            raise InvalidHookInput("UserPromptSubmit 缺少 prompt")

        return cls(
            hook_event_name=event_name,
            identity=TaskIdentity(
                session_id=session_id,
                turn_id=turn_id,
            ),
            cwd=Path(cwd_value),
            prompt=prompt,
            stop_hook_active=stop_hook_active,
            last_assistant_message=last_assistant_message,
        )

    @staticmethod
    def _required_string(
        payload: Mapping[str, Any],
        field_name: str,
    ) -> str:
        """读取并校验非空字符串字段。

        Args:
            payload: 待校验的 Hook JSON 字段映射。
            field_name: 要读取的字段名。

        Returns:
            字段对应的非空字符串。

        Raises:
            InvalidHookInput: 字段缺失、类型错误或内容为空时抛出。
        """

        value = payload.get(field_name)

        if not isinstance(value, str) or not value.strip():
            raise InvalidHookInput(
                f"{field_name} 必须是非空字符串"
            )

        return value


@dataclass(frozen=True)
class HookOutput:
    """生成 Codex 通用通知或 Stop 续跑输出。"""

    status: str
    reason_code: str
    message: str
    continuation_reason: str | None = None

    def to_dict(
        self,
    ) -> dict[str, Any]:
        """生成普通 Hook 通知或一次 Stop 续跑所需的 JSON 字段。

        Returns:
            普通通知包含 `continue: true` 和 `systemMessage`；设置续跑原因时返回
            Stop 专用的 `decision: block`、`reason` 与 `systemMessage`。
        """

        output: dict[str, Any] = {
            "systemMessage": (
                f"[codex-task-review][{self.status}][{self.reason_code}] "
                f"{self.message}"
            )
        }

        if self.continuation_reason is None:
            output["continue"] = True
        else:
            output["decision"] = "block"
            output["reason"] = self.continuation_reason

        return output
