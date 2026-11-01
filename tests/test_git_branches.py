"""
Tests for the git side of working with branches: the remotes, committing files without a
checkout, and replaying a stack of branches onto a moved base.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from basstler_domain_model.git.exceptions import GitCommandFailed
from basstler_domain_model.git.commands import (
    GitCommandRunner,
    RemoteBranch,
    RemoteName,
)

# %% fixtures


@pytest.fixture
def checkout(tmp_path: Path) -> GitCommandRunner:
    """:return: A checkout with one commit on ``main``, and an identity to commit as."""
    git = GitCommandRunner(tmp_path / "checkout")
    git.working_directory.mkdir()
    git.run("init", "--quiet", "--initial-branch=main")
    git.run("config", "user.name", "Test Author")
    git.run("config", "user.email", "test.author@example.com")
    (git.working_directory / "README.md").write_text("start\n")
    git.run("add", "README.md")
    git.run("commit", "--quiet", "--message", "Start")
    return git


def commit_on(git: GitCommandRunner, branch: str, start: str, name: str) -> None:
    """
    :param git: The checkout.
    :param branch: The branch to create and commit on.
    :param start: Where it starts.
    :param name: The file the commit adds, and its message.
    """
    git.run("switch", "--quiet", "--create", branch, start)
    (git.working_directory / name).write_text(f"{name}\n")
    git.run("add", name)
    git.run("commit", "--quiet", "--message", name)


# %% remotes


def test_a_remote_names_the_repository_it_pushes_to(checkout: GitCommandRunner):
    checkout.run(
        "remote", "add", "origin", "https://github.com/an-owner/a-repository.git"
    )

    [remote] = checkout.remotes()

    assert remote.repository is not None
    assert remote.repository.full_name == "an-owner/a-repository"


def test_a_remote_that_names_no_repository_has_none(checkout: GitCommandRunner):
    checkout.run("remote", "add", "local", "/a/plain/path")

    assert checkout.remotes()[0].repository is None


@pytest.fixture
def published(checkout: GitCommandRunner, tmp_path: Path) -> RemoteBranch:
    """:return: ``main``, pushed to a bare ``origin`` of the checkout."""
    remote = tmp_path / "remote.git"
    checkout.run("init", "--quiet", "--bare", str(remote))
    checkout.run("remote", "add", RemoteName.ORIGIN, str(remote))
    branch = RemoteBranch(RemoteName.ORIGIN, "main")
    checkout.run("push", "--quiet", branch.remote, f"HEAD:{branch.reference}")
    return branch


def test_a_pushed_branch_is_on_its_remote(
    checkout: GitCommandRunner, published: RemoteBranch
):
    assert checkout.has_remote_branch(published)


def test_a_branch_never_pushed_is_not_on_the_remote(
    checkout: GitCommandRunner, published: RemoteBranch
):
    assert not checkout.has_remote_branch(RemoteBranch(published.remote, "elsewhere"))


def test_a_deleted_branch_is_gone_from_its_remote(
    checkout: GitCommandRunner, published: RemoteBranch
):
    deleted = checkout.delete_remote_branch(published)

    assert deleted.succeeded
    assert not checkout.has_remote_branch(published)


def test_a_fetched_branch_moves_only_its_tracking_reference(
    checkout: GitCommandRunner, published: RemoteBranch
):
    checkout.fetch_branch(published.remote, published.name, published.remote)

    assert checkout.commit_at(published.tracking_reference) == checkout.commit_at(
        "HEAD"
    )


# %% committing without a checkout


def test_a_commit_of_files_leaves_the_checkout_untouched(checkout: GitCommandRunner):
    before = checkout.run("status", "--porcelain")

    commit = checkout.commit_files(None, {Path("notes.md"): "a note\n"}, "Save")

    assert checkout.run("show", f"{commit}:notes.md") == "a note"
    assert checkout.run("status", "--porcelain") == before


def test_a_commit_on_a_parent_keeps_the_parent_s_files(checkout: GitCommandRunner):
    parent = checkout.commit_files(None, {Path("notes.md"): "a note\n"}, "Save")

    commit = checkout.commit_files(
        parent, {Path("progress/a.md"): "progress\n"}, "Save"
    )

    assert checkout.run("show", f"{commit}:notes.md") == "a note"
    assert checkout.run("rev-parse", f"{commit}^") == parent


# %% restacking


def test_a_stack_is_replayed_onto_its_moved_base_branch_by_branch(
    checkout: GitCommandRunner,
):
    commit_on(checkout, "lower", "main", "lower.txt")
    commit_on(checkout, "upper", "lower", "upper.txt")
    commit_on(checkout, "base-moved", "main", "base.txt")

    result = checkout.rebase_stack("base-moved", "upper")

    assert result.succeeded
    assert checkout.contains("base-moved", "lower")
    assert checkout.contains("lower", "upper")


# %% working on branches


def test_a_created_branch_is_checked_out_at_its_start(checkout: GitCommandRunner):
    start = checkout.commit_at("HEAD")

    checkout.create_branch("feature", "main")

    assert checkout.checked_out_branch() == "feature"
    assert checkout.commit_at("HEAD") == start


def test_creating_a_branch_that_exists_is_refused(checkout: GitCommandRunner):
    with pytest.raises(GitCommandFailed):
        checkout.create_branch("main", "main")


def test_switching_checks_the_branch_out(checkout: GitCommandRunner):
    commit_on(checkout, "feature", "main", "feature.txt")

    checkout.switch_to("main")

    assert checkout.checked_out_branch() == "main"


def test_a_commit_holds_the_named_paths_only(checkout: GitCommandRunner):
    (checkout.working_directory / "kept.txt").write_text("kept\n")
    (checkout.working_directory / "left.txt").write_text("left\n")

    commit = checkout.commit("Keep one", [Path("kept.txt")])

    assert checkout.run("show", "--name-only", "--format=", commit) == "kept.txt"
    assert checkout.run("status", "--porcelain") == "?? left.txt"


def test_a_branch_behind_fast_forwards(checkout: GitCommandRunner):
    commit_on(checkout, "ahead", "main", "ahead.txt")
    checkout.switch_to("main")

    assert checkout.fast_forward("ahead").succeeded
    assert checkout.commit_at("main") == checkout.commit_at("ahead")


def test_a_diverged_branch_does_not_fast_forward(checkout: GitCommandRunner):
    commit_on(checkout, "other", "main", "other.txt")
    commit_on(checkout, "mine", "main", "mine.txt")

    assert not checkout.fast_forward("other").succeeded
    assert checkout.contains("mine", "HEAD")


def test_a_kept_reset_keeps_uncommitted_changes(checkout: GitCommandRunner):
    commit_on(checkout, "rewritten", "main", "rewritten.txt")
    commit_on(checkout, "mine", "main", "mine.txt")
    (checkout.working_directory / "README.md").write_text("edited\n")

    checkout.reset_kept("rewritten")

    assert checkout.commit_at("HEAD") == checkout.commit_at("rewritten")
    assert (checkout.working_directory / "README.md").read_text() == "edited\n"


@pytest.mark.parametrize("already_staged", [False, True])
def test_a_commit_of_a_removed_path_removes_it(
    checkout: GitCommandRunner, already_staged: bool
):
    (checkout.working_directory / "README.md").unlink()
    if already_staged:
        checkout.run("rm", "--quiet", "--cached", "README.md")

    commit = checkout.commit("Remove the readme", [Path("README.md")])

    assert checkout.run("ls-tree", "--name-only", commit) == ""


def test_a_remote_branch_s_tip_is_the_commit_pushed(
    checkout: GitCommandRunner, published: RemoteBranch
):
    assert checkout.remote_branch_tip(published) == checkout.commit_at("HEAD")


def test_a_branch_the_remote_lacks_has_no_tip(
    checkout: GitCommandRunner, published: RemoteBranch
):
    assert (
        checkout.remote_branch_tip(RemoteBranch(published.remote, "elsewhere")) is None
    )
