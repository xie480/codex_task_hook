# Codex Task Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone, Windows-compatible Codex Plugin that captures task-scoped Git snapshots, classifies the exact task Diff, runs a read-only `codex review -` only when required, and writes Markdown reports without modifying user code.

**Architecture:** Use `.codex-plugin/plugin.json` as the Codex compatibility manifest so the current Codex loader attaches plugin-bundled Hooks. Hook entrypoint `hooks/task_review.py` loads a focused `codex_task_review` standard-library package. A temporary Git index creates BASE and FINAL trees; Stop exports FINAL to an isolated temporary review repository and passes only BASE→FINAL Diff through stdin to `codex review -`.

**Tech Stack:** Python 3 standard library, Git for Windows, Codex CLI `codex review -`, JSON, Markdown, Python `unittest`.

**Spec:** `docs/superpowers/specs/2026-11-24-codex-task-review-design.md`

## Global Constraints

- Target Windows 10/11, PowerShell, Git for Windows, Python 3, and Codex CLI.
- Do not add third-party Python dependencies, cloud services, API keys, WSL, Bash-only syntax, or hard-coded user paths.
- Never run `git reset`, `git checkout`, `git clean`, automatic `git add` on the user Index, or automatic commit.
- Only use a temporary `GIT_INDEX_FILE`; the user’s real Git Index must remain unchanged.
- Never fall back to `git diff HEAD`, `git diff main`, `git diff origin/main`, or whole-branch Diff when task state is missing.
- Hook commands always return valid JSON with `continue: true`; never block or request an automatic continuation.
- Reports are written only after FINAL Tree and BASE→FINAL Diff are captured.
- Use `command` plus `commandWindows`; Windows starts with `py -3`, and missing interpreters produce a safe, readable skip.
- Reviewer runs in a temporary final-snapshot Git repository with `CODEX_TASK_REVIEW_ACTIVE=1` and read-only sandbox configuration.
- Every new Python class/function has a useful Chinese comment covering responsibility, parameters, return value, and relevant exceptions.
- Commit locally in the format `type：中文描述`; do not push.

---

### Task 1: Initialize the standalone repository and preserve the approved design

**Files:**
- Create: `.gitignore`
- Create: `LICENSE`
- Keep: `docs/superpowers/specs/2026-11-24-codex-task-review-design.md`
- Keep: `docs/superpowers/plans/2026-11-24-codex-task-review.md`

**Interfaces:**
- Produces a clean Git repository with tracked design and plan documents; later tasks rely on the repository root and local commit history.

- [ ] **Step 1: Initialize Git without touching any existing project outside the workspace**

Run in `E:\YilenaCode\codex_task_hook`:

    git init -b main

Expected: a new local `.git` directory and no files outside the workspace changed.

- [ ] **Step 2: Add ignore rules before adding product files**

Create `.gitignore` with these exact entries:

    __pycache__/
    *.py[cod]
    .pytest_cache/
    .mypy_cache/
    .venv/
    dist/
    build/
    .codex/reviews/
    .codex/task-review.json

The actual user configuration and generated reports remain local; the example configuration is tracked later.

- [ ] **Step 3: Add the MIT license**

Create `LICENSE` with the standard MIT text and copyright holder `Codex Task Review contributors`.

- [ ] **Step 4: Verify the initial repository contents**

Run:

    git status --short
    git diff --check

Expected: only the design, plan, `.gitignore`, and `LICENSE` are untracked; `git diff --check` exits 0.

- [ ] **Step 5: Commit the approved design baseline**

    git add .gitignore LICENSE docs/superpowers/specs/2026-11-24-codex-task-review-design.md docs/superpowers/plans/2026-11-24-codex-task-review.md
    git commit -m "docs：确定 Codex Task Review 设计与实现计划"

Expected: one local commit with the requested Chinese commit format.

### Task 2: Define data contracts, configuration, and Hook JSON behavior with failing tests first

**Files:**
- Create: `codex_task_review/__init__.py`
- Create: `codex_task_review/models.py`
- Create: `codex_task_review/config.py`
- Create: `codex_task_review/hook_io.py`
- Create: `tests/__init__.py`
- Create: `tests/test_config_and_hook_io.py`

