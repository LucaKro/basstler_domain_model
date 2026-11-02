"""
Reading and writing a repository's pull requests, labels and stacks.

The reading and the writing halves are declared separately, so a caller that must not
write can be handed a reader and provably cannot.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any

from basstler_domain_model.github.clients import GitHubApi
from basstler_domain_model.github.commit_checks import CommitCheckReader
from basstler_domain_model.github.exceptions import NotAnIssueError
from basstler_domain_model.github.issue_models import Issue, IssueComment
from basstler_domain_model.github.labels import GitHubLabel
from basstler_domain_model.github.routes import (
    QueryParameter,
    RepositoryRoute,
    StackAction,
)
from basstler_domain_model.github.rest_models import RestPullRequest, RestRepository
from basstler_domain_model.github.stack_models import Stack
from basstler_domain_model.github.vocabulary import (
    IssueState,
    IssueStateReason,
    PullRequestState,
    RestJSONKey,
    RollupState,
)
from basstler_domain_model.repository import Repository

# %% what a caller reads and writes


@dataclass(frozen=True)
class PullRequestReader(ABC):
    """
    Reading a repository's pull requests.

    Implementations inherit rather than merely match the shape, so one that omits a read
    is refused when it is constructed rather than when the missing call is first made.
    """

    @abstractmethod
    def open_pull_requests(self) -> list[RestPullRequest]:
        """:return: Every open pull request in the repository."""

    @abstractmethod
    def pull_request(self, number: int) -> RestPullRequest:
        """:param number: The pull request to read.
        :return: That pull request."""


@dataclass(frozen=True)
class PullRequestWriter(ABC):
    """
    The three writes a pass makes to a pull request, each one probed against the live
    API first.
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


@dataclass(frozen=True)
class PullRequestOpener(ABC):
    """
    Opening a pull request.
    """

    @abstractmethod
    def open_draft(self, head: str, base: str, title: str, body: str) -> int:
        """
        :param head: The branch to merge, in this repository.
        :param base: The branch to merge it into.
        :param title: The pull request's title.
        :param body: Its description.
        :return: The number of the new draft pull request.
        """


@dataclass(frozen=True)
class RepositoryDetails(ABC):
    """
    Reading facts about the repository itself.
    """

    @abstractmethod
    def default_branch(self) -> str:
        """:return: The branch pull requests target unless told otherwise."""


@dataclass(frozen=True)
class RepositorySettings(ABC):
    """
    Whether GitHub deletes merged branches, and turning that on, which not every
    credential may.
    """

    @abstractmethod
    def deletes_merged_branches(self) -> bool:
        """:return: Whether GitHub deletes a pull request's branch once it is merged."""

    @abstractmethod
    def turn_on_merged_branch_deletion(self) -> bool:
        """
        Have GitHub delete a pull request's branch once it is merged.

        :return: Whether GitHub accepted the change; a credential that may not change
            settings is refused.
        """

    @abstractmethod
    def issues_enabled(self) -> bool:
        """:return: Whether the repository has issues turned on."""

    @abstractmethod
    def turn_on_issues(self) -> bool:
        """
        Turn the repository's issues on.

        :return: Whether GitHub accepted the change.
        """

    @abstractmethod
    def actions_enabled(self) -> bool | None:
        """
        :return: Whether GitHub Actions may run in the repository, ``None`` when the
            credential may not read that.
        """

    @abstractmethod
    def turn_on_actions(self) -> bool:
        """
        Let GitHub Actions run in the repository.

        :return: Whether GitHub accepted the change.
        """


@dataclass(frozen=True)
class IssueBoard(ABC):
    """
    Filing, listing, labelling and closing a repository's issues.
    """

    @abstractmethod
    def open_issue(self, title: str, body: str, labels: Sequence[str]) -> int:
        """
        :param title: The issue's title.
        :param body: Its description.
        :param labels: The labels it is filed with.
        :return: The new issue's number.
        """

    @abstractmethod
    def issues(self, labels: Sequence[str], state: IssueState) -> list[Issue]:
        """
        :param labels: Labels every listed issue carries.
        :param state: Whether to list open or closed issues.
        :return: The issues, pull requests left out.
        """

    @abstractmethod
    def issue(self, number: int) -> Issue:
        """
        :param number: The issue to read.
        :return: That issue.
        :raises NotAnIssueError: If the number belongs to a pull request.
        """

    @abstractmethod
    def replace_labels(self, number: int, labels: Sequence[str]) -> None:
        """
        :param number: The issue or pull request to write.
        :param labels: The complete label set it must end up with.
        """

    @abstractmethod
    def add_labels(self, number: int, labels: Sequence[str]) -> None:
        """
        Add labels, leaving every label the issue already carries in place.

        :param number: The issue or pull request to write.
        :param labels: The labels it must carry afterwards.
        """

    @abstractmethod
    def remove_label(self, number: int, label: str) -> None:
        """
        Remove one label, leaving every other label in place.

        :param number: The issue or pull request to write.
        :param label: A label it carries.
        """

    @abstractmethod
    def add_comment(self, number: int, body: str) -> str:
        """
        :param number: The issue or pull request to comment on.
        :param body: The comment.
        :return: The comment's URL.
        """

    @abstractmethod
    def comments(self, number: int) -> list[IssueComment]:
        """
        :param number: The issue or pull request to read.
        :return: Its comments, oldest first.
        """

    @abstractmethod
    def close_issue(self, number: int, reason: IssueStateReason) -> None:
        """
        :param number: The issue to close.
        :param reason: Why it is closed.
        """


