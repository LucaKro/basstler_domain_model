"""
Reading and writing a repository's pull requests and labels.

The reading and the writing halves are declared separately, so a caller that must not
write can be handed a reader and provably cannot. Every write here
was probed against the live API first: a pull request's *base branch* is the one the
credential a session carries is refused, which is why retargeting is reported for a
caller to perform rather than performed.
"""

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum, StrEnum
from pathlib import Path
from typing import Any

from basstler_domain_model.environment import GitHubCredentialVariable
from basstler_domain_model.github.clients import GitHubApi
from basstler_domain_model.github.exceptions import (
    GitHubCredentialUnavailableError,
)
from basstler_domain_model.github.labels import GitHubLabel
from basstler_domain_model.github.pull_request_fields import PullRequestPayload
from basstler_domain_model.github.pull_request_models import CheckStatus
from basstler_domain_model.github.stack_models import Stack
from basstler_domain_model.github.rest_models import (
    RestCheckRunPage,
    RestCombinedStatusPage,
)
from basstler_domain_model.github.vocabulary import (
    PullRequestState,
    RestJSONKey,
    RollupState,
)
from basstler_domain_model.locations import PathEnumeration
from basstler_domain_model.repository import GitHubAddress, Repository

# %% what a caller reads and writes


@dataclass(frozen=True)
class PullRequestReader(ABC):
    """
    Reading the pull-request state a pass derives from.

    Implementations inherit rather than merely match the shape, so one that omits a read
    is refused when it is constructed rather than when the missing call is first made.
    """

    @abstractmethod
    def open_pull_requests(self) -> list[PullRequestPayload]:
        """:return: Every open pull request on the fork."""

    @abstractmethod
    def pull_request(self, number: int) -> PullRequestPayload:
        """:param number: The pull request to read.
        :return: That pull request."""


@dataclass(frozen=True)
class PullRequestWriter(ABC):
    """
    The three writes a pass makes, each one probed against the live API first.

    Every one of them is available to the credential a session carries; a pull request's
    *base branch* is the single write that is not, which is why reparenting is the
    caller's job and none of this is.
    """

    @abstractmethod
    def replace_labels(self, number: int, labels: Sequence[str]) -> None:
        """:param number: The pull request to write.
        :param labels: The complete label set it must end up with."""

    @abstractmethod
    def add_comment(self, number: int, body: str) -> str:
        """:param number: The pull request to comment on.
        :param body: The comment.
        :return: The comment's URL."""

    @abstractmethod
    def set_description(self, number: int, body: str) -> None:
        """:param number: The pull request to write.
        :param body: The new description."""


@dataclass(frozen=True)
class ForkPullRequests(PullRequestReader, PullRequestWriter, ABC):
    """
    Everything a pass does to the fork's pull requests.

    A pass reads state and writes back to the same fork, so the two halves are named
    together wherever both are needed; the board export takes the reading half alone,
    which is what keeps an export from being able to write.
    """


@dataclass(frozen=True)
class RepositoryLabels(ABC):
    """
    The labels a repository carries, and adding one it lacks.
    """

    @abstractmethod
    def labels(self) -> set[str]:
        """:return: The name of every label the repository carries."""

    @abstractmethod
    def create_label(self, label: GitHubLabel) -> None:
        """:param label: The label to add, created with its description."""


@dataclass(frozen=True)
class PullRequestBaseWriter(ABC):
    """
    Retargeting a pull request at another branch.
    """

    @abstractmethod
    def set_base(self, number: int, branch: str) -> None:
        """:param number: The pull request to retarget.
        :param branch: The branch it is to merge into."""


@dataclass(frozen=True)
class StackReader(ABC):
    """
    Reading a repository's native stacks of pull requests.
    """

    @abstractmethod
    def stacks(self) -> list[Stack]:
        """:return: Every stack in the repository, newest first."""

    @abstractmethod
    def stack(self, number: int) -> Stack:
        """:param number: The stack's number.
        :return: That stack."""

    @abstractmethod
    def stack_of(self, pull_request: int) -> Stack | None:
        """:param pull_request: A pull request's number.
        :return: The stack holding it, ``None`` when it is in none."""