**Interfaces:**
- `TaskIdentity(session_id: str, turn_id: str)` exposes `key` for state filenames.
- `HookInput.from_payload(payload: dict) -> HookInput` validates `UserPromptSubmit` and `Stop` fields.
- `HookOutput(status: str, reason_code: str, message: str) -> dict` returns only Codex-compatible output fields.
- `ReviewConfig.from_repo(repo_root: Path) -> ReviewConfig` loads `.codex/task-review.json` or safe defaults.

- [ ] **Step 1: Write failing tests for stable defaults and Hook input validation**

Add tests that assert:

    def test_default_config_matches_project_contract(self):
        config = ReviewConfig.defaults()
        self.assertTrue(config.skip_simple_bugfix)
        self.assertEqual(config.max_bugfix_files, 3)
        self.assertEqual(config.max_bugfix_changed_lines, 80)
        self.assertEqual(config.force_review_marker, "[review:force]")
        self.assertEqual(config.report_directory, ".codex/reviews")
        self.assertEqual(config.review_timeout, 600)

    def test_user_prompt_submit_requires_prompt_and_identity(self):
        payload = {"hook_event_name": "UserPromptSubmit", "cwd": "."}
        with self.assertRaises(InvalidHookInput):
            HookInput.from_payload(payload)

    def test_stop_accepts_null_last_assistant_message(self):
        hook_input = HookInput.from_payload({
            "hook_event_name": "Stop",
            "session_id": "session-a",
            "turn_id": "turn-1",
            "cwd": "C:/work",
            "stop_hook_active": False,
            "last_assistant_message": None,
        })
        self.assertFalse(hook_input.stop_hook_active)
        self.assertEqual(hook_input.last_assistant_message, "")

    def test_hook_output_is_codex_compatible_and_always_continues(self):
        output = HookOutput("skipped", "no_changes", "没有代码变化").to_dict()
        self.assertEqual(output["continue"], True)
        self.assertEqual(set(output), {"continue", "systemMessage"})

- [ ] **Step 2: Run the focused tests and confirm the expected missing-symbol failures**

Run:

    py -3 -m unittest tests.test_config_and_hook_io -v

Expected: FAIL because the contracts do not exist yet, not because the test fixture is malformed.

- [ ] **Step 3: Implement the minimal contracts and defaults**

Implement dataclasses and a `ReviewConfig` with the exact fields `skip_simple_bugfix`, `skip_pure_ui`, `max_bugfix_files`, `max_bugfix_changed_lines`, `force_review_marker`, `report_directory`, `review_timeout`, `max_diff_bytes`, `high_risk_keywords`, and `high_risk_paths`. Parse JSON only from `<repo>/.codex/task-review.json`; reject wrong types, merge valid scalar/list fields, and retain defaults on parse errors. Add Chinese class/function comments.

- [ ] **Step 4: Run the focused tests and verify they pass**

    py -3 -m unittest tests.test_config_and_hook_io -v

Expected: all tests pass with no warnings.

- [ ] **Step 5: Commit the contracts**

    git add codex_task_review tests
    git commit -m "feat：建立插件配置与 Hook 数据契约"

### Task 3: Implement temporary-index snapshots and exact Diff computation

**Files:**
- Create: `codex_task_review/git_snapshot.py`
- Create: `tests/git_helpers.py`
- Create: `tests/test_git_snapshot.py`

**Interfaces:**
- `GitRepository.find(cwd: Path) -> GitRepository` returns the repository root or raises a typed `GitRepositoryError`.
- `GitSnapshotter.capture() -> Snapshot` creates and cleans up a temporary Index without changing the real Index.
- `GitSnapshotter.diff(base_tree: str, final_tree: str) -> DiffResult` runs `git diff --binary -M` between the two trees.
- `GitSnapshotter.export_tree(tree_id: str, destination: Path) -> None` exports a tree into an isolated directory for Reviewer use.

- [ ] **Step 1: Write failing integration tests using only temporary Git repositories**

