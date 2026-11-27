"""把 Reviewer 结果格式化为稳定且有界的 Markdown 内容。"""

from __future__ import annotations

import json
import re
from datetime import datetime
from datetime import timezone
from pathlib import Path

from .models import ClassificationResult
from .models import DiffResult
from .models import ReviewResult
from .models import TaskState


MAX_REVIEW_OUTPUT_BYTES = 64 * 1024
MAX_SESSION_FEEDBACK_BYTES = 4 * 1024
NO_FINDING_PHRASES = frozenset(
    {
        "no findings",
        "no issues found",
        "no actionable findings",
        "none",
        "none.",
        "无",
        "无。",
        "未发现",
        "未发现。",
        "未发现问题",
        "未发现可操作问题",
        "未发现可操作缺陷",
    }
)
REVIEW_SECTION_PATTERN = re.compile(
    r"^\s{0,3}##\s*(P[0-3]|已检查且未发现问题|未能检查|修复建议汇总)\s*$",
    re.IGNORECASE,
)
SEVERITY_HEADINGS = [
    "P0",
    "P1",
    "P2",
    "P3",
]


def format_report(
    task: TaskState,
    diff: DiffResult,
    classification: ClassificationResult,
    result: ReviewResult,
    generated_at: datetime | None = None,
) -> str:
    """把任务、Diff、分类和 Reviewer 状态渲染为完整 Markdown。

    Args:
        task: 任务身份、Prompt 和起始快照元信息。
        diff: 已捕获的 BASE→FINAL Diff 与统计信息。
        classification: Review 决策、原因和风险证据。
        result: Reviewer 原始文本、完成状态和失败原因。
        generated_at: 可选的报告生成时间；缺省使用当前本地时间。

    Returns:
        始终包含 P0–P3、检查项和修复建议章节的 UTF-8 Markdown 文本。
    """

    report_time = (
        generated_at
        if generated_at is not None
        else datetime.now(
            timezone.utc,
        ).astimezone()
    )
    bounded_output, output_truncated = _bound_output(
        result.raw_output,
    )
    parsed_sections = _parse_review_sections(
        bounded_output,
    )
    no_findings = _reports_no_findings(
        bounded_output,
    )
    severity_sections = [
        _format_severity_section(
            severity,
            result,
            parsed_sections,
            no_findings,
        )
        for severity in SEVERITY_HEADINGS
    ]
    file_rows = [
        "\t".join(
            [
                item.status,
                f"+{item.additions}",
                f"-{item.deletions}",
                json.dumps(
                    item.path.replace("\\", "/"),
                    ensure_ascii=False,
                ),
                (
                    json.dumps(
                        item.old_path.replace("\\", "/"),
                        ensure_ascii=False,
                    )
                    if item.old_path
                    else ""
                ),
            ]
        )
        for item in diff.files
    ]
    completion_text = _completion_summary(
        result,
        no_findings,
    )
    checked_text = _section_or_fallback(
        parsed_sections,
        "已检查且未发现问题",
        (
            "Reviewer 未能完成完整检查。"
            if result.status != "completed"
            else (
                "未发现可操作问题。"
                if no_findings
                else "Reviewer 未提供结构化检查清单；请查看原始输出。"
            )
        ),
    )
    unchecked_text = _section_or_fallback(
        parsed_sections,
        "未能检查",
        (
            _review_error_summary(result)
            if result.status != "completed"
            else "Reviewer 未提供未检查项说明。"
        ),
    )
    recommendations_text = _section_or_fallback(
        parsed_sections,
        "修复建议汇总",
        (
            "无需修复。"
            if no_findings and result.status == "completed"
            else "请参阅 P0–P3 章节和下方 Reviewer 原始输出。"
        ),
    )
    output_note = (
        "\n\n> 原始 Reviewer 输出超过报告上限，末尾内容已截断。"
        if output_truncated
        else ""
    )
    raw_output = (
        _fenced_block(bounded_output)
        if bounded_output
        else "（Reviewer 未返回文本。）"
    )
    risk_evidence = (
        "\n".join(
            f"- `{_escape_inline(item)}`"
            for item in classification.risk_evidence
        )
        if classification.risk_evidence
        else "无。"
    )
    lines = [
        "# Codex Task Review",
        "",
        "## 审查信息",
        "",
        f"- 生成时间：{report_time.isoformat(timespec='seconds')}",
        f"- 会话：`{_escape_inline(task.identity.session_id)}`",
        f"- 轮次：`{_escape_inline(task.identity.turn_id)}`",
        f"- 仓库：{_fenced_block(str(task.repo_root))}",
        f"- 任务开始时间：`{_escape_inline(task.created_at)}`",
        f"- Reviewer 状态：`{_escape_inline(result.status)}`",
        f"- 任务分类：`{_escape_inline(classification.kind)}`",
        f"- 分类原因：{_escape_inline(classification.reason)}",
        "",
        "## 任务描述",
        "",
        _fenced_block(task.prompt),
        "",
        "## Diff 摘要",
        "",
        f"- BASE_TREE：`{diff.base_tree}`",
        f"- FINAL_TREE：`{diff.final_tree}`",
        f"- 变化文件：{len(diff.files)}",
        f"- 新增行：{diff.additions}",
        f"- 删除行：{diff.deletions}",
        f"- 总变化行：{diff.changed_lines}",
        f"- 高风险证据：\n{risk_evidence}",
        "",
        "### 修改文件",
        "",
        (
            _fenced_block("\n".join(file_rows))
            if file_rows
            else "无文件变化。"
        ),
        "",
        "## 总体结论",
        "",
        completion_text,
        "",
        f"Reviewer 错误：{_review_error_summary(result)}"
        if result.error
        else "",
        "",
        *severity_sections,
        "## 已检查且未发现问题",
        "",
        checked_text,
        "",
        "## 未能检查",
        "",
        unchecked_text,
        "",
        "## 修复建议汇总",
        "",
        recommendations_text,
        "",
        "## Reviewer 原始输出",
        "",
        raw_output + output_note,
        "",
    ]

    return "\n".join(
        line
        for line in lines
        if line is not None
    )


