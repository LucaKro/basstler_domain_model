"""
Running git in one checkout, and what a push is allowed to overwrite.

Every command goes through :class:`GitCommandRunner`, and every push is built as a
:class:`ProposedPush` - so whether published history may be rewritten is decided in one
place rather than at each call site.
"""

from __future__ import annotations

import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from basstler_domain_model.commands import CommandResult, CommandRunner
from basstler_domain_model.environment import GitVariable
from basstler_domain_model.repository import Repository
from basstler_domain_model.git.exceptions import (
    GitCommandFailed,
    UnresolvableReferenceError,
)

# %% how one branch takes in another


class IntegrationStrategy(StrEnum):
    """
    How a branch takes in another branch's commits, each named as the git command that
    does it.
    """

    MERGE = "merge"
    """
    Merge the other branch's tip in, keeping the branch's published history.
    """

    REBASE = "rebase"
    """
    Replay the branch onto the other branch's tip, which rewrites published history.
    """


# %% running git


@dataclass(frozen=True)
class GitCommandResult(CommandResult):
    """
    One finished git command, whether or not it succeeded.
    """

    arguments: tuple[str, ...]
    """
    The git subcommand and its arguments, as invoked, without ``git`` itself.
    """

    @classmethod
    def of(cls, result: CommandResult) -> GitCommandResult:
        """
        :param result: A finished ``git`` command.
        :return: It, its arguments without ``git`` itself.
        """
        return cls(
            result.arguments[1:],
            result.exit_status,
            result.output,
            result.error_output,
            result.seconds,
        )

    def raise_if_failed(self) -> GitCommandResult:
        """:return: This result, when the command succeeded.
        :raises GitCommandFailed: When it did not."""
        if not self.succeeded:
            raise GitCommandFailed(
                status=self.exit_status,
                detail=self.error_output,
                arguments=self.arguments,
            )
        return self


# %% remotes


class RemoteName(StrEnum):
    """
    The remote names git gives a meaning of their own.
    """

    ORIGIN = "origin"
    """
    The remote a clone starts with.
    """


@dataclass(frozen=True)
class RemoteBranch:
    """
    One branch on one remote, and where a fetch of it is kept.
    """

    remote: str
    """
    The remote's name in the checkout.
    """

    name: str
    """
    The branch's name on the remote.
    """

    @property
    def reference(self) -> str:
        """:return: The branch's full reference, as the remote has it."""
        return f"refs/heads/{self.name}"

    @property
    def tracking_reference(self) -> str:
        """:return: The remote-tracking reference a fetch of the branch moves."""
        return f"refs/remotes/{self.remote}/{self.name}"


@dataclass(frozen=True)
class Remote:
    """
    One remote of a checkout, and the GitHub repository it pushes to.
    """

    name: str
    """
    The remote's name in the checkout.
    """

    push_url: str
    """
    The URL a push to it goes to.
    """

    repository: Repository | None
    """
    The repository the push URL names, ``None`` when it names none.
    """


# %% what a push is allowed to overwrite


@dataclass(frozen=True)
class ProposedPush:
    """
    One publication, and whether it is authorised to overwrite what is published.

    Every push is built here, so whether history may be rewritten is decided once rather
    than at each call.
    """

    remote: str
    """
    The remote to publish to.
    """

    refspec: str
    """
    What to publish, as ``<source>:<destination>``.
    """

    with_lease: bool = False
    """
    Whether published history may be overwritten, and then only if the remote is where
    this checkout last saw it.
    """