Create helpers that run `git init`, set local identity, create an initial commit, and use `tempfile.TemporaryDirectory`. Add tests for:

    def test_start_dirty_files_are_excluded_from_task_diff(self): ...
    def test_new_modified_deleted_staged_and_unstaged_files_are_included(self): ...
    def test_rename_is_reported_with_similarity_detection(self): ...
    def test_snapshot_does_not_change_real_index(self): ...
    def test_chinese_and_space_path_is_supported(self): ...
    def test_repository_without_head_returns_explicit_error(self): ...

- [ ] **Step 2: Run the snapshot tests and verify they fail for missing implementation**

    py -3 -m unittest tests.test_git_snapshot -v

Expected: FAIL with missing `GitSnapshotter`/`GitRepository` symbols.

- [ ] **Step 3: Implement the temporary-index context manager**

Use `tempfile.NamedTemporaryFile(delete=False)` for a unique index path, set `GIT_INDEX_FILE` only in the `subprocess.run` environment, run `git read-tree HEAD`, then `git add -A` and `git write-tree`. Always unlink the temporary index and possible `.lock` file in `finally`; never call reset, checkout, clean, or mutate the user Index. Convert subprocess failures into `GitRepositoryError` with command and stderr but without secrets.

- [ ] **Step 4: Implement Diff parsing and tree export**

Run `git diff --binary -M base final` with `text=False`; decode with UTF-8 `errors="replace"`. Parse `--numstat`/`--name-status` in separate commands to obtain files, additions, deletions, and rename metadata. Export FINAL with `git archive --format=zip tree_id`, extract using Python `zipfile` into a new temporary directory, and reject unsafe archive members before extraction.

- [ ] **Step 5: Run the snapshot tests and the full suite**

    py -3 -m unittest tests.test_git_snapshot -v
    py -3 -m unittest discover -s tests -v

Expected: snapshot tests pass; earlier contract tests remain green.

- [ ] **Step 6: Commit the snapshot slice**

    git add codex_task_review/git_snapshot.py tests/git_helpers.py tests/test_git_snapshot.py
    git commit -m "feat：实现临时 Index 精确 Git 快照"

### Task 4: Add isolated task state and the UserPromptSubmit/Stop orchestration shell

**Files:**
- Create: `codex_task_review/state.py`
- Create: `codex_task_review/orchestrator.py`
- Modify: `codex_task_review/models.py`
- Create: `hooks/task_review.py`
- Create: `tests/test_state_and_orchestrator.py`

**Interfaces:**
- `TaskStateStore(data_root: Path).save(state: TaskState)`, `.load(identity)`, and `.remove(identity)` use safe encoded filenames and atomic replace.
- `TaskOrchestrator.handle_user_prompt_submit(hook_input: HookInput) -> HookOutput` captures the BASE tree and stores state.
- `TaskOrchestrator.handle_stop(hook_input: HookInput) -> HookOutput` returns a safe result after capturing FINAL/Diff; later Tasks inject classifier/reviewer/report collaborators.
- `hooks/task_review.py` exposes `main() -> int`, reads exactly one stdin JSON object, and prints exactly one Codex-compatible JSON object.

- [ ] **Step 1: Write failing tests for task isolation and error contracts**

Add tests for two sessions and two turns writing separate state files, parallel identities not overwriting each other, missing state never calling a fallback Diff, `stop_hook_active=True` being a safe no-op, and malformed Hook input returning `continue: true` JSON.

- [ ] **Step 2: Run the tests and confirm the expected failures**

    py -3 -m unittest tests.test_state_and_orchestrator -v

Expected: FAIL because the state store and orchestrator are not implemented.

- [ ] **Step 3: Implement atomic state storage**

Use `PLUGIN_DATA/tasks` as the root, encode identity with URL-safe Base64 or a SHA-256 digest, write UTF-8 JSON to a sibling `.tmp` file, then call `os.replace`. Store `repo_root`, `base_tree`, `prompt`, `created_at`, and a config version. If a JSON file is corrupt, return a typed missing-state result; never reconstruct from Git HEAD.

- [ ] **Step 4: Implement the two Hook paths and entrypoint**

