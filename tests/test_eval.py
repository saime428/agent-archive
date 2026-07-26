from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from typer.testing import CliRunner

import agent.core.eval as eval_module
from agent.cli import app
from agent.core.eval import EvalError, deterministic_signature, run_reference_eval


EXPECTED_SIGNATURE = (
    ("direct_completion", True, True, "done", "ok", None, 0, 0),
    ("read_then_finish", True, True, "done", "ok", None, 1, 0),
    ("recover_after_missing_file", True, True, "done", "ok", None, 2, 1),
    ("approval_stays_blocked", True, False, "write_file", "error", "APPROVAL_REQUIRED", 1, 1),
)


def test_reference_eval_is_deterministic_and_ignores_workspace_runtime_config(tmp_path: Path) -> None:
    agent_root = tmp_path / ".agent"
    agent_root.mkdir()
    (agent_root / "config.toml").write_text(
        'provider = "deepseek"\ndefault_skills = ["missing-skill"]\nenabled_hooks = ["fail"]\n',
        encoding="utf-8",
    )
    (agent_root / "secrets.env").write_text("DEEPSEEK_API_KEY=eval-must-ignore-this\n", encoding="utf-8")

    first = run_reference_eval(tmp_path)
    second = run_reference_eval(tmp_path)

    assert first.passed is True
    assert first.total_cases == 4
    assert first.passed_cases == 4
    assert first.failed_cases == 0
    assert first.completed_cases == 3
    assert first.tool_calls == 4
    assert first.errors == 2
    assert deterministic_signature(first) == EXPECTED_SIGNATURE
    assert deterministic_signature(second) == EXPECTED_SIGNATURE
    assert first.eval_id != second.eval_id
    assert first.report_path != second.report_path

    payload = json.loads(first.report_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "agent-eval-v1"
    assert payload["passed"] is True
    assert payload["totals"] == {
        "cases": 4,
        "passed": 4,
        "failed": 0,
        "completed": 3,
        "tool_calls": 4,
        "errors": 2,
        "duration_ms": first.duration_ms,
    }
    assert "eval-must-ignore-this" not in first.report_path.read_text(encoding="utf-8")
    for case in first.cases:
        if case.summary_path is not None:
            assert (first.report_path.parent / case.summary_path).is_file()
    assert not (first.report_path.parent / "cases" / "approval_stays_blocked" / "blocked.txt").exists()


def test_reference_eval_bounds_redacts_and_reports_case_execution_failures(tmp_path: Path, monkeypatch) -> None:
    def fail_run(*_args, **_kwargs):
        raise RuntimeError("Bearer secret-token\n" + "failure " * 400)

    monkeypatch.setattr(eval_module, "run_once", fail_run)

    report = run_reference_eval(tmp_path)

    assert report.passed is False
    assert report.failed_cases == 4
    for case in report.cases:
        assert case.passed is False
        assert case.failure_detail is not None
        assert len(case.failure_detail) <= 2_000
        assert "[REDACTED]" in case.failure_detail
        assert "secret-token" not in case.failure_detail
        assert case.failure_detail.endswith("[truncated]")
    serialized = report.report_path.read_text(encoding="utf-8")
    assert "secret-token" not in serialized

    monkeypatch.setattr("agent.cli.run_reference_eval", lambda _workspace: report)
    result = CliRunner().invoke(app, ["eval", "run", "--cwd", str(tmp_path)])

    assert result.exit_code == 1
    assert "passed: 0 failed: 4" in result.output
    assert "[REDACTED]" in result.output
    assert "Traceback" not in result.output


def test_reference_eval_rejects_linked_storage(tmp_path: Path) -> None:
    agent_root = tmp_path / ".agent"
    agent_root.mkdir()
    external = tmp_path / "external-evals"
    external.mkdir()
    try:
        (agent_root / "evals").symlink_to(external, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlinks are not available on this host.")

    with pytest.raises(EvalError, match="real directory"):
        run_reference_eval(tmp_path)


def test_reference_eval_rejects_duplicate_case_ids_before_writing(tmp_path: Path, monkeypatch) -> None:
    duplicate = eval_module._REFERENCE_CASES[0]
    monkeypatch.setattr(eval_module, "_REFERENCE_CASES", (duplicate, duplicate))

    with pytest.raises(EvalError, match="duplicate eval case id"):
        run_reference_eval(tmp_path)
    assert not (tmp_path / ".agent").exists()


def test_reference_eval_reports_metric_mismatch_and_cli_exits_nonzero(tmp_path: Path, monkeypatch) -> None:
    mismatched = replace(eval_module._REFERENCE_CASES[0], expected_tool_calls=1)
    monkeypatch.setattr(eval_module, "_REFERENCE_CASES", (mismatched, *eval_module._REFERENCE_CASES[1:]))

    report = run_reference_eval(tmp_path)

    assert report.passed is False
    assert report.failed_cases == 1
    assert report.cases[0].failure_detail == "tool_calls: expected 1, got 0"

    monkeypatch.setattr("agent.cli.run_reference_eval", lambda _workspace: report)
    result = CliRunner().invoke(app, ["eval", "run", "--cwd", str(tmp_path)])

    assert result.exit_code == 1
    assert "passed: 3 failed: 1" in result.output
    assert "detail: tool_calls: expected 1, got 0" in result.output
    assert "Traceback" not in result.output


def test_reference_eval_report_publish_is_atomic_and_cli_success_is_stable(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    cli_workspace = tmp_path / "cli"
    cli_workspace.mkdir()

    result = runner.invoke(app, ["eval", "run", "--cwd", str(cli_workspace)])

    assert result.exit_code == 0
    assert "passed: 4 failed: 0 completed: 3 tool_calls: 4 errors: 2" in result.output
    assert "report: .agent/evals/eval_" in result.output
    assert len(list((cli_workspace / ".agent" / "evals").glob("eval_*/report.json"))) == 1

    atomic_workspace = tmp_path / "atomic"
    atomic_workspace.mkdir()

    def fail_replace(_source, _target) -> None:
        raise OSError("injected replace failure")

    monkeypatch.setattr("agent._user_store.os.replace", fail_replace)

    with pytest.raises(EvalError, match="publish eval report"):
        run_reference_eval(atomic_workspace)
    assert not list((atomic_workspace / ".agent" / "evals").glob("eval_*/report.json"))
