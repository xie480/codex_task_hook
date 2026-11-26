"""在工作区内创建可回收的临时测试目录。"""

from __future__ import annotations

import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def temporary_workspace(
    root: Path | None = None,
) -> Iterator[Path]:
    """创建并回收工作区内的临时测试目录。

    Args:
        root: 可选的临时目录父路径；未传入时使用仓库根目录。

    Returns:
        上下文管理器，进入时返回新建目录路径。

    Raises:
        OSError: 创建父目录或唯一临时目录失败时抛出。
    """

    workspace_root = (
        root
        if root is not None
        else Path(__file__).resolve().parents[1]
    )
    parent = workspace_root / ".test-tmp"
    parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    directory = parent / uuid.uuid4().hex
    directory.mkdir()

    try:
        yield directory
    finally:
        shutil.rmtree(
            directory,
            ignore_errors=True,
        )