`UserPromptSubmit` locates the same repository root used by `cwd`, captures BASE, and stores state. `Stop` validates `stop_hook_active`, loads the matching state, verifies the repo root, captures FINAL and Diff before any report directory write, then returns a placeholder `status=ready_for_classification` system message. All exceptions are converted to a safe JSON response and exit code 0 so the main Agent can finish.

- [ ] **Step 5: Verify subprocess entrypoint behavior**

Run:

    '{"hook_event_name":"UserPromptSubmit","session_id":"s","turn_id":"t","cwd":"E:\\YilenaCode\\codex_task_hook","prompt":"add a feature"}' | py -3 hooks/task_review.py
    '{"hook_event_name":"Stop","session_id":"missing","turn_id":"t","cwd":"E:\\YilenaCode\\codex_task_hook","stop_hook_active":false,"last_assistant_message":null}' | py -3 hooks/task_review.py

Expected: both commands print one JSON object with `continue: true`; the second includes a missing-state reason and does not run `git diff HEAD`.

- [ ] **Step 6: Run the full suite and commit**

    py -3 -m unittest discover -s tests -v
    git add codex_task_review/state.py codex_task_review/orchestrator.py codex_task_review/models.py hooks/task_review.py tests/test_state_and_orchestrator.py
    git commit -m "feat：隔离任务状态并接入双 Hook 生命周期"

### Task 5: Implement deterministic task classification and skip rules

**Files:**
- Create: `codex_task_review/classifier.py`
- Create: `tests/test_classifier.py`

**Interfaces:**
- `classify_task(prompt: str, diff: DiffResult, config: ReviewConfig) -> ClassificationResult` returns `kind`, `should_review`, `reason`, `changed_files`, `changed_lines`, and `risk_evidence`.

- [x] **Step 1: Write failing tests for every required classification branch**

Add tests for no changes, small explicit Bug fix, oversized Bug fix, three-file threshold, pure CSS/SCSS/UI text changes, JSX with API/state/validation/persistence logic, new feature, refactor, high-risk paths/keywords, and `[review:force]` overriding every skip.

- [x] **Step 2: Run the classifier tests and confirm the missing implementation failure**

    py -3 -m unittest tests.test_classifier -v

Expected: FAIL because `classify_task` is not defined.

- [x] **Step 3: Implement the priority-ordered classifier**

Normalize prompt and paths case-insensitively, detect force marker first, then no Diff, risk evidence, business logic in UI files, pure UI, simple Bug fix, and default review. Count changed files and `abs(additions) + abs(deletions)` from `DiffResult`; keep risk lists configurable and use conservative default keywords/paths. Add Chinese comments explaining why high-risk evidence wins over skip heuristics.

- [x] **Step 4: Run focused and full tests**

    py -3 -m unittest tests.test_classifier -v
    py -3 -m unittest discover -s tests -v

Expected: all classification assertions and earlier tests pass.

- [x] **Step 5: Integrate classification into Stop orchestration and commit**

Make Stop return a skip message without invoking Reviewer when `should_review` is false; for reviewable changes, pass the immutable `DiffResult` to the next slice.

    git add codex_task_review/classifier.py codex_task_review/orchestrator.py tests/test_classifier.py
    git commit -m "feat：增加确定性任务分类与跳过规则"

### Task 6: Implement read-only Reviewer isolation and failure-safe execution

**Files:**
- Create: `codex_task_review/reviewer.py`
- Create: `tests/test_reviewer.py`
- Modify: `codex_task_review/orchestrator.py`

**Interfaces:**
- `ReviewRunner.run(repo_root: Path, final_tree: str, diff: DiffResult, prompt: str, config: ReviewConfig) -> ReviewResult`.
- `ReviewResult(status: str, raw_output: str, error: str | None, workspace: Path | None)` is serializable for report generation.

- [x] **Step 1: Write failing tests for isolated Review behavior**

Use an injectable process runner to assert the command receives `--sandbox read-only`, `review`, and `-`; cwd is not the user repository; stdin contains the exact Diff; `CODEX_TASK_REVIEW_ACTIVE=1` is present; and the original repository files/Index remain byte-for-byte unchanged. Add timeout, missing executable, nonzero exit, and recursive-environment tests.