def format_session_feedback(
    result: ReviewResult,
    report_path: Path | None = None,
    report_error: str | None = None,
) -> str:
    """生成回传当前会话的有界审查结论与具体 finding 摘要。

    Args:
        result: Reviewer 的完成状态、原始输出和失败原因。
        report_path: 已写入的完整报告路径；报告写入失败时为空。
        report_error: 报告写入失败原因；报告写入成功时为空。

    Returns:
        保留严重等级与定位信息、并包含报告状态的有界 Markdown 文本。
    """

    lines = [
        "Codex Task Review 结果",
        "",
    ]
    bounded_output, output_truncated = _bound_output(
        result.raw_output,
    )
    parsed_sections = _parse_review_sections(
        bounded_output,
    )

    if result.status == "completed":
        lines.append("状态：只读审查已完成。")

        if _reports_no_findings(bounded_output) or _has_only_clear_severity_sections(
            parsed_sections,
        ):
            lines.append("结论：未发现可操作问题。")
        else:
            findings: list[tuple[str, str]] = []

            for severity in SEVERITY_HEADINGS:
                section_text = parsed_sections.get(
                    severity,
                    "",
                ).strip()

                if section_text and not _is_clear_section(section_text):
                    findings.append(
                        (
                            severity,
                            section_text,
                        )
                    )

            if findings:
                lines.append("结论：发现以下 Reviewer findings。")

                for severity, section_text in findings:
                    lines.extend(
                        [
                            "",
                            f"### {severity}",
                            section_text,
                        ]
                    )
            elif bounded_output:
                lines.extend(
                    [
                        "",
                        "结论：Reviewer 未返回可解析的 P0–P3 章节；以下为其有界原始输出：",
                        bounded_output,
                    ]
                )
            else:
                lines.append("结论：Reviewer 未返回可展示的审查结论。")

        if output_truncated:
            lines.extend(
                [
                    "",
                    "Reviewer 原始输出超过解析上限；会话摘要以当前已解析部分为准。",
                ]
            )
    else:
        lines.extend(
            [
                "状态：只读审查未完成，不能视为审查通过。",
                f"错误：{_bounded_error_text(result.error)}",
            ]
        )

        if bounded_output:
            lines.extend(
                [
                    "",
                    "Reviewer 部分输出（审查未完成，不能视为完整结果）：",
                    bounded_output,
                ]
            )

    if report_path is not None:
        report_line = f"完整报告：{report_path}"
    elif report_error:
        report_line = (
            "报告写入失败："
            + _bounded_error_text(report_error)
        )
    else:
        report_line = "完整报告：未生成。"

    return _bound_session_feedback(
        "\n".join(lines),
        report_line,
    )


