from typer.testing import CliRunner

from agent.cli import app


def test_doctor_reports_python_and_cwd() -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "Python" in result.output
    assert "cwd" in result.output