@dataclass(frozen=True)
class StackWriter(ABC):
    """
    Forming, growing and dissolving native stacks of pull requests.
    """

    @abstractmethod
    def create_stack(self, pull_requests: Sequence[int]) -> Stack:
        """
        :param pull_requests: At least two pull requests, bottom first, each targeting
            the branch of the one before it.
        :return: The new stack.
        """

    @abstractmethod
    def add_to_stack(self, stack: Stack, pull_requests: Sequence[int]) -> Stack:
        """
        :param stack: The stack to grow.
        :param pull_requests: The pull requests to put on top, lowest first, the first
            targeting the stack's top branch.
        :return: The grown stack.
        """

    @abstractmethod
    def unstack(self, stack: Stack) -> Stack | None:
        """
        :param stack: The stack to take the pull requests out of.
        :return: What remains of it, ``None`` when it dissolved.
        """


class CommitChecks(ABC):
    """
    Reading the verdict over the checks reported on one commit.
    """

    @abstractmethod
    def check_state(self, commit: str) -> RollupState:
        """:param commit: The commit the checks ran on.
        :return: The verdict over every check run and commit status reported on it."""


@dataclass(frozen=True)
class CredentialHolder(ABC):
    """
    Telling whose credential a client calls GitHub with.
    """

    @abstractmethod
    def authenticated_login(self) -> str:
        """:return: The login of the account the credential belongs to."""


class GitHubPath(PathEnumeration):
    """
    The API paths that are not below a repository.
    """

    AUTHENTICATED_USER = Path("/user")
    """
    The account the request's credential belongs to.
    """


class RepositoryPath(PathEnumeration):
    """
    The API paths below a repository.
    """

    PULL_REQUESTS = Path("/pulls")
    """
    The repository's pull requests.
    """

    LABELS = Path("/labels")
    """
    The labels defined on the repository.
    """

    COMMITS = Path("/commits")
    """
    The repository's commits.
    """

    STACKS = Path("/stacks")
    """
    The repository's native stacks of pull requests.
    """


class CommitReport(StrEnum):
    """
    The listings reported against one commit, below :attr:`RepositoryPath.COMMITS`.
    """

    CHECK_RUNS = "check-runs"
    """
    The check runs reported against it.
    """

    STATUS = "status"
    """
    The commit statuses posted against it.
    """


class StackAction(StrEnum):
    """
    What is done to a stack, below its own path.
    """

    ADD = "add"
    """
    Put pull requests on top.
    """

    UNSTACK = "unstack"
    """
    Take the pull requests out again.
    """


class ListingParameter(StrEnum):
    """
    The query parameters a paged listing takes.
    """

    STATE = "state"
    """
    Which pull requests to list, by state.
    """

    PAGE_SIZE = "per_page"
    """
    How many entries one page holds.
    """

    PAGE = "page"
    """
    Which page to read, counting from one.
    """

    PULL_REQUEST = "pull_request"
    """
    Which pull request a listed stack must hold.
    """


@dataclass(frozen=True)
class PullRequestListingSpecification:
    """
    One filter the pull request list API takes: what it is asked for by, and which
    :class:`PullRequestState` values it lets through.
    """

    query: str
    """
    The value the list API's ``state`` parameter takes for this filter.
    """

    states: tuple[PullRequestState, ...]
    """
    The pull request states this filter lets through.
    """


class PullRequestListState(PullRequestListingSpecification, Enum):
    """
    The pull request states the list API filters on: open, no longer open, and every
    state at once.

    Each member *is* a :class:`PullRequestListingSpecification`, written as its fields
    in declaration order - ``query``, then ``states`` - which the enum passes straight to
    the dataclass.
    """

    OPEN = PullRequestState.OPEN.value, (PullRequestState.OPEN,)
    """
    Pull requests whose state is :attr:`PullRequestState.OPEN`: drafts and those ready
    for review alike.
    """

    CLOSED = PullRequestState.CLOSED.value, (
        PullRequestState.CLOSED,
        PullRequestState.MERGED,
    )
    """
    Pull requests that are no longer open: closed unmerged and merged alike, which REST
    reports under one state.
    """

    ALL = "all", tuple(PullRequestState)
    """
    Every pull request, whatever its :class:`PullRequestState`.
    """


# %% the client that makes the calls