@dataclass(frozen=True)
class ReviewRequests(ABC):
    """
    The repository's pull requests waiting on the credential's account.
    """

    @abstractmethod
    def awaiting_my_review(self) -> int:
        """
        :return: How many of the repository's open pull requests ask the account for a
            review.
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
    PullRequestOpener,
    RepositoryDetails,
    RepositorySettings,
    IssueBoard,
    ReviewRequests,
    StackReader,
    StackWriter,
    CommitChecks,
    RepositoryLabels,
    CredentialHolder,
):
    """
    Every pull-request, stack and label call this tooling makes, against one repository.
    """

    repository: Repository
    """
    The repository to read and write.
    """

    api: GitHubApi
    """
    Makes the calls.
    """

    @classmethod
    def from_environment(cls, repository: Repository) -> GitHubRepository:
        """
        :param repository: The repository to read and write.
        :return: A client calling with the credential :meth:`GitHubApi.from_environment`
            finds.
        :raises GitHubCredentialUnavailableError: If no token is found.
        """
        return cls(repository, GitHubApi.from_environment())

    @property
    def route(self) -> RepositoryRoute:
        """:return: The repository's paths."""
        return RepositoryRoute(self.repository)

    def open_pull_requests(self) -> list[RestPullRequest]:
        """:return: Every open pull request on the repository, oldest page first."""
        return self._pull_requests_in_state(PullRequestListState.OPEN)

    def all_pull_requests(self) -> list[RestPullRequest]:
        """:return: Every pull request on the repository, open or closed."""
        return self._pull_requests_in_state(PullRequestListState.ALL)

    def issue(self, number: int) -> Issue:
        entry = self.api.get(self.route.issue(number))
        if Issue.is_pull_request(entry):
            raise NotAnIssueError(number)
        return Issue.from_json(entry)

    def _pull_requests_in_state(
        self, state: PullRequestListState
    ) -> list[RestPullRequest]:
        """
        :param state: Which pull requests to list.
        :return: Them, oldest page first.
        """
        listing = self.route.listing(
            self.route.pull_requests, {QueryParameter.STATE: state.query}
        )
        return [
            RestPullRequest.from_json(entry) for entry in self._every_entry(listing)
        ]

    def labels(self) -> set[str]:
        return {
            label[RestJSONKey.NAME]
            for label in self._every_entry(self.route.listing(self.route.labels))
        }

    def create_label(self, label: GitHubLabel) -> None:
        payload = {RestJSONKey.NAME: label, RestJSONKey.DESCRIPTION: label.description}
        if label.color is not None:
            payload[RestJSONKey.COLOR] = label.color
        self.api.request("POST", self.route.labels, payload)

    def check_state(self, commit: str) -> RollupState:
        checks = CommitCheckReader(self.api, self.route).checks(commit)
        return RollupState.NOT_REPORTED if checks is None else checks.state

    def authenticated_login(self) -> str:
        account = self.api.get(self.route.authenticated_user())
        return str(account[RestJSONKey.LOGIN])

    def _every_entry(self, listing: str) -> list[Any]:
        """
        :param listing: A paged listing whose pages are lists.
        :return: Every entry of every page, first page first.
        """
        return [entry for page in self.api.get_pages(listing) for entry in page]

    def pull_request(self, number: int) -> RestPullRequest:
        return RestPullRequest.from_json(self.api.get(self.route.pull_request(number)))

    def replace_labels(self, number: int, labels: Sequence[str]) -> None:
        """
        Write a pull request's complete label set.

        :param number: The pull request to write.
        :param labels: The complete set it must end up with - this call replaces rather
            than adds.
        """
        self.api.request(
            "PUT", self.route.issue_labels(number), {RestJSONKey.LABELS: list(labels)}
        )

    def add_labels(self, number: int, labels: Sequence[str]) -> None:
        self.api.request(
            "POST", self.route.issue_labels(number), {RestJSONKey.LABELS: list(labels)}
        )

    def remove_label(self, number: int, label: str) -> None:
        self.api.request("DELETE", self.route.issue_label(number, label))

    def add_comment(self, number: int, body: str) -> str:
        """:param number: The pull request to comment on.
        :param body: The comment.
        :return: The comment's URL."""
        created = self.api.request(
            "POST", self.route.issue_comments(number), {RestJSONKey.BODY: body}
        )
        return str(created[RestJSONKey.HTML_URL])

    def comments(self, number: int) -> list[IssueComment]:
        return [
            IssueComment.from_json(entry)
            for entry in self._every_entry(
                self.route.listing(self.route.issue_comments(number))
            )
        ]

    def set_description(self, number: int, body: str) -> None:
        """
        Rewrite a pull request's description and nothing else.

        :param number: The pull request to write.
        :param body: The new description.
        """
        self.api.request(
            "PATCH", self.route.pull_request(number), {RestJSONKey.BODY: body}
        )

    def open_draft(self, head: str, base: str, title: str, body: str) -> int:
        created = self.api.request(
            "POST",
            self.route.pull_requests,
            {
                RestJSONKey.HEAD: head,
                RestJSONKey.BASE: base,
                RestJSONKey.TITLE: title,
                RestJSONKey.BODY: body,
                RestJSONKey.DRAFT: True,
            },
        )
        return int(created[RestJSONKey.NUMBER])

    def default_branch(self) -> str:
        return RestRepository.from_json(self.api.get(self.route.root)).default_branch

    def deletes_merged_branches(self) -> bool:
        return RestRepository.from_json(
            self.api.get(self.route.root)
        ).deletes_merged_branches

    def turn_on_merged_branch_deletion(self) -> bool:
        return self.api.attempt(
            "PATCH", self.route.root, {RestJSONKey.DELETE_BRANCH_ON_MERGE: True}
        ).succeeded

    def issues_enabled(self) -> bool:
        return RestRepository.from_json(self.api.get(self.route.root)).issues_enabled

    def turn_on_issues(self) -> bool:
        return self.api.attempt(
            "PATCH", self.route.root, {RestJSONKey.HAS_ISSUES: True}
        ).succeeded

    def actions_enabled(self) -> bool | None:
        permissions = self.api.attempt("GET", self.route.actions_permissions)
        if not permissions.succeeded:
            return None
        return bool(permissions.body[RestJSONKey.ENABLED])

    def turn_on_actions(self) -> bool:
        return self.api.attempt(
            "PUT", self.route.actions_permissions, {RestJSONKey.ENABLED: True}
        ).succeeded

    def open_issue(self, title: str, body: str, labels: Sequence[str]) -> int:
        created = self.api.request(
            "POST",
            self.route.issues(),
            {
                RestJSONKey.TITLE: title,
                RestJSONKey.BODY: body,
                RestJSONKey.LABELS: list(labels),
            },
        )
        return int(created[RestJSONKey.NUMBER])

    def issues(self, labels: Sequence[str], state: IssueState) -> list[Issue]:
        listing = self.route.listing(
            self.route.issues(),
            {QueryParameter.LABELS: ",".join(labels), QueryParameter.STATE: state},
        )
        return [
            Issue.from_json(entry)
            for entry in self._every_entry(listing)
            if not Issue.is_pull_request(entry)
        ]

    def close_issue(self, number: int, reason: IssueStateReason) -> None:
        self.api.request(
            "PATCH",
            self.route.issue(number),
            {RestJSONKey.STATE: IssueState.CLOSED, RestJSONKey.STATE_REASON: reason},
        )

    def awaiting_my_review(self) -> int:
        found = self.api.get(self.route.review_requests())
        return int(found[RestJSONKey.TOTAL_COUNT])

    def set_base(self, number: int, branch: str) -> None:
        self.api.request(
            "PATCH", self.route.pull_request(number), {RestJSONKey.BASE: branch}
        )

    def stacks(self) -> list[Stack]:
        return [
            Stack.from_json(entry)
            for entry in self._every_entry(self.route.listing(self.route.stacks))
        ]

    def stack(self, number: int) -> Stack:
        return Stack.from_json(self.api.get(self.route.stack(number)))

    def stack_of(self, pull_request: int) -> Stack | None:
        found = self.api.get(self.route.stacks_holding(pull_request))
        return Stack.from_json(found[0]) if found else None

    def create_stack(self, pull_requests: Sequence[int]) -> Stack:
        return Stack.from_json(
            self.api.request(
                "POST",
                self.route.stacks,
                {RestJSONKey.PULL_REQUESTS: list(pull_requests)},
            )
        )

    def add_to_stack(self, stack: Stack, pull_requests: Sequence[int]) -> Stack:
        return Stack.from_json(
            self.api.request(
                "POST",
                self.route.stack_action(stack.number, StackAction.ADD),
                {RestJSONKey.PULL_REQUESTS: list(pull_requests)},
            )
        )

    def unstack(self, stack: Stack) -> Stack | None:
        remaining = self.api.request(
            "POST", self.route.stack_action(stack.number, StackAction.UNSTACK)
        )
        return None if remaining is None else Stack.from_json(remaining)
