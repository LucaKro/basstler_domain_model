"""
Running git in one checkout, and what a push is allowed to overwrite.

Every command goes through :class:`GitCommandRunner`, and every push is built as a
:class:`ProposedPush` - so whether published history may be rewritten is decided in one
place rather than at each call site.
"""

from __future__ import annotations

import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from basstler_domain_model.class_property import classproperty
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

    @classmethod
    def of(cls, result: CommandResult) -> GitCommandResult:
        """
        :param result: A finished ``git`` command.
        :return: It, as a git command.
        """
        return cls(
            result.arguments,
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

    sets_upstream: bool = False
    """
    Whether the local branch published then tracks the branch it was published to.
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

    @classproperty
    def unattended_environment(cls) -> dict[str, str]:
        """
        The variables every git command runs with, so it fails rather than waits for a
        person.
        """
        return {GitVariable.TERMINAL_PROMPT: "0"}

    @classmethod
    def clone(cls, url: str, destination: Path) -> GitCommandRunner:
        """
        Clone a repository into a new checkout.

        :param url: The repository to clone, as git fetches it.
        :param destination: The new checkout's directory, absent or empty.
        :return: Runs git in the new checkout.
        :raises GitCommandFailed: If the repository cannot be cloned there.
        """
        checkout = destination.absolute()
        checkout.parent.mkdir(parents=True, exist_ok=True)
        cls(checkout.parent).run("clone", "--quiet", url, str(checkout))
        return cls(checkout)

    def attempt(
        self, *arguments: str, environment: Mapping[str, str] | None = None
    ) -> GitCommandResult:
        """
        Run a command whose failure is an expected outcome, failing rather than
        prompting on the terminal.

        :param arguments: The git subcommand and its arguments.
        :param environment: Variables to set for this command on top of the process's
            own.
        :return: The finished command.
        """
        return GitCommandResult.of(
            CommandRunner(self.working_directory).run(
                "git",
                *arguments,
                environment={**self.unattended_environment, **(environment or {})},
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

    def fetch_branch(self, branch: RemoteBranch) -> GitCommandResult:
        """
        Fetch one branch into its tracking ref, leaving ``FETCH_HEAD`` alone.

        :param branch: The branch to fetch.
        :return: The finished fetch, whose failure is an expected outcome.
        """
        return self.attempt(
            "fetch",
            "--quiet",
            "--no-write-fetch-head",
            branch.remote,
            f"+{branch.reference}:{branch.tracking_reference}",
        )

    def has_remote_branch(self, branch: RemoteBranch) -> bool:
        """
        :param branch: A branch on a remote.
        :return: Whether the remote has it.
        :raises GitCommandFailed: If the remote cannot be reached.
        """
        return self.remote_branch_tip(branch) is not None

    def remote_branch_tip(self, branch: RemoteBranch) -> str | None:
        """
        :param branch: A branch on a remote.
        :return: The commit it is at on the remote, ``None`` when the remote has no
            such branch.
        :raises GitCommandFailed: If the remote cannot be reached.
        """
        listed = self.run("ls-remote", branch.remote, branch.reference)
        return next(
            (
                commit
                for commit, reference in (line.split() for line in listed.splitlines())
                if reference == branch.reference
            ),
            None,
        )

    def remote_default_branch(self, remote: str) -> str | None:
        """
        :param remote: A remote's name.
        :return: The branch the remote's ``HEAD`` names, as the remote answers, or as
            last fetched when it cannot be reached; ``None`` when neither knows.
        """
        branches = RemoteBranch(remote, "").reference
        listed = self.attempt("ls-remote", "--symref", remote, "HEAD")
        for line in listed.output.splitlines() if listed.succeeded else []:
            target, _, name = line.partition("\t")
            if name == "HEAD" and target.startswith(f"ref: {branches}"):
                return target.removeprefix(f"ref: {branches}")
        tracking = RemoteBranch(remote, "").tracking_reference
        fetched = self.attempt("symbolic-ref", "--quiet", f"{tracking}HEAD")
        if not fetched.succeeded:
            return None
        return fetched.output.removeprefix(tracking)

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

    def create_branch(self, name: str, start_point: str) -> None:
        """
        Create a branch and check it out, tracking no branch: not even a remote's it
        starts at.

        :param name: The new branch.
        :param start_point: What it starts at.
        :raises GitCommandFailed: If the branch exists already.
        """
        self.run("switch", "--quiet", "--no-track", "--create", name, start_point)

    def switch_to(self, branch: str) -> None:
        """
        Check out an existing branch, creating a local one that tracks the remote's when
        only a remote has it.

        :param branch: The branch to check out.
        :raises GitCommandFailed: If no branch of that name exists, or uncommitted changes
            would be overwritten.
        """
        self.run("switch", "--quiet", branch)

    def commit(self, message: str, paths: Sequence[Path]) -> str:
        """
        Commit the current content of some paths.

        :param message: The commit message.
        :param paths: The files and directories to commit, as they are in the working
            tree; one no longer there is committed as removed.
        :return: The new commit.
        :raises GitCommandFailed: If nothing changed.
        """
        present = [
            str(path) for path in paths if (self.working_directory / path).exists()
        ]
        removed = [str(path) for path in paths if str(path) not in present]
        if present:
            self.run("add", "--", *present)
        if removed:
            self.run(
                "rm", "-r", "--quiet", "--cached", "--ignore-unmatch", "--", *removed
            )
        self.run("commit", "--quiet", "--message", message)
        return self.commit_at("HEAD")

    def fast_forward(self, reference: str) -> GitCommandResult:
        """
        :param reference: What to move the checked-out branch to.
        :return: The finished merge, failed when the branch has commits *reference* lacks.
        """
        return self.attempt("merge", "--quiet", "--ff-only", reference)

    def fast_forward_branch(self, branch: str, reference: str) -> GitCommandResult:
        """
        Move a branch that is not checked out forward to a reference.

        :param branch: The branch to move.
        :param reference: Where to move it, a descendant of its commit.
        :return: The finished move, refused when the branch has commits the reference
            lacks or is checked out in any worktree.
        """
        return self.attempt("fetch", "--quiet", ".", f"{reference}:refs/heads/{branch}")

    def reset_kept(self, reference: str) -> None:
        """
        Move the checked-out branch to another commit, keeping uncommitted changes.

        :param reference: The commit to move it to.
        :raises GitCommandFailed: If an uncommitted change would be lost.
        """
        self.run("reset", "--quiet", "--keep", reference)

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
        upstream = ["--set-upstream"] if proposed.sets_upstream else []
        return self.attempt(
            "push", "--quiet", *lease, *upstream, proposed.remote, proposed.refspec
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

    def export_files(self, commit: str, destination: Path) -> None:
        """
        Write the files a commit records into a directory, leaving the checkout, its
        index and ``HEAD`` alone.

        :param commit: Any reference git can resolve to a commit.
        :param destination: The directory, created when absent.
        """
        destination.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as directory:
            index = {GitVariable.INDEX_FILE: str(Path(directory) / "index")}
            self.run("read-tree", commit, environment=index)
            self.run(
                "checkout-index",
                "--all",
                f"--prefix={destination.resolve()}/",
                environment=index,
            )

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
