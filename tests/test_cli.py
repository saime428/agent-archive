from pathlib import Path

from typer.testing import CliRunner

from agent.cli import app


def test_doctor_reports_python_and_cwd() -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "Python" in result.output
    assert "cwd" in result.output


def test_run_reports_fake_llm_result() -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["run", "inspect project"])

    assert result.exit_code == 0
    assert "inspect project" in result.output
    assert "run_id:" in result.output
    assert "final:" in result.output
    assert "summary:" in result.output


def test_runs_list_reports_no_runs(tmp_path) -> None:
    runner = CliRunner()

    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(app, ["runs", "list"])

    assert result.exit_code == 0
    assert "No runs found" in result.output


def test_runs_list_outputs_existing_run(tmp_path) -> None:
    runner = CliRunner()

    with runner.isolated_filesystem(temp_dir=tmp_path):
        run_dir = Path.cwd() / ".agent" / "runs" / "run_test"
        run_dir.mkdir(parents=True)
        (run_dir / "summary.md").write_text("# Run run_test\n", encoding="utf-8")
        (run_dir / "tool_calls.jsonl").write_text("", encoding="utf-8")
        result = runner.invoke(app, ["runs", "list"])

    assert result.exit_code == 0
    assert "run_test" in result.output


def test_runs_show_outputs_summary_snapshots_and_restore(tmp_path) -> None:
    runner = CliRunner()

    with runner.isolated_filesystem(temp_dir=tmp_path):
        run_dir = Path.cwd() / ".agent" / "runs" / "run_test"
        run_dir.mkdir(parents=True)
        (run_dir / "summary.md").write_text("# Run run_test\n\n- final: ok\n", encoding="utf-8")
        (run_dir / "tool_calls.jsonl").write_text(
            '{"action":{"action":{"name":"write_file"}},"observation":{"status":"ok",'
            '"data":{"path":"notes.txt","snapshot_path":".agent/runs/run_test/snapshots/act/original",'
            '"restore_hint":"Restore by copying original back."}}}\n',
            encoding="utf-8",
        )
        result = runner.invoke(app, ["runs", "show", "run_test"])

    assert result.exit_code == 0
    assert "Run run_test" in result.output
    assert "tool calls: 1" in result.output
    assert "snapshot" in result.output
    assert "Restore by copying" in result.output


def test_runs_show_missing_run_returns_nonzero(tmp_path) -> None:
    runner = CliRunner()

    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(app, ["runs", "show", "run_missing"])

    assert result.exit_code != 0
    assert "Run not found" in result.output
