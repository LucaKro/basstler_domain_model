"""
A branch used to store files: read from a private reference, written by commits built
without a checkout, and pushed without force.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from basstler_domain_model.git.commands import GitCommandResult, GitCommandRunner
from basstler_domain_model.git.exceptions import StorageBranchPushRefused

# %% the branch


@dataclass(frozen=True)
class StorageBranch:
    """
    A branch on a remote that holds files rather than a project's history, so the
    checkout it is used from is never touched.
    """

    git: GitCommandRunner
    """
    Runs git in the checkout the branch is used from.
    """

    remote: str
    """
    The remote the branch lives on, by name or URL.
    """

    branch: str
    """
    The branch's name on the remote.
    """

    reference: str
    """
    Where a fetch of the branch is kept, so neither a local branch nor ``FETCH_HEAD``
    moves.
    """

    def fetch(self) -> bool:
        """
        Bring the private reference to the branch's tip on the remote.

        :return: Whether the branch exists on the remote.
        :raises GitCommandFailed: If the remote cannot be reached.
        """
        if not self.git.run("ls-remote", "--heads", self.remote, self.branch):
            self.git.attempt("update-ref", "-d", self.reference)
            return False
        self.git.run(
            "fetch",
            "--quiet",
            "--no-write-fetch-head",
            self.remote,
            f"+refs/heads/{self.branch}:{self.reference}",
        )
        return True

    def read(self, path: Path) -> str | None:
        """
        :param path: A file on the branch.
        :return: Its content as last fetched, ``None`` when it does not exist.
        """
        shown = self.git.attempt("show", f"{self.reference}:{path}")
        return shown.output if shown.succeeded else None

    def write(self, files: Mapping[Path, str], message: str) -> None:
        """
        Commit *files* on top of the branch's tip and push the commit.

        When another writer pushed first, the commit is built again on the new tip;
        writers that write different files never need a merge.

        :param files: The text of each file to write.
        :param message: The commit message.
        :raises StorageBranchPushRefused: If the push is refused twice.
        """
        pushed = self._push(files, message)
        if not pushed.succeeded:
            self.fetch()
            pushed = self._push(files, message)
        if not pushed.succeeded:
            raise StorageBranchPushRefused(self.branch, pushed.error_output)
        self.fetch()

    def _push(self, files: Mapping[Path, str], message: str) -> GitCommandResult:
        """
        :param files: The text of each file to write.
        :param message: The commit message.
        :return: The finished push of a commit holding *files* on the fetched tip.
        """
        commit = self.git.commit_files(
            self.git.commit_or_none(self.reference), files, message
        )
        return self.git.attempt(
            "push", "--quiet", self.remote, f"{commit}:refs/heads/{self.branch}"
        )
