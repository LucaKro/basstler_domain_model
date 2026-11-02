"""
The errors running git ends in.
"""

from __future__ import annotations

from dataclasses import dataclass

from basstler_domain_model.exceptions import DataclassException, ExternalCallFailed

# %% errors


@dataclass
class GitCommandFailed(ExternalCallFailed):
    """
    Raised when a git command the caller depends on the result of fails.
    """

    arguments: tuple[str, ...] = ()
    """
    The command and its arguments, ``git`` included, as invoked.
    """

    @property
    def call(self) -> str:
        """:return: The git command line, as invoked."""
        return " ".join(self.arguments)


@dataclass
class UnresolvableReferenceError(DataclassException, LookupError):
    """
    Raised when a git reference a decision depends on names no commit in the checkout.
    """

    reference: str
    """
    The reference git could not resolve.
    """

    def error_message(self) -> str:
        return f"git cannot resolve '{self.reference}' to a commit in this checkout"

    def suggest_correction(self) -> str:
        return (
            "fetch the branch it names from its remote, and check that the branch "
            "still exists there"
        )


@dataclass
class StorageBranchPushRefused(DataclassException, RuntimeError):
    """
    Raised when a storage branch refuses a push even after building on its newest tip.
    """

    branch: str
    """
    The storage branch.
    """

    detail: str
    """
    What git said when it refused.
    """

    def error_message(self) -> str:
        return f"pushing {self.branch} was refused: {self.detail}"

    def suggest_correction(self) -> str:
        return "Run the write again; if it keeps failing, check access to the remote."