- [x] **Step 2: Run the Reviewer tests and confirm expected failures**

    py -3 -m unittest tests.test_reviewer -v

Expected: FAIL because `ReviewRunner` and `ReviewResult` are not implemented.

- [x] **Step 3: Implement temporary FINAL workspace creation**

Call `GitSnapshotter.export_tree(final_tree, temp_workspace)`, run `git init --initial-branch=main`, use command-scoped author identity and an empty isolated Git config, `git add -A`, and create one local commit. Never copy or expose the original `.git` directory. Delete the workspace in `finally` unless the test explicitly asks to retain a diagnostic path.

- [x] **Step 4: Implement the `codex review -` process**

Build a prompt that states the task description, BASE/FINAL IDs, changed file list, exact Diff, P0–P3 definitions, evidence/line-number requirements, and “read-only report-only; do not edit files”. Run `codex --sandbox read-only review -` from the temporary workspace with stdin bytes/text, timeout from config, and `CODEX_TASK_REVIEW_ACTIVE=1`. Convert every process failure to `ReviewResult(status="failed", ...)` without raising through Stop.

- [x] **Step 5: Verify isolation, failure safety, and full tests**

    py -3 -m unittest tests.test_reviewer -v
    py -3 -m unittest discover -s tests -v

Expected: Review tests pass; no user project mutation is observed.

- [x] **Step 6: Commit the Reviewer slice**

    git add codex_task_review/reviewer.py codex_task_review/orchestrator.py tests/test_reviewer.py
    git commit -m "feat：隔离执行只读 Codex Reviewer"

### Task 7: Generate Markdown reports and complete Stop lifecycle

**Files:**
- Create: `codex_task_review/report.py`
- Create: `codex_task_review/report_format.py`
- Create: `tests/report_helpers.py`
- Create: `tests/test_report_format.py`
- Create: `tests/test_report_writer.py`
- Create: `tests/test_report_lifecycle.py`
- Modify: `codex_task_review/orchestrator.py`
- Modify: `codex_task_review/reviewer.py`

**Interfaces:**
- `ReviewReportWriter.write(repo_root: Path, config: ReviewConfig, task: TaskState, diff: DiffResult, classification: ClassificationResult, result: ReviewResult) -> Path`.
- `format_report(...) -> str` always includes P0, P1, P2, P3 headings, even when no issue is returned.

- [x] **Step 1: Write failing tests for report structure and timing boundary**

Assert report path format `.codex/reviews/code-review-YYYY-MM-DD-HH-mm-ss.md`, UTF-8 output, task description, BASE/FINAL Tree IDs, file list, classification, all four severity sections, checked/unchecked sections, raw Reviewer output, and failed Reviewer reason. Use a spy to assert `write()` is called only after `GitSnapshotter.diff()` returns.

- [x] **Step 2: Run report tests and verify the missing implementation failure**

    py -3 -m unittest tests.test_report_format tests.test_report_writer tests.test_report_lifecycle -v

Expected: FAIL because `ReviewReportWriter` is not implemented.

- [x] **Step 3: Implement deterministic Markdown generation**

Render paths with forward slashes, escape raw Markdown code fences where needed, include “未发现” for empty P0–P3 sections, and preserve raw Reviewer output under a bounded section. Create the report directory only after BASE/FINAL/Diff are captured; write atomically with UTF-8 and never call Git staging APIs.

- [x] **Step 4: Finish Stop orchestration and cleanup**

For no Diff or skipped classifications, output a reason and remove only the current task state. For reviewable Diff, call Reviewer, write success/failed report, remove only the current state, and return `continue: true`. If report writing fails, return a failure message without rerunning snapshot/Diff or blocking the Agent.

- [x] **Step 5: Run focused and full suites**

    py -3 -m unittest tests.test_report_format tests.test_report_writer tests.test_report_lifecycle -v
    py -3 -m unittest discover -s tests -v

Expected: all report, lifecycle, snapshot, classification, and Reviewer tests pass.

