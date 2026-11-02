"""
The interfaces through which GitHub is read, and the client implementing them over HTTP.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from http import HTTPStatus
from pathlib import Path
from typing import Any

from basstler_domain_model.class_property import classproperty
from basstler_domain_model.commands import CommandRunner
from basstler_domain_model.environment import GitHubActionsVariable
from basstler_domain_model.github.credential import GitHubToken
from basstler_domain_model.github.exceptions import GitHubRequestFailed
from basstler_domain_model.github.pull_request_models import GraphQLResponse
from basstler_domain_model.github.vocabulary import PullRequestJSONKey
from basstler_domain_model.repository import GitHubAddress, Repository

# %% what reads GitHub


class JobLogReader(ABC):
    """
    Reads the log one Actions job recorded.
    """

    @abstractmethod
    def read_job_log(self, repository: Repository, job_identifier: int) -> str:
        """
        Read one job's whole log.

        :param repository: The repository the job ran in.
        :param job_identifier: The job to read.
        :return: The log, exactly as the runner recorded it.
        """


class GraphQLClient(ABC):
    """
    Sends a GraphQL document to GitHub and returns its ``data`` data.
    """

    @abstractmethod
    def execute(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        """
        Run one GraphQL query.

        :param query: The GraphQL document.
        :param variables: The document's variables.
        :return: The response's ``data`` data.
        """


class RestClient(ABC):
    """
    Reads REST responses from GitHub.
    """

    @abstractmethod
    def get(self, path: str) -> Any:
        """
        Read one response.

        :param path: The REST path, query included.
        :return: The parsed response.
        """

    @abstractmethod
    def get_pages(self, path: str) -> list[Any]:
        """
        Read every page of a paged response.

        :param path: The REST path of the first page, query included.
        :return: Each page's parsed response, in order.
        """


# %% one answer


@dataclass(frozen=True)
class RestAnswer:
    """
    What the API answered one call with, a refusal included.
    """

    status: int
    """
    The HTTP status.
    """

    text: str
    """
    The body, as it came.
    """

    headers: Mapping[str, str] = field(default_factory=dict)
    """
    The response headers, by lowercased name.
    """

    @classproperty
    def redirect_statuses(cls) -> frozenset[int]:
        """
        The statuses that send a caller to another address.
        """
        return frozenset(
            {
                HTTPStatus.MOVED_PERMANENTLY,
                HTTPStatus.FOUND,
                HTTPStatus.SEE_OTHER,
                HTTPStatus.TEMPORARY_REDIRECT,
                HTTPStatus.PERMANENT_REDIRECT,
            }
        )

    @property
    def succeeded(self) -> bool:
        """:return: Whether the status is a 2xx one."""
        return 200 <= self.status < 300

    @property
    def body(self) -> Any:
        """:return: The body decoded as JSON, ``None`` when it is empty."""
        return json.loads(self.text) if self.text else None

    @property
    def redirect(self) -> str | None:
        """:return: The address the answer sends the caller to, ``None`` when it sends
        it nowhere."""
        if self.status not in self.redirect_statuses:
            return None
        return self.headers.get("location")

    @property
    def next_page(self) -> str | None:
        """:return: The address of the next page of a paged listing, ``None`` on the
        last page."""
        found = re.search(r'<([^>]+)>;\s*rel="next"', self.headers.get("link", ""))
        return found.group(1) if found else None


# %% the client


class NoAutomaticRedirect(urllib.request.HTTPRedirectHandler):
    """
    Hands every redirect back as an answer, so the client decides whether the token
    travels with it.
    """

    def redirect_request(self, *arguments: Any) -> None:
        """:return: Nothing, so the redirect is answered rather than followed."""
        return None


@dataclass(frozen=True)
class GitHubApi(GraphQLClient, RestClient, JobLogReader):
    """
    GitHub's REST and GraphQL APIs, called over HTTP with a token.
    """

    token: str
    """
    The credential the calls authenticate with.
    """

    api_root: str = GitHubAddress.API
    """
    Where the API answers.
    """

    timeout_seconds: float = 30.0
    """
    How long a call may wait on the API before it fails.
    """

    @classmethod
    def from_environment(cls) -> GitHubApi:
        """
        :return: A client with the environment's token, or ``gh``'s, at the API root a
            GitHub Actions runner names, or GitHub's own.
        :raises GitHubCredentialUnavailableError: If no token is found.
        """
        return cls(
            GitHubToken(CommandRunner(Path.cwd())).find(),
            GitHubActionsVariable.API_URL.read() or GitHubAddress.API,
        )

    def attempt(
        self, method: str, path: str, payload: Mapping[str, Any] | None = None
    ) -> RestAnswer:
        """
        Make one call whose refusal is an expected outcome, following a redirect, with
        the token only when it stays on the API's host.

        :param method: The HTTP method.
        :param path: The path below the API root, with or without a leading slash, or a
            whole address the API handed out.
        :param payload: The JSON body, absent for a read.
        :return: What the API answered, a refusal included.
        """
        address = (
            path
            if path.startswith(self.api_root)
            else f"{self.api_root}/{path.removeprefix('/')}"
        )
        answer = self._exchange(method, address, payload, authorized=True)
        if answer.redirect is None:
            return answer
        same_host = (
            urllib.parse.urlsplit(answer.redirect).netloc
            == urllib.parse.urlsplit(self.api_root).netloc
        )
        return self._exchange("GET", answer.redirect, None, authorized=same_host)

    def request(
        self, method: str, path: str, payload: Mapping[str, Any] | None = None
    ) -> Any:
        """
        Make one call the caller depends on.

        :param method: The HTTP method.
        :param path: The path below the API root.
        :param payload: The JSON body, absent for a read.
        :return: The decoded answer, ``None`` when it has no body.
        :raises GitHubRequestFailed: If the API refuses the call.
        """
        return self._succeeded(method, path, self.attempt(method, path, payload)).body

    def execute(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        """
        :raises GitHubRequestFailed: If the API refuses the call.
        :raises GraphQLErrorsReturned: If GitHub answers with errors.
        """
        payload = {
            PullRequestJSONKey.QUERY: query,
            PullRequestJSONKey.VARIABLES: variables,
        }
        answer = self._succeeded(
            "POST", "graphql", self.attempt("POST", "graphql", payload)
        )
        return GraphQLResponse.from_json(answer.text).result()

    def get(self, path: str) -> Any:
        """
        :raises GitHubRequestFailed: If the API refuses the call.
        """
        return self.request("GET", path)

    def get_pages(self, path: str) -> list[Any]:
        """
        :raises GitHubRequestFailed: If the API refuses a page.
        """
        pages = []
        address: str | None = path
        while address is not None:
            answer = self._succeeded("GET", address, self.attempt("GET", address))
            pages.append(answer.body)
            address = answer.next_page
        return pages

    def read_job_log(self, repository: Repository, job_identifier: int) -> str:
        """
        :raises GitHubRequestFailed: If the API refuses the call.
        """
        path = repository.job_log_path(job_identifier)
        return self._succeeded("GET", path, self.attempt("GET", path)).text

    @staticmethod
    def _succeeded(method: str, path: str, answer: RestAnswer) -> RestAnswer:
        """
        :param method: The HTTP method the answer is to.
        :param path: The path it is to.
        :param answer: The answer.
        :return: It, when it succeeded.
        :raises GitHubRequestFailed: When it did not.
        """
        if not answer.succeeded:
            raise GitHubRequestFailed(
                status=answer.status, detail=answer.text, method=method, path=path
            )
        return answer

    def _exchange(
        self,
        method: str,
        address: str,
        payload: Mapping[str, Any] | None,
        authorized: bool,
    ) -> RestAnswer:
        """
        :param method: The HTTP method.
        :param address: The whole address to call.
        :param payload: The JSON body, absent for a read.
        :param authorized: Whether the token goes with the call.
        :return: What came back, a refusal or a redirect included.
        :raises GitHubRequestFailed: If no answer came back.
        """
        headers = {
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        }
        if authorized:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(
            address,
            method=method,
            data=None if payload is None else json.dumps(payload).encode(),
            headers=headers,
        )
        opener = urllib.request.build_opener(NoAutomaticRedirect())
        try:
            with opener.open(request, timeout=self.timeout_seconds) as response:
                return RestAnswer(
                    response.status,
                    response.read().decode(errors="replace"),
                    {name.lower(): value for name, value in response.headers.items()},
                )
        except urllib.error.HTTPError as refused:
            return RestAnswer(
                refused.code,
                refused.read().decode(errors="replace"),
                {
                    name.lower(): value
                    for name, value in (refused.headers or {}).items()
                },
            )
        except (urllib.error.URLError, TimeoutError) as unanswered:
            raise GitHubRequestFailed(
                status=None,
                detail=str(unanswered),
                method=method,
                path=address,
            ) from unanswered