def _has_only_clear_severity_sections(
    sections: dict[str, str],
) -> bool:
    """判断 Reviewer 是否为每个有输出的等级都明确写出无发现。

    Args:
        sections: 从 Reviewer 输出提取的 Markdown 章节。

    Returns:
        至少存在一个 P0–P3 章节且所有非空章节均为明确无发现时返回真。
    """

    severity_sections = [
        section.strip()
        for severity in SEVERITY_HEADINGS
        if (section := sections.get(severity, "").strip())
    ]

    return bool(severity_sections) and all(
        _is_clear_section(section)
        for section in severity_sections
    )


def _is_clear_section(
    section_text: str,
) -> bool:
    """识别仅表示该等级无发现的常见短语，不解释自由文本语义。

    Args:
        section_text: P0–P3 章节正文。

    Returns:
        正文精确匹配已知无发现短语时返回真。
    """

    normalized = " ".join(
        section_text.casefold().split()
    )

    return normalized in NO_FINDING_PHRASES


def _bounded_error_text(
    error_text: str | None,
) -> str:
    """将失败文本规范化并限制长度，避免错误输出挤占 findings 摘要。

    Args:
        error_text: Reviewer 或报告写入器返回的错误文本。

    Returns:
        单行最多 500 个字符的错误摘要。
    """

    if not error_text:
        return "未知错误。"

    normalized = " ".join(
        error_text.split()
    )

    if len(normalized) > 500:
        return normalized[:499] + "…"

    return normalized


def _bound_session_feedback(
    body: str,
    report_line: str,
) -> str:
    """限制会话反馈字节数，并在截断时保留报告状态或路径。

    Args:
        body: 审查结论和按严重级别排列的 findings 正文。
        report_line: 完整报告路径或报告写入失败信息。

    Returns:
        UTF-8 字节数不超过会话上限的反馈文本。
    """

    complete_text = f"{body}\n\n{report_line}"
    encoded_text = complete_text.encode(
        "utf-8",
        errors="replace",
    )

    if len(encoded_text) <= MAX_SESSION_FEEDBACK_BYTES:
        return complete_text

    truncation_note = (
        "…（会话摘要已截断；剩余内容请查看完整报告。）"
    )
    suffix = f"\n\n{truncation_note}\n{report_line}"
    available_body_bytes = (
        MAX_SESSION_FEEDBACK_BYTES
        - len(
            suffix.encode(
                "utf-8",
                errors="replace",
            )
        )
    )
    truncated_body = encoded_text[
        :max(0, available_body_bytes)
    ].decode(
        "utf-8",
        errors="ignore",
    ).rstrip()

    if truncated_body:
        last_line_break = truncated_body.rfind("\n")

        if last_line_break > 0:
            truncated_body = truncated_body[:last_line_break]

    return f"{truncated_body}{suffix}"


def _format_severity_section(
    severity: str,
    result: ReviewResult,
    sections: dict[str, str],
    no_findings: bool,
) -> str:
    """生成单个 P0–P3 标题及审查正文或明确的缺失说明。

    Args:
        severity: 当前稳定严重等级名称。
        result: Reviewer 的状态和原始输出。
        sections: 从 Reviewer Markdown 中提取的结构化章节。
        no_findings: Reviewer 是否明确表示没有可操作发现。

    Returns:
        包含等级标题以及正文、未检查或缺少格式说明的 Markdown。
    """

    if result.status != "completed":
        body = "未检查：Reviewer 未完成审查。"
    else:
        body = sections.get(
            severity,
            "",
        ).strip()

        if not body:
            body = (
                "未发现。"
                if no_findings
                else "Reviewer 未返回该等级的结构化条目；请参阅原始输出。"
            )

    return "\n".join(
        [
            f"## {severity}",
            "",
            body,
            "",
        ]
    )


def _parse_review_sections(
    raw_output: str,
) -> dict[str, str]:
    """按精确 Markdown 标题提取等级、检查项和修复建议章节。

    Args:
        raw_output: 已受大小限制的 Reviewer 原始输出。

    Returns:
        标题名到正文的映射；未识别格式的输出仍保留在原始章节。
    """

    sections: dict[str, list[str]] = {}
    active_heading: str | None = None
    active_fence_character: str | None = None

    for line in raw_output.splitlines():
        fence_match = re.match(
            r"^\s{0,3}(`{3,}|~{3,})",
            line,
        )

        if fence_match:
            fence_character = fence_match.group(1)[0]

            if active_fence_character is None:
                active_fence_character = fence_character
            elif active_fence_character == fence_character:
                active_fence_character = None

            if active_heading is not None:
                sections[active_heading].append(line)

            continue

        if active_fence_character is not None:
            if active_heading is not None:
                sections[active_heading].append(line)

            continue

        heading_match = REVIEW_SECTION_PATTERN.match(line)

        if heading_match:
            active_heading = heading_match.group(1)

            if active_heading.startswith("P"):
                active_heading = active_heading.upper()

            sections.setdefault(
                active_heading,
                [],
            )
            continue

        if re.match(
            r"^\s{0,3}##\s+",
            line,
        ):
            active_heading = None
            continue

        if active_heading is not None:
            sections[active_heading].append(line)

    return {
        heading: "\n".join(lines).strip()
        for heading, lines in sections.items()
    }