@dataclass(frozen=True)
class GitHubRepository(
    ForkPullRequests,
    PullRequestBaseWriter,
    StackReader,
    StackWriter,
    CommitChecks,
    RepositoryLabels,
    CredentialHolder,
):
    """
    Every pull-request, stack and label call this tooling makes, against one repository.

    ``gh`` is absent from the environment this normally runs in, so the calls are plain
    authenticated requests rather than a CLI wrapper.
    """

    repository: Repository
    """
    The repository to read and write.
    """

    token: str
    """
    The credential the requests authenticate with.
    """

    page_size: int = 100
    """
    How many pull requests, stacks or labels to ask for per request.
    """

    api_root: str = GitHubAddress.API
    """
    Where the REST API answers.
    """

    @classmethod
    def from_environment(cls, repository: Repository) -> GitHubRepository:
        """
        Build a client from whichever credential the environment carries.

        :param repository: The repository to read and write.
        :return: The client.
        :raises GitHubCredentialUnavailableError: If no token is set.
        """
        token = GitHubCredentialVariable.first_token()
        if token:
            return cls(repository, token)
        raise GitHubCredentialUnavailableError(tuple(GitHubCredentialVariable))

    def open_pull_requests(self) -> list[PullRequestPayload]:
        """:return: Every open pull request on the repository, oldest page first."""
        return self._pull_requests_in_state(PullRequestListState.OPEN)

    def all_pull_requests(self) -> list[PullRequestPayload]:
        """:return: Every pull request on the repository, open or closed."""
        return self._pull_requests_in_state(PullRequestListState.ALL)

    def issue(self, number: int) -> Mapping[str, Any]:
        """:param number: The issue or pull request to read.
        :return: It, as the issues API describes it."""
        return self._call("GET", f"/issues/{number}")

    def _pull_requests_in_state(
        self, state: PullRequestListState
    ) -> list[PullRequestPayload]:
        """
        Read every page of pull requests in one state.

        :param state: Which pull requests to list.
        :return: Them, oldest page first.
        """
        return self._every_page(
            RepositoryPath.PULL_REQUESTS, {ListingParameter.STATE: state.query}
        )

    def labels(self) -> set[str]:
        return {
            label[RestJSONKey.NAME]
            for label in self._every_page(RepositoryPath.LABELS, {})
        }

    def create_label(self, label: GitHubLabel) -> None:
        self._call(
            "POST",
            str(RepositoryPath.LABELS),
            {RestJSONKey.NAME: label, RestJSONKey.DESCRIPTION: label.description},
        )

    def check_state(self, commit: str) -> RollupState:
        runs = [
            run.result
            for page in self._every_page_of_entries(
                self._commit_report(commit, CommitReport.CHECK_RUNS),
                RestJSONKey.CHECK_RUNS,
            )
            for run in RestCheckRunPage.from_json(page).check_runs
        ]
        statuses = [
            status.result
            for page in self._every_page_of_entries(
                self._commit_report(commit, CommitReport.STATUS), RestJSONKey.STATUSES
            )
            for status in RestCombinedStatusPage.from_json(page).statuses
        ]
        checks = CheckStatus.over(runs + statuses)
        return RollupState.NOT_REPORTED if checks is None else checks.state

    @staticmethod
    def _commit_report(commit: str, report: CommitReport) -> str:
        """:param commit: The commit reported against.
        :param report: Which of its listings to read.
        :return: The listing's path below the repository."""
        return f"{RepositoryPath.COMMITS}/{commit}/{report}"

    def authenticated_login(self) -> str:
        account = self._request("GET", str(GitHubPath.AUTHENTICATED_USER))
        return str(account[RestJSONKey.LOGIN])

    def _every_page(
        self, path: RepositoryPath, filters: Mapping[ListingParameter, str]
    ) -> list[Any]:
        """
        Read a listing below the repository to its end.

        :param path: The listing's path below the repository.
        :param filters: The query parameters narrowing the listing.
        :return: Every entry, first page first.
        """
        return [
            entry
            for page in self._every_page_of_entries(str(path), None, filters)
            for entry in page
        ]

    def _every_page_of_entries(
        self,
        path: str,
        entries_key: str | None,
        filters: Mapping[ListingParameter, str] | None = None,
    ) -> list[Any]:
        """
        Read a paged listing below the repository to its end.

        :param path: The listing's path below the repository.
        :param entries_key: The key a page holds its entries under, ``None`` when a page
            is the list of entries itself.
        :param filters: The query parameters narrowing the listing.
        :return: Every page, first page first.
        """
        pages: list[Any] = []
        page_number = 1
        while True:
            query = urllib.parse.urlencode(
                {
                    **(filters or {}),
                    ListingParameter.PAGE_SIZE: self.page_size,
                    ListingParameter.PAGE: page_number,
                }
            )
            page = self._call("GET", f"{path}?{query}")
            pages.append(page)
            entries = page if entries_key is None else page[entries_key]
            if len(entries) < self.page_size:
                return pages
            page_number += 1

    def pull_request(self, number: int) -> PullRequestPayload:
        """:param number: The pull request to read.
        :return: That pull request."""
        return self._call("GET", f"{RepositoryPath.PULL_REQUESTS}/{number}")

    def replace_labels(self, number: int, labels: Sequence[str]) -> None:
        """
        Write a pull request's complete label set.

        :param number: The pull request to write.
        :param labels: The complete set it must end up with, computed by
            :meth:`stack.LabelWrite.replacing` - this call replaces rather than adds.
        """
        self._call("PUT", f"/issues/{number}/labels", {"labels": list(labels)})

    def add_comment(self, number: int, body: str) -> str:
        """:param number: The pull request to comment on.
        :param body: The comment.
        :return: The comment's URL."""
        created = self._call("POST", f"/issues/{number}/comments", {"body": body})
        return str(created["html_url"])

    def set_description(self, number: int, body: str) -> None:
        """
        Rewrite a pull request's description and nothing else.

        :param number: The pull request to write.
        :param body: The new description.
        """
        self._call("PATCH", f"{RepositoryPath.PULL_REQUESTS}/{number}", {"body": body})

    def set_base(self, number: int, branch: str) -> None:
        self._call(
            "PATCH",
            f"{RepositoryPath.PULL_REQUESTS}/{number}",
            {RestJSONKey.BASE: branch},
        )

    def stacks(self) -> list[Stack]:
        return [
            Stack.from_json(entry)
            for entry in self._every_page(RepositoryPath.STACKS, {})
        ]

    def stack(self, number: int) -> Stack:
        return Stack.from_json(self._call("GET", f"{RepositoryPath.STACKS}/{number}"))

    def stack_of(self, pull_request: int) -> Stack | None:
        query = urllib.parse.urlencode({ListingParameter.PULL_REQUEST: pull_request})
        found = self._call("GET", f"{RepositoryPath.STACKS}?{query}")
        return Stack.from_json(found[0]) if found else None

    def create_stack(self, pull_requests: Sequence[int]) -> Stack:
        return Stack.from_json(
            self._call(
                "POST",
                str(RepositoryPath.STACKS),
                {RestJSONKey.PULL_REQUESTS: list(pull_requests)},
            )
        )

    def add_to_stack(self, stack: Stack, pull_requests: Sequence[int]) -> Stack:
        return Stack.from_json(
            self._call(
                "POST",
                f"{RepositoryPath.STACKS}/{stack.number}/{StackAction.ADD}",
                {RestJSONKey.PULL_REQUESTS: list(pull_requests)},
            )
        )

    def unstack(self, stack: Stack) -> Stack | None:
        remaining = self._call(
            "POST", f"{RepositoryPath.STACKS}/{stack.number}/{StackAction.UNSTACK}"
        )
        return None if remaining is None else Stack.from_json(remaining)

    def _call(
        self, method: str, path: str, payload: Mapping[str, Any] | None = None
    ) -> Any:
        """
        Make one authenticated API call below this repository.

        :param method: The HTTP method.
        :param path: The path below the repository, starting with a slash.
        :param payload: The JSON body, absent for a read.
        :return: The decoded response.
        :raises GitHubRequestFailed: If the API answers with an error status.
        """
        return self._request(method, f"/repos/{self.repository}{path}", payload)

    def _request(
        self, method: str, path: str, payload: Mapping[str, Any] | None = None
    ) -> Any:
        """
        Make one authenticated API call.

        :param method: The HTTP method.
        :param path: The path below the API root, starting with a slash.
        :param payload: The JSON body, absent for a read.
        :return: The decoded response, ``None`` when it has no body.
        :raises GitHubRequestFailed: If the API answers with an error status.
        """
        return GitHubApi(self.token, self.api_root).request(method, path, payload)