- [x] **Step 6: Commit reports and lifecycle completion in reviewable slices**

Keep report formatting, file writing, and Stop integration in separate commits so each commit remains independently testable:

    git add codex_task_review/report_format.py codex_task_review/reviewer.py tests/report_helpers.py tests/test_report_format.py
    git commit -m "feat: 生成 Markdown Review 报告内容"
    git add codex_task_review/report.py tests/test_report_writer.py
    git commit -m "feat: 安全写入 Markdown Review 报告"
    git add codex_task_review/report.py
    git commit -m "fix: 避免跨平台覆盖同名审查报告"
    git add codex_task_review/orchestrator.py tests/test_report_lifecycle.py docs/superpowers/plans/2026-11-24-codex-task-review.md
    git commit -m "feat: 在 Stop 生命周期中保存审查报告"

The writer uses an exclusive same-directory hard-link creation from a fully flushed temporary file, avoiding `os.rename` overwrite behavior on POSIX while preserving collision suffixes on Windows and Unix.

### Task 8: Add official plugin manifests, Hooks, Marketplace, examples, and README

**Files:**
- Create: `.codex-plugin/plugin.json`
- Create: `hooks/hooks.json`
- Create: `.agents/plugins/marketplace.json`
- Create: `examples/task-review.json`
- Create: `examples/code-review-example.md`
- Create: `assets/codex-task-review.svg`
- Create: `README.md`

**Interfaces:**
- The Codex compatibility manifest uses plugin name `codex-task-review` and version `0.1.0`; omit a root portable manifest because the current Codex loader skips bundled hooks for Agent Plugins format.
- Marketplace name is `codex-task-review-marketplace`; its Git-backed root source URL is `https://github.com/YOUR_GITHUB_USERNAME/codex-task-review.git`, with `ref: "main"`.

- [ ] **Step 1: Write failing manifest and documentation validation tests**

