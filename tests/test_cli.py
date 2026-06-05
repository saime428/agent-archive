from typer.testing import CliRunner

from agent.cli import app


def test_doctor_reports_python_and_cwd() -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "Python" in result.output
    assert "cwd" in result.output


def test_run_reports_task_and_not_implemented_status() -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["run", "inspect project"])

    assert result.exit_code == 0
    assert "inspect project" in result.output
    assert "not implemented" in result.output
