"""Console entrypoint behavior."""
from __future__ import annotations

from servo_agent.cli import main


def test_help_exits_successfully(capsys) -> None:
    assert main(["--help"]) == 0
    out = capsys.readouterr().out
    assert "Usage:" in out
    assert "servo-agent serve" in out


def test_unknown_command_exits_with_usage_hint(capsys) -> None:
    assert main(["nope"]) == 2
    err = capsys.readouterr().err
    assert "unknown command" in err
    assert "selftest" in err


def test_install_servo_passes_the_version_and_reports_failure(monkeypatch, capsys) -> None:
    import servo_agent.engines as engines

    asked: list[str | None] = []

    def failing_install(version=None):
        asked.append(version)
        raise engines.EngineInstallError("no installable Servo build for Darwin arm64")

    monkeypatch.setattr(engines, "install", failing_install)

    assert main(["install-servo", "--version", "0.7.0"]) == 1
    assert asked == ["0.7.0"]
    assert "no installable Servo build" in capsys.readouterr().err
    assert main(["install-servo", "--version"]) == 2