@dataclass(frozen=True)
class GitCommandRunner:
    """
    Runs git in one checkout, reporting failures rather than swallowing them.
    """

    working_directory: Path
    """
    The checkout every command runs in.
    """

    def attempt(
        self, *arguments: str, environment: Mapping[str, str] | None = None
    ) -> GitCommandResult:
        """
        Run a command whose failure is an expected outcome.

        :param arguments: The git subcommand and its arguments.
        :param environment: Variables to set for this command on top of the process's
            own.
        :return: The finished command.
        """
        return GitCommandResult.of(
            CommandRunner(self.working_directory).run(
                "git", *arguments, environment=environment
            )
        )

    def run(self, *arguments: str, environment: Mapping[str, str] | None = None) -> str:
        """
        Run a command the caller depends on the result of.

        :param arguments: The git subcommand and its arguments.
        :param environment: Variables to set for this command on top of the process's
            own.
        :return: Git's stripped stdout.
        :raises GitCommandFailed: If git exits non-zero.
        """
        return (
            self.attempt(*arguments, environment=environment).raise_if_failed().output
        )

    def repository_state_path(self, location: Path) -> Path:
        """
        :param location: Scratch state kept per repository.
        :return: Where it lives for this checkout's repository, the same from every
            worktree of it.
        """
        common_directory = self.run(
            "rev-parse", "--path-format=absolute", "--git-common-dir"
        )
        return Path(common_directory) / location

    def fetch(self, remote: str, *references: str) -> None:
        """
        Refresh what this checkout knows about a remote.

        :param remote: The remote to fetch from.
        :param references: The branches to fetch, all of them when none is named.
        """
        self.run("fetch", "--quiet", remote, *references)

    def fetch_branch(
        self, location: str, branch: str, tracking_remote: str
    ) -> GitCommandResult:
        """
        Fetch one branch into its tracking ref, leaving ``FETCH_HEAD`` alone.

        :param location: The remote name or URL to fetch from.
        :param branch: The branch to fetch.
        :param tracking_remote: The remote whose tracking refs the branch is kept under.
        :return: The finished fetch, whose failure is an expected outcome.
        """
        tracked = RemoteBranch(tracking_remote, branch)
        return self.attempt(
            "fetch",
            "--quiet",
            "--no-write-fetch-head",
            location,
            f"+{tracked.reference}:{tracked.tracking_reference}",
        )

    def has_remote_branch(self, branch: RemoteBranch) -> bool:
        """
        :param branch: A branch on a remote.
        :return: Whether the remote has it.
        :raises GitCommandFailed: If the remote cannot be reached.
        """
        return bool(self.run("ls-remote", branch.remote, branch.reference))

    def commit_or_none(self, reference: str) -> str | None:
        """:param reference: A ref that may not exist.
        :return: The commit it names, or ``None`` if it does not exist."""
        resolved = self.attempt("rev-parse", "--verify", "--quiet", reference)
        return resolved.output if resolved.succeeded else None

    def commit_at(self, reference: str) -> str:
        """:param reference: Any reference git can resolve.
        :return: The commit it names."""
        return self.run("rev-parse", reference)

    def parents_of(self, commit: str) -> tuple[str, ...]:
        """:param commit: Any reference git can resolve to a commit.
        :return: The commit's parents, its first parent first."""
        return tuple(
            self.run("rev-list", "--parents", "--max-count=1", commit).split()[1:]
        )

    def tree_of(self, commit: str) -> str:
        """:param commit: Any reference git can resolve to a commit.
        :return: The tree the commit records."""
        return self.run("rev-parse", f"{commit}^{{tree}}")

    def automatic_merge_tree(self, first: str, second: str) -> str | None:
        """
        Merge two commits without touching any branch or the working tree.

        :param first: One side of the merge.
        :param second: The other side.
        :return: The tree merging them produces, or ``None`` when it conflicts.
        """
        merge = self.attempt("merge-tree", "--write-tree", first, second)
        return merge.output.splitlines()[0] if merge.succeeded else None

    def adds_only_merges(self, candidate: str, *references: str) -> bool:
        """:param candidate: The reference whose history is examined.
        :param references: The references it is compared against.
        :return: Whether every commit *candidate* holds beyond all of *references* is a
            merge.
        :raises UnresolvableReferenceError: If any reference names no commit here.
        """
        for compared in (*references, candidate):
            if not self.attempt(
                "rev-parse", "--verify", "--quiet", f"{compared}^{{commit}}"
            ).succeeded:
                raise UnresolvableReferenceError(reference=compared)
        beyond = self.run(
            "rev-list",
            "--no-merges",
            "--max-count=1",
            candidate,
            *(f"^{reference}" for reference in references),
        )
        return not beyond

    def checkout(self, branch: str, start_point: str) -> None:
        """
        Put a branch at a starting point and check it out.

        :param branch: The branch to move and check out.
        :param start_point: What to point it at.
        """
        self.run("checkout", "--quiet", "-B", branch, start_point)

    def checked_out_branch(self) -> str:
        """:return: The branch whose content a push would move."""
        return self.run("branch", "--show-current")

    def merge(self, reference: str, message: str) -> GitCommandResult:
        """:param reference: The reference to merge in.
        :param message: The merge commit's message.
        :return: The finished merge, whose failure is a conflict only when it left
            unmerged paths behind."""
        return self.attempt("merge", "--no-edit", "--message", message, reference)

    def trailer_value(self, commit: str, trailer: str) -> str:
        """:param commit: Any reference git can resolve to a commit.
        :param trailer: The trailer key read.
        :return: The value the commit's message gives that trailer, empty when it has
            none."""
        return self.run(
            "log",
            "--max-count=1",
            f"--format=%(trailers:key={trailer},valueonly)",
            commit,
        )

    def rebase(self, reference: str) -> GitCommandResult:
        """:param reference: The reference to rebase onto.
        :return: The finished rebase, whose failure is a conflict only when it left
            unmerged paths behind."""
        return self.attempt("rebase", reference)

    def abandon(self, strategy: IntegrationStrategy) -> None:
        """
        Undo whichever integration just failed.

        :param strategy: The integration that was attempted.
        """
        self.attempt(strategy, "--abort")

    def unmerged_paths(self) -> tuple[str, ...]:
        """:return: The paths the integration that just failed left conflicted."""
        unmerged = self.attempt("diff", "--name-only", "--diff-filter=U")
        return tuple(path for path in unmerged.output.splitlines() if path)

    def push(self, proposed: ProposedPush) -> GitCommandResult:
        """
        Publish a refspec, forcing only where the push itself says it is authorised.

        :param proposed: What to publish, and whether a rewrite is authorised.
        :return: The finished push, whose failure the caller reports rather than forces.
        """
        lease = ["--force-with-lease"] if proposed.with_lease else []
        return self.attempt(
            "push", "--quiet", *lease, proposed.remote, proposed.refspec
        )

    def delete_remote_branch(self, branch: RemoteBranch) -> GitCommandResult:
        """
        :param branch: The branch to delete from its remote.
        :return: The finished push deleting it, whose failure the caller reports.
        """
        return self.push(ProposedPush(branch.remote, f":{branch.reference}"))

    def remotes(self) -> list[Remote]:
        """:return: Every remote of the checkout, in the order git lists them."""
        remotes = []
        for name in self.run("remote").split():
            url = self.run("remote", "get-url", "--push", name)
            repository = (
                Repository.from_remote_url(url)
                if Repository.names_a_repository(url)
                else None
            )
            remotes.append(Remote(name, url, repository))
        return remotes

    def commit_files(
        self, parent: str | None, files: Mapping[Path, str], message: str
    ) -> str:
        """
        Commit files without checking anything out, in an index of the commit's own.

        :param parent: The commit to build on, ``None`` for a commit with no parent.
        :param files: The text of each file to write, over the parent's files.
        :param message: The commit message.
        :return: The new commit.
        """
        with tempfile.TemporaryDirectory() as directory:
            index = {GitVariable.INDEX_FILE: str(Path(directory) / "index")}
            if parent is not None:
                self.run("read-tree", parent, environment=index)
            for path, text in files.items():
                staged = Path(directory) / "content"
                staged.write_text(text)
                blob = self.run("hash-object", "-w", str(staged))
                self.run(
                    "update-index",
                    "--add",
                    "--cacheinfo",
                    f"100644,{blob},{path}",
                    environment=index,
                )
            tree = self.run("write-tree", environment=index)
        parents = () if parent is None else ("-p", parent)
        return self.run("commit-tree", tree, *parents, "-m", message)

    def rebase_stack(self, onto: str, top: str) -> GitCommandResult:
        """
        Replay a stack of branches onto a moved base, moving every branch inside it.

        :param onto: The branch the stack is replayed onto.
        :param top: The topmost branch of the stack, which is checked out afterwards.
        :return: The finished rebase, whose failure is a conflict only when it left
            unmerged paths behind.
        """
        return self.attempt("rebase", "--update-refs", onto, top)

    def contains(self, candidate: str, descendant: str) -> bool:
        """:param candidate: The reference that may be contained.
        :param descendant: The reference that may contain it.
        :return: Whether *candidate* is an ancestor of *descendant*."""
        return self.attempt(
            "merge-base", "--is-ancestor", candidate, descendant
        ).succeeded
