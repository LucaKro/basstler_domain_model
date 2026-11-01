"""
Tests for :mod:`basstler_domain_model.commands`: a command's result, whether or not it
could run.
"""

from __future__ import annotations

import sys

from basstler_domain_model.commands import CommandRunner

# %% running


def test_a_finished_command_keeps_its_output(tmp_path):
    result = CommandRunner(tmp_path).run(sys.executable, "-c", "print('done')")

    assert result.succeeded
    assert result.output == "done"


def test_a_failing_command_keeps_its_status_and_error_output(tmp_path):
    result = CommandRunner(tmp_path).run(
        sys.executable, "-c", "import sys; sys.exit('broken')"
    )

    assert result.exit_status == 1
    assert result.error_output == "broken"


def test_a_command_that_is_not_installed_comes_back_as_a_result(tmp_path):
    result = CommandRunner(tmp_path).run("a-command-that-does-not-exist")

    assert not result.succeeded
    assert result.exit_status is None
