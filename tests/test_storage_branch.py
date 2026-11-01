"""
Tests for :class:`basstler_domain_model.git.storage_branch.StorageBranch`: a branch read
and written without a checkout, by several writers.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from basstler_domain_model.git.commands import GitCommandRunner
from basstler_domain_model.git.storage_branch import StorageBranch

# %% fixtures


@pytest.fixture
def remote(tmp_path: Path) -> Path:
    """:return: A bare repository holding one commit on ``main``."""
    bare = tmp_path / "remote.git"
    GitCommandRunner(tmp_path).run(
        "init", "--quiet", "--bare", "--initial-branch=main", str(bare)
    )
    seed = GitCommandRunner(tmp_path / "seed")
    seed.working_directory.mkdir()
    seed.run("init", "--quiet", "--initial-branch=main")
    identify(seed)
    seed.run("commit", "--quiet", "--allow-empty", "--message", "Start")
    seed.run("push", "--quiet", str(bare), "HEAD:refs/heads/main")
    return bare


def identify(git: GitCommandRunner) -> None:
    """:param git: A checkout to commit in."""
    git.run("config", "user.name", "Test Author")
    git.run("config", "user.email", "test.author@example.com")


def storage(remote: Path, tmp_path: Path, name: str) -> StorageBranch:
    """
    :param remote: The bare repository.
    :param tmp_path: Where to clone it.
    :param name: The clone's directory name.
    :return: The storage branch, as that clone uses it.
    """
    git = GitCommandRunner(tmp_path)
    git.run("clone", "--quiet", str(remote), name)
    clone = GitCommandRunner(tmp_path / name)
    identify(clone)
    return StorageBranch(clone, "origin", "storage", "refs/storage/branch")


# %% reading and writing


def test_before_the_first_write_there_is_nothing_to_read(remote, tmp_path):
    branch = storage(remote, tmp_path, "reader")

    assert branch.fetch() is False
    assert branch.read(Path("file.md")) is None


def test_the_first_write_creates_the_branch_with_the_file(remote, tmp_path):
    storage(remote, tmp_path, "writer").write({Path("file.md"): "text\n"}, "Write")
    reader = storage(remote, tmp_path, "reader")

    assert reader.fetch() is True
    assert reader.read(Path("file.md")) == "text"


def test_a_write_leaves_the_files_it_does_not_write_alone(remote, tmp_path):
    branch = storage(remote, tmp_path, "writer")
    branch.write({Path("one.md"): "one\n"}, "Write")

    branch.write({Path("two.md"): "two\n"}, "Write")

    assert branch.read(Path("one.md")) == "one"
    assert branch.read(Path("two.md")) == "two"


def test_a_writer_behind_another_keeps_both_writes(remote, tmp_path):
    """
    The later writer fetched before the earlier one wrote, so its first push is refused
    and it builds again on the new tip.
    """
    first = storage(remote, tmp_path, "first")
    second = storage(remote, tmp_path, "second")
    first.write({Path("one.md"): "one\n"}, "Write")
    second.fetch()
    first.write({Path("two.md"): "two\n"}, "Write")

    second.write({Path("three.md"): "three\n"}, "Write")

    assert second.read(Path("two.md")) == "two"
    assert second.read(Path("three.md")) == "three"


def test_a_write_leaves_the_checkout_untouched(remote, tmp_path):
    branch = storage(remote, tmp_path, "writer")
    before = branch.git.run("status", "--porcelain"), branch.git.run(
        "rev-parse", "HEAD"
    )

    branch.write({Path("file.md"): "text\n"}, "Write")

    assert (
        branch.git.run("status", "--porcelain"),
        branch.git.run("rev-parse", "HEAD"),
    ) == before
