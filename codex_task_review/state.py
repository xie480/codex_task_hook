"""PLUGIN_DATA 中按 session 与 turn 隔离的原子任务状态存储。"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from .models import TaskIdentity
from .models import TaskState


class TaskStateStore:
    """为每个 Codex session/turn 保存单独的任务开始快照。"""

    def __init__(
        self,
        data_root: Path,
    ) -> None:
        """设置插件持久化数据根目录。

        Args:
            data_root: Codex 提供的 `PLUGIN_DATA` 目录。
        """

        self.data_root = data_root.expanduser().resolve()
        self.tasks_root = self.data_root / "tasks"

    def path_for(
        self,
        identity: TaskIdentity,
    ) -> Path:
        """根据完整任务身份生成不可控路径片段的状态文件路径。

        Args:
            identity: 由 session_id 和 turn_id 组成的任务身份。

        Returns:
            位于 tasks 目录、以身份摘要命名的 JSON 文件路径。
        """

        identity_bytes = (
            f"{identity.session_id}\0{identity.turn_id}"
        ).encode(
            "utf-8",
            errors="surrogatepass",
        )
        identity_digest = hashlib.sha256(
            identity_bytes
        ).hexdigest()

        return self.tasks_root / f"{identity_digest}.json"

    def save(
        self,
        state: TaskState,
    ) -> None:
        """原子保存任务状态，避免并发读到半写入 JSON。

        Args:
            state: 包含仓库、Tree 和 Prompt 的任务状态。

        Returns:
            无；状态经同目录临时文件和原子替换持久化。

        Raises:
            OSError: 数据目录不可写或磁盘写入失败时抛出。
            ValueError: 状态内容无法序列化为 JSON 时抛出。
        """

        self.tasks_root.mkdir(
            parents=True,
            exist_ok=True,
        )
        state_path = self.path_for(
            state.identity,
        )
        payload = {
            "session_id": state.identity.session_id,
            "turn_id": state.identity.turn_id,
            "repo_root": str(state.repo_root),
            "base_tree": state.base_tree,
            "prompt": state.prompt,
            "created_at": state.created_at,
            "config_version": state.config_version,
        }
        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=f"{state_path.stem}-",
            suffix=".tmp",
            dir=self.tasks_root,
        )
        temporary_path = Path(temporary_name)

        try:
            with os.fdopen(
                file_descriptor,
                "w",
                encoding="utf-8",
                newline="\n",
            ) as temporary_file:
                json.dump(
                    payload,
                    temporary_file,
                    ensure_ascii=False,
                    separators=(
                        ",",
                        ":",
                    ),
                )
                temporary_file.flush()
                os.fsync(
                    temporary_file.fileno()
                )

            os.replace(
                temporary_path,
                state_path,
            )
        finally:
            temporary_path.unlink(
                missing_ok=True,
            )

    def load(
        self,
        identity: TaskIdentity,
    ) -> TaskState | None:
        """读取并校验指定任务状态，损坏状态视为不存在。

        Args:
            identity: 要读取的 session/turn 任务身份。

        Returns:
            校验成功的任务状态；文件缺失、损坏或身份不匹配时返回 None。
        """

        state_path = self.path_for(identity)

        try:
            payload = json.loads(
                state_path.read_text(
                    encoding="utf-8",
                )
            )
        except (
            OSError,
            json.JSONDecodeError,
            UnicodeDecodeError,
        ):
            return None

        if not isinstance(payload, dict):
            return None

        if (
            payload.get("session_id") != identity.session_id
            or payload.get("turn_id") != identity.turn_id
        ):
            return None

        required_fields = (
            "repo_root",
            "base_tree",
            "prompt",
            "created_at",
            "config_version",
        )

        if not all(
            isinstance(payload.get(field_name), str)
            for field_name in required_fields
        ):
            return None

        return TaskState(
            identity=identity,
            repo_root=Path(
                payload["repo_root"],
            ),
            base_tree=payload["base_tree"],
            prompt=payload["prompt"],
            created_at=payload["created_at"],
            config_version=payload["config_version"],
        )

    def remove(
        self,
        identity: TaskIdentity,
    ) -> None:
        """删除指定任务状态，不影响其他 session/turn 文件。

        Args:
            identity: 要删除的任务身份。

        Returns:
            无；文件不存在时保持静默。
        """

        self.path_for(identity).unlink(
            missing_ok=True,
        )