def _reports_no_findings(
    raw_output: str,
) -> bool:
    """识别明确的全局无问题结论，避免对缺失等级自行推断。

    Args:
        raw_output: Reviewer 原始输出。

    Returns:
        输出整体仅包含常见无问题短语时返回真。
    """

    normalized = " ".join(
        raw_output.casefold().split()
    )
    return normalized in NO_FINDING_PHRASES


def _completion_summary(
    result: ReviewResult,
    no_findings: bool,
) -> str:
    """根据 Reviewer 状态写出不会夸大审查完整度的总评。

    Args:
        result: Reviewer 完成状态和失败原因。
        no_findings: Reviewer 是否明确返回全局无发现结论。

    Returns:
        完成、无发现或失败降级的中文审查结论。
    """

    if result.status == "completed" and no_findings:
        return "只读 Review 已完成；Reviewer 明确未发现可操作问题。"

    if result.status == "completed":
        return "只读 Review 已完成；发现与建议见下方等级章节和原始输出。"

    return (
        "只读 Review 未完成；下方内容可能只是部分输出，"
        "不能作为审查通过结论。"
    )


def _section_or_fallback(
    sections: dict[str, str],
    heading: str,
    fallback: str,
) -> str:
    """读取 Reviewer 的结构化附加章节或返回诚实的缺省说明。

    Args:
        sections: 按标题提取的原始 Reviewer 章节。
        heading: 要读取的章节名称。
        fallback: Reviewer 未返回章节时使用的说明。

    Returns:
        非空章节内容或 fallback 文本。
    """

    return sections.get(
        heading,
        "",
    ).strip() or fallback


def _review_error_summary(
    result: ReviewResult,
) -> str:
    """限制并转义 Reviewer 错误文本，避免破坏 Markdown 报告结构。

    Args:
        result: Reviewer 结果对象。

    Returns:
        单行、最多 4000 字符的安全错误摘要。
    """

    if not result.error:
        return "无。"

    normalized_error = " ".join(
        result.error.split()
    )
    truncated_error = normalized_error[:4000]

    if len(normalized_error) > len(truncated_error):
        truncated_error += "…"

    return _escape_inline(
        truncated_error,
    )


def _bound_output(
    raw_output: str,
) -> tuple[str, bool]:
    """按 UTF-8 字节上限截断 Reviewer 原文且不切断编码字符。

    Args:
        raw_output: Reviewer 返回的完整文本。

    Returns:
        有界文本和是否发生截断的布尔值。
    """

    encoded_output = raw_output.encode(
        "utf-8",
        errors="replace",
    )

    if len(encoded_output) <= MAX_REVIEW_OUTPUT_BYTES:
        return raw_output, False

    bounded_output = encoded_output[:MAX_REVIEW_OUTPUT_BYTES].decode(
        "utf-8",
        errors="ignore",
    )

    return bounded_output, True


def _fenced_block(
    content: str,
) -> str:
    """选择长于内容内反引号序列的围栏，安全展示原始文本。

    Args:
        content: 任务 Prompt、文件列表或 Reviewer 原始输出。

    Returns:
        用动态长度 Markdown 代码围栏包裹的原文。
    """

    longest_run = max(
        (
            len(match.group(0))
            for match in re.finditer(
                r"`+",
                content,
            )
        ),
        default=0,
    )
    fence = "`" * max(
        3,
        longest_run + 1,
    )

    return "\n".join(
        [
            f"{fence}text",
            content,
            fence,
        ]
    )


def _escape_inline(
    content: str,
) -> str:
    """压平换行并转义行内代码分隔符。

    Args:
        content: 分类原因、任务身份或错误摘要。

    Returns:
        不会跨越报告行或闭合 Markdown 代码的单行字符串。
    """

    normalized = " ".join(
        content.split()
    )

    return normalized.replace(
        "`",
        "\\`",
    )
