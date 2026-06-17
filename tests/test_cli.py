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
