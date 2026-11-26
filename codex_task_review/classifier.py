"""基于本轮 Prompt 与 Diff 的本地确定性任务分类器。"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from .config import ReviewConfig
from .models import ClassificationResult
from .models import DiffResult


BUGFIX_KEYWORDS = [
    "bug fix",
    "bugfix",
    "fix bug",
    "fix a bug",
    "fix the bug",
    "fix issue",
    "fix error",
    "修复 bug",
    "修复bug",
    "修复问题",
    "修复异常",
    "修复错误",
    "修正 bug",
    "修正bug",
]

COMPLEX_TASK_KEYWORDS = [
    "complex",
    "major",
    "refactor",
    "redesign",
    "new feature",
    "add a feature",
    "implement feature",
    "new module",
    "new api",
    "migration",
    "concurrency",
    "data consistency",
    "复杂",
    "重构",
    "新功能",
    "新增功能",
    "新模块",
    "接口改造",
    "架构调整",
    "数据一致性",
]

UI_FILE_EXTENSIONS = {
    ".css",
    ".scss",
    ".sass",
    ".less",
    ".svg",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
    ".jsx",
    ".tsx",
    ".vue",
    ".html",
}

UI_LOGIC_PATTERNS = {
    "api_request": re.compile(
        r"(?:\bfetch\s*\(|\baxios(?:\.|\s*\()|\busequery\s*\(|"
        r"\busemutation\s*\(|\bgraphql\b|/api/)",
        re.IGNORECASE,
    ),
    "state_management": re.compile(
        r"\b(?:usestate|usereducer|usestore|zustand|redux|dispatch|setstate)\b|"
        r"\bstate\s*(?:=|\.)",
        re.IGNORECASE,
    ),
    "form_validation": re.compile(
        r"\b(?:validate\w*|validation|yup|zod|joi|onsubmit|required)\b",
        re.IGNORECASE,
    ),
    "data_conversion": re.compile(
        r"\.(?:map|filter|reduce)\s*\(|\bjson\.(?:parse|stringify)\s*\(|"
        r"\b(?:parseint|parsefloat|transform|convert)\s*\(",
        re.IGNORECASE,
    ),
    "permission_control": re.compile(
        r"\b(?:permission|authorization|authentication|isadmin|canaccess|hasrole)\b",
        re.IGNORECASE,
    ),
    "event_handling": re.compile(
        r"\bon(?:click|change|submit|input|keydown|keyup)\s*=|"
        r"@(click|change|submit|input|keydown|keyup)\b|"
        r"\baddEventListener\s*\(",
        re.IGNORECASE,
    ),
    "persistence": re.compile(
        r"\b(?:localstorage|sessionstorage|indexeddb|document\.cookie)\b|"
        r"\.(?:setitem|removeitem)\s*\(",
        re.IGNORECASE,
    ),
    "reactive_state": re.compile(
        r"\b(?:ref|computed|watch|watchEffect)\s*\(",
        re.IGNORECASE,
    ),
}


def classify_task(
    prompt: str,
    diff: DiffResult,
    config: ReviewConfig,
) -> ClassificationResult:
    """根据任务意图、路径、Diff 逻辑和规模生成 Review 决策。

    Args:
        prompt: 当前 turn 的用户 Prompt。
        diff: 仅包含当前任务开始与结束 Tree 差异的 Diff。
        config: 插件默认配置或仓库自定义配置。

    Returns:
        含分类类型、Review 决策、原因和证据的结果对象。
    """

    changed_files = len(diff.files)
    changed_lines = diff.changed_lines

    if diff.is_empty:
        return _classification(
            "no_changes",
            False,
            "本轮没有文件变化",
            changed_files,
            changed_lines,
        )

    if config.force_review_marker and config.force_review_marker in prompt:
        return _classification(
            "forced_review",
            True,
            f"Prompt 包含强制审查标记 {config.force_review_marker}",
            changed_files,
            changed_lines,
        )

    risk_evidence = _find_high_risk_evidence(
        prompt,
        diff,
        config,
    )

    if risk_evidence:
        return _classification(
            "high_risk",
            True,
            "检测到高风险路径或内容，必须启动 Review",
            changed_files,
            changed_lines,
            risk_evidence,
        )

    prompt_lower = prompt.casefold()

    if _contains_any(
        prompt_lower,
        COMPLEX_TASK_KEYWORDS,
    ):
        kind = (
            "complex_bugfix"
            if _is_bugfix_prompt(
                prompt_lower,
            )
            else "review_required"
        )
        return _classification(
            kind,
            True,
            "Prompt 表明这是新功能、重构或复杂开发任务",
            changed_files,
            changed_lines,
        )

    ui_paths = _all_files_are_ui(diff)

    if ui_paths:
        logic_evidence = _find_ui_logic_evidence(diff)

        if logic_evidence:
            return _classification(
                "ui_logic",
                True,
                "UI Diff 涉及业务逻辑、状态、数据或事件处理",
                changed_files,
                changed_lines,
                logic_evidence,
            )

        if config.skip_pure_ui:
            return _classification(
                "pure_ui",
                False,
                "修改仅涉及样式、展示结构、静态文案或视觉资源",
                changed_files,
                changed_lines,
            )

        return _classification(
            "pure_ui_reviewed",
            True,
            "纯 UI 跳过配置已关闭",
            changed_files,
            changed_lines,
        )

    is_bugfix = _is_bugfix_prompt(
        prompt_lower,
    )

    if is_bugfix:
        within_file_limit = changed_files <= config.max_bugfix_files
        within_line_limit = changed_lines <= config.max_bugfix_changed_lines

        if (
            config.skip_simple_bugfix
            and within_file_limit
            and within_line_limit
        ):
            return _classification(
                "simple_bugfix",
                False,
                (
                    f"简单 Bug 修复在阈值内：{changed_files} 个文件，"
                    f"{changed_lines} 行变化"
                ),
                changed_files,
                changed_lines,
            )

        return _classification(
            "simple_bugfix_reviewed",
            True,
            (
                "Bug 修复超过跳过阈值或简单修复跳过已关闭："
                f"{changed_files} 个文件，{changed_lines} 行变化"
            ),
            changed_files,
            changed_lines,
        )

    return _classification(
        "review_required",
        True,
        "无法可靠归类为简单 Bug 修复或纯 UI 修改，默认启动 Review",
        changed_files,
        changed_lines,
    )


def _classification(
    kind: str,
    should_review: bool,
    reason: str,
    changed_files: int,
    changed_lines: int,
    risk_evidence: list[str] | None = None,
) -> ClassificationResult:
    """使用统一字段创建分类结果。

    Args:
        kind: 稳定的分类标识。
        should_review: 是否启动 Reviewer。
        reason: 决策原因。
        changed_files: 变化文件数量。
        changed_lines: 新增和删除行总数。
        risk_evidence: 高风险或 UI 逻辑证据。

    Returns:
        填充完整字段的 ClassificationResult。
    """

    return ClassificationResult(
        kind=kind,
        should_review=should_review,
        reason=reason,
        changed_files=changed_files,
        changed_lines=changed_lines,
        risk_evidence=(
            risk_evidence
            if risk_evidence is not None
            else []
        ),
    )


def _contains_any(
    text: str,
    keywords: list[str],
) -> bool:
    """判断文本是否包含任一配置或固定意图词。

    Args:
        text: 已按调用方需求规范化的字符串。
        keywords: 待匹配的关键字列表。

    Returns:
        命中至少一个非空关键字时返回真。
    """

    return any(
        keyword.casefold() in text
        for keyword in keywords
        if keyword
    )


def _is_bugfix_prompt(
    prompt: str,
) -> bool:
    """识别中英文中带有明确 Bug、问题或错误对象的修复请求。

    Args:
        prompt: 已做 casefold 规范化的任务 Prompt。

    Returns:
        Prompt 明确要求修复 Bug、问题、异常或错误时返回真。
    """

    if _contains_any(
        prompt,
        BUGFIX_KEYWORDS,
    ):
        return True

    chinese_fix = _contains_any(
        prompt,
        [
            "修复",
            "修正",
            "解决",
        ],
    )
    chinese_problem = _contains_any(
        prompt,
        [
            "问题",
            "异常",
            "错误",
            "bug",
        ],
    )

    if chinese_fix and chinese_problem:
        return True

    english_fix_pattern = re.compile(
        r"\b(?:fix|repair|resolve)\b.{0,60}"
        r"\b(?:bug|issue|error|defect|problem)\b",
        re.IGNORECASE,
    )
    reversed_english_pattern = re.compile(
        r"\b(?:bug|issue|error|defect|problem)\b.{0,30}"
        r"\bfix\b",
        re.IGNORECASE,
    )

    return bool(
        english_fix_pattern.search(prompt)
        or reversed_english_pattern.search(prompt)
    )


def _find_high_risk_evidence(
    prompt: str,
    diff: DiffResult,
    config: ReviewConfig,
) -> list[str]:
    """从 Prompt、Diff 文本和路径中收集高风险证据。

    Args:
        prompt: 当前任务 Prompt。
        diff: 当前任务的完整 Diff 结构。
        config: 含高风险路径和关键字配置的对象。

    Returns:
        以 `path:` 或 `keyword:` 开头的去重证据列表。
    """

    prompt_text = prompt.casefold()
    changed_text = "\n".join(
        _changed_patch_lines(diff.patch),
    ).casefold()
    all_text = f"{prompt_text}\n{changed_text}"
    evidence: list[str] = []
    normalized_paths = [
        diff_file.path.replace(
            "\\",
            "/",
        ).casefold()
        for diff_file in diff.files
    ]

    for diff_file in diff.files:
        if diff_file.old_path:
            normalized_paths.append(
                diff_file.old_path.replace(
                    "\\",
                    "/",
                ).casefold()
            )

    for configured_path in config.high_risk_paths:
        path_keyword = configured_path.replace(
            "\\",
            "/",
        ).casefold()

        if path_keyword and any(
            path_keyword in path
            for path in normalized_paths
        ):
            evidence.append(
                f"path:{configured_path}"
            )

    for keyword in config.high_risk_keywords:
        normalized_keyword = keyword.casefold().strip()

        if _contains_risk_keyword(
            all_text,
            normalized_keyword,
        ):
            evidence.append(
                f"keyword:{keyword}"
            )

    return list(
        dict.fromkeys(evidence)
    )


def _contains_risk_keyword(
    text: str,
    keyword: str,
) -> bool:
    """匹配风险词；短英文词采用 ASCII 边界避免子串误报。

    Args:
        text: Prompt 与变更行合并后的文本。
        keyword: 已规范化的风险关键字。

    Returns:
        风险词命中时返回真。
    """

    if not keyword:
        return False

    if keyword.isascii() and len(keyword) <= 3:
        pattern = re.compile(
            rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])",
            re.IGNORECASE,
        )

        return pattern.search(text) is not None

    return keyword in text


def _changed_patch_lines(
    patch: str,
) -> list[str]:
    """提取补丁中的新增或删除代码行，不包含 diff 元数据。

    Args:
        patch: `git diff` 生成的统一补丁文本。

    Returns:
        只包含新增行和删除行正文的字符串列表。
    """

    changed_lines: list[str] = []

    for line in patch.splitlines():
        if line.startswith(
            (
                "+++",
                "---",
            )
        ):
            continue

        if line.startswith(
            (
                "+",
                "-",
            )
        ):
            changed_lines.append(
                line[1:]
            )

    return changed_lines


def _all_files_are_ui(
    diff: DiffResult,
) -> bool:
    """确认所有变化文件均属于允许判定的 UI 展示文件类型。

    Args:
        diff: 当前任务的文件变化列表。

    Returns:
        Diff 非空且每个新旧路径后缀均属于 UI 后缀时返回真。
    """

    if not diff.files:
        return False

    paths: list[str] = []

    for diff_file in diff.files:
        paths.append(diff_file.path)

        if diff_file.old_path:
            paths.append(diff_file.old_path)

    return all(
        PurePosixPath(
            path.replace(
                "\\",
                "/",
            )
        ).suffix.casefold()
        in UI_FILE_EXTENSIONS
        for path in paths
    )


def _find_ui_logic_evidence(
    diff: DiffResult,
) -> list[str]:
    """检查 UI Diff 的增删代码行是否包含业务逻辑信号。

    Args:
        diff: 当前任务的完整 Diff。

    Returns:
        命中的逻辑类别列表；没有逻辑证据时为空。
    """

    changed_text = "\n".join(
        _changed_patch_lines(diff.patch),
    )
    evidence = [
        category
        for category, pattern in UI_LOGIC_PATTERNS.items()
        if pattern.search(changed_text)
    ]

    return evidence