Add `tests/test_package_layout.py` that loads JSON and asserts the Codex compatibility manifest identity and hook path, absence of the root portable manifest, both Hook events, `commandWindows` containing `py -3`, Marketplace name/version/source URL placeholder, no hard-coded `C:\Users\` path, README installation/update/uninstall commands, and example report headings.

- [ ] **Step 2: Run package layout tests and confirm expected failures**

    py -3 -m unittest tests.test_package_layout -v

Expected: the four packaging checks error because the required manifest, Hook, Marketplace, example, and README files do not exist.

- [x] **Step 3: Implement the Codex compatibility manifest**

Use `.codex-plugin/plugin.json` as the primary Codex manifest and declare `hooks: "./hooks/hooks.json"` there. Do not add root `plugin.json`: current Codex source selects the Agent Plugins format from that root manifest and skips bundled Hook loading for that format. Do not include secrets or fake publisher identity.

- [x] **Step 4: Register Windows-safe Hooks**

Use this shape in `hooks/hooks.json`:

    {
      "hooks": {
        "UserPromptSubmit": [
          {
            "hooks": [
              {
                "type": "command",
                "command": "python3 \\\"${PLUGIN_ROOT}/hooks/task_review.py\\\"",
                "commandWindows": "py -3 \"${PLUGIN_ROOT}\\hooks\\task_review.py\"",
                "timeout": 30,
                "statusMessage": "Capturing task review snapshot"
              }
            ]
          }
        ],
        "Stop": [
          {
            "hooks": [
              {
                "type": "command",
                "command": "python3 \\\"${PLUGIN_ROOT}/hooks/task_review.py\\\"",
                "commandWindows": "py -3 \"${PLUGIN_ROOT}\\hooks\\task_review.py\"",
                "timeout": 600,
                "statusMessage": "Reviewing task changes"
              }
            ]
          }
        ]
      }
    }

The entrypoint reads `PLUGIN_DATA` and `PLUGIN_ROOT` from the process environment; no user path is embedded.

- [x] **Step 5: Add Marketplace, config example, report example, icon, and Chinese README**

README must contain project introduction, workflow, requirements, structure, installation, update, uninstall, configuration, skip rules, report example, FAQ, Windows troubleshooting, GitHub publishing commands, compatibility-manifest rationale, and these copyable commands:

    codex plugin marketplace add YOUR_GITHUB_USERNAME/codex-task-review --ref main
    codex plugin add codex-task-review@codex-task-review-marketplace
    codex plugin marketplace upgrade codex-task-review-marketplace
    git remote add origin https://github.com/YOUR_GITHUB_USERNAME/codex-task-review.git
    git branch -M main
    git push -u origin main

Explain that lifecycle hooks are suited to GitHub-backed/manual Codex installation and require user trust; do not claim automatic public directory eligibility.

- [x] **Step 6: Run package tests and commit packaging**

    py -3 -m unittest tests.test_package_layout -v
    git add .codex-plugin hooks/hooks.json .agents/plugins/marketplace.json examples assets README.md tests/test_package_layout.py docs/superpowers/specs/2026-11-24-codex-task-review-design.md docs/superpowers/plans/2026-11-24-codex-task-review.md
    git commit -m "feat: 完成 Codex 插件与 Marketplace 打包"

### Task 9: Complete Windows-oriented integration coverage and release verification

**Files:**
- Create: `tests/test_integration.py`
- Create: `.github/workflows/tests.yml`
- Modify: `README.md` only for observed command/output corrections

**Interfaces:**
- The public verification command is `py -3 -m unittest discover -s tests -v`.
- The project does not add a test-only dependency or require the user’s real repository.

- [ ] **Step 1: Write failing end-to-end tests for the complete Hook flow**

In a temporary Git repository with a pre-existing dirty file, invoke `hooks/task_review.py` twice with different identities, mutate staged/unstaged files, stop one task, and assert only that task’s Diff appears in the generated report. Assert the report is written after the FINAL snapshot and Diff so it cannot enter that same task’s Diff, and that the user Git Index remains unchanged. Add a fake Reviewer so the suite is offline and deterministic.

- [ ] **Step 2: Run the integration tests and fix only product defects**

    py -3 -m unittest tests.test_integration -v

Expected: initially failing integration assertions identify missing wiring; do not weaken assertions or remove valid scenarios.

- [ ] **Step 3: Run the complete verification set**

    py -3 -m unittest discover -s tests -v
    git diff --check
    python -m json.tool .codex-plugin/plugin.json > $null
    python -m json.tool hooks/hooks.json > $null
    python -m json.tool .agents/plugins/marketplace.json > $null
    git status --short

Expected: all tests pass, all JSON commands exit 0, no whitespace errors, and only intentional local changes are present.

- [ ] **Step 4: Inspect the final diff for prohibited behavior**

    git grep -n -E "git (reset|checkout|clean)|git diff (HEAD|main|origin/main)|C:\\Users\\|OPENAI_API_KEY|decision\\\"\\s*:\\s*\\\"block" -- . ':(exclude).git'

Expected: no prohibited implementation matches; the only allowed `YOUR_GITHUB_USERNAME` placeholder remains in metadata/docs.

- [ ] **Step 5: Commit final verification and documentation corrections**

    git add tests README.md
    git commit -m "test：完成 Windows 集成验证与发布检查"

- [ ] **Step 6: Report real evidence and known limits**

Report local commit list, exact test command/output summary, plugin files, documentation path, and unverified production behavior such as a real installed plugin trust flow, live GitHub fetch, and a live remote Reviewer call if those were not executed.

## Plan self-review

- Spec coverage: Tasks 2–4 cover Hook contracts, state isolation, no-HEAD/error handling, and exact temporary-index Diff; Task 5 covers every classification branch; Tasks 6–7 cover isolated Review, report format, recursion, timeout, and report timing; Task 8 covers plugin, hooks, Marketplace, configuration, README, and examples; Task 9 covers all listed integration behaviors.
- Placeholder scan: `YOUR_GITHUB_USERNAME` is an intentional user-facing publishing placeholder required by the spec; no implementation step is left as TODO/TBD.
- Type consistency: `DiffResult`, `ClassificationResult`, `ReviewResult`, `TaskState`, `HookInput`, and `ReviewConfig` are defined in Task 2 and consumed by later tasks with the same names and fields.
