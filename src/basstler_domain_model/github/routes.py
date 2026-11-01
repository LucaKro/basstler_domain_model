"""
The REST paths the API is called at, each built in one place.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote, urlencode

from basstler_domain_model.class_property import classproperty
from basstler_domain_model.repository import Repository

# %% the paths


@dataclass(frozen=True)
class RepositoryRoute:
    """
    Every REST path below one repository, and the few beside it, as the API takes them.
    """

    repository: Repository
    """
    The repository the paths are under.
    """

    @classproperty
    def page_size(cls) -> int:
        """
        The most entries GitHub hands back per page, asked for so a long list takes as
        few requests as it can.
        """
        return 100

    def pull_requests_for_head(self, owner: str, branch: str) -> str:
        """
        :param owner: Whose branch to search for.
        :param branch: The branch's name.
        :return: The search for pull requests opened from it, in any state.
        """
        query = urlencode(
            {"head": f"{owner}:{branch}", "state": "all", "per_page": self.page_size},
            safe=":",
        )
        return f"{self.repository.api_path}/pulls?{query}"

    def pull_request(self, number: int) -> str:
        """
        :param number: The pull request's number.
        :return: The pull request itself.
        """
        return f"{self.repository.api_path}/pulls/{number}"

    def reviews(self, number: int) -> str:
        """
        :param number: The pull request's number.
        :return: Its submitted reviews.
        """
        return f"{self.pull_request(number)}/reviews?per_page={self.page_size}"

    def review_comments(self, number: int) -> str:
        """
        :param number: The pull request's number.
        :return: Every review comment on it, across all its threads.
        """
        return f"{self.pull_request(number)}/comments?per_page={self.page_size}"

    def review_threads(self, number: int) -> str:
        """
        The threads with their resolved state - a route of the Claude Code session
        proxy's own, standing in for the GraphQL GitHub keeps that state behind, which
        answers with every thread at once.

        :param number: The pull request's number.
        :return: Its review threads.
        """
        return f"{self.pull_request(number)}/ccr/review_threads"

    def check_runs(self, sha: str) -> str:
        """
        :param sha: The commit.
        :return: The check runs reported against it.
        """
        return (
            f"{self.repository.api_path}/commits/{sha}/check-runs"
            f"?per_page={self.page_size}"
        )

    def commit_status(self, sha: str) -> str:
        """
        :param sha: The commit.
        :return: The statuses posted against it.
        """
        return (
            f"{self.repository.api_path}/commits/{sha}/status"
            f"?per_page={self.page_size}"
        )

    @property
    def root(self) -> str:
        """:return: The repository itself."""
        return self.repository.api_path

    @property
    def pull_requests(self) -> str:
        """:return: The repository's pull requests."""
        return f"{self.root}/pulls"

    def issues(self, **filters: str) -> str:
        """
        :param filters: Query parameters narrowing the listing.
        :return: The repository's issues, its pull requests among them.
        """
        query = f"?{urlencode(filters)}" if filters else ""
        return f"{self.root}/issues{query}"

    def issue(self, number: int) -> str:
        """:param number: The issue.
        :return: That issue."""
        return f"{self.root}/issues/{number}"

    def issue_comments(self, number: int) -> str:
        """:param number: The issue or pull request.
        :return: Its comments."""
        return f"{self.issue(number)}/comments"

    @property
    def labels(self) -> str:
        """:return: The repository's labels."""
        return f"{self.root}/labels"

    def label(self, name: str) -> str:
        """:param name: The label.
        :return: That label."""
        return f"{self.labels}/{quote(name)}"

    def comparison(self, base: str, head: str) -> str:
        """
        :param base: The branch compared against.
        :param head: The branch compared.
        :return: How far *head* is ahead of and behind *base*.
        """
        return f"{self.root}/compare/{quote(base)}...{quote(head)}"

    @property
    def actions_permissions(self) -> str:
        """:return: Whether Actions may run in the repository, and which."""
        return f"{self.root}/actions/permissions"

    def workflow_runs(self, branch: str) -> str:
        """:param branch: The branch the runs were triggered on.
        :return: Its workflow runs, newest first."""
        return f"{self.root}/actions/runs?{urlencode({'branch': branch})}"

    def stacks_holding(self, number: int) -> str:
        """:param number: The pull request.
        :return: The stacks holding it."""
        return f"{self.root}/stacks?{urlencode({'pull_request': number})}"

    def unstacking(self, number: int) -> str:
        """:param number: The stack.
        :return: Where taking its pull requests out is asked for."""
        return f"{self.root}/stacks/{number}/unstack"

    @staticmethod
    def authenticated_user() -> str:
        """:return: The account the token belongs to."""
        return "user"

    @staticmethod
    def review_requests() -> str:
        """:return: The search for open pull requests waiting on the caller's review."""
        return f"search/issues?{urlencode({'q': 'is:open is:pr review-requested:@me'})}"
