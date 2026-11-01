"""
Tests for :class:`basstler_domain_model.github.clients.GitHubApi`: REST, GraphQL and job
logs over HTTP, against answers replayed by a local server.
"""

from __future__ import annotations

import json
from http import HTTPStatus

import pytest

from basstler_domain_model.github.clients import GitHubApi
from basstler_domain_model.github.exceptions import (
    GitHubRequestFailed,
    GraphQLErrorsReturned,
)
from basstler_domain_model.github.replayed_api import RecordedAnswer, ReplayedApi
from basstler_domain_model.github.vocabulary import PullRequestJSONKey
from basstler_domain_model.repository import Repository

from .dataset.locations import DatasetLocation

TOKEN = "a-token"
"""
The token every client in these tests calls with.
"""

REPOSITORY = Repository("an-owner", "a-repository")
"""
The repository the job logs are read from.
"""

# %% REST


def test_a_response_is_read_from_its_path():
    path = f"/{REPOSITORY.api_path}/pulls/1"
    answers = {
        ("GET", path): RecordedAnswer.from_file(HTTPStatus.OK, DatasetLocation.PAGE_ONE)
    }

    with ReplayedApi(answers) as api:
        read = GitHubApi(TOKEN, api.url).get(path)

    assert read == json.loads(DatasetLocation.PAGE_ONE.read_text())
    assert api.sent[0].authorization == f"Bearer {TOKEN}"


def test_every_page_is_collected_by_following_the_next_link():
    first, second = (
        f"/{REPOSITORY.api_path}/pulls",
        f"/{REPOSITORY.api_path}/pulls?page=2",
    )
    with ReplayedApi() as api:
        api.answers[("GET", first)] = RecordedAnswer(
            HTTPStatus.OK,
            DatasetLocation.PAGE_ONE.read_text(),
            {"Link": f'<{api.url}{second}>; rel="next"'},
        )
        api.answers[("GET", second)] = RecordedAnswer.from_file(
            HTTPStatus.OK, DatasetLocation.PAGE_TWO
        )

        pages = GitHubApi(TOKEN, api.url).get_pages(first)

    assert pages == [
        json.loads(DatasetLocation.PAGE_ONE.read_text()),
        json.loads(DatasetLocation.PAGE_TWO.read_text()),
    ]


def test_a_refused_call_is_raised_with_its_status():
    with ReplayedApi() as api:
        with pytest.raises(GitHubRequestFailed) as raised:
            GitHubApi(TOKEN, api.url).get("/repos/missing")

    assert raised.value.status == HTTPStatus.NOT_FOUND


def test_an_attempt_reports_a_refusal_instead_of_raising_it():
    path = "/user"
    answers = {
        ("GET", path): RecordedAnswer.from_file(
            HTTPStatus.FORBIDDEN, DatasetLocation.REFUSAL
        )
    }

    with ReplayedApi(answers) as api:
        answer = GitHubApi(TOKEN, api.url).attempt("GET", path)

    assert answer.status == HTTPStatus.FORBIDDEN
    assert answer.body == json.loads(DatasetLocation.REFUSAL.read_text())


# %% GraphQL


def test_a_query_and_its_variables_are_sent_and_its_data_unwrapped():
    answers = {
        ("POST", "/graphql"): RecordedAnswer.from_file(
            HTTPStatus.OK, DatasetLocation.GRAPHQL_DATA
        )
    }
    query, variables = "query { viewer { login } }", {"number": 1}

    with ReplayedApi(answers) as api:
        data = GitHubApi(TOKEN, api.url).execute(query, variables)

    assert api.sent[0].payload == {
        PullRequestJSONKey.QUERY: query,
        PullRequestJSONKey.VARIABLES: variables,
    }
    assert (
        data
        == json.loads(DatasetLocation.GRAPHQL_DATA.read_text())[PullRequestJSONKey.DATA]
    )


def test_graphql_errors_are_raised_rather_than_returned():
    answers = {
        ("POST", "/graphql"): RecordedAnswer.from_file(
            HTTPStatus.OK, DatasetLocation.GRAPHQL_ERRORS
        )
    }

    with ReplayedApi(answers) as api:
        with pytest.raises(GraphQLErrorsReturned) as raised:
            GitHubApi(TOKEN, api.url).execute("query {}", {})

    recorded = json.loads(DatasetLocation.GRAPHQL_ERRORS.read_text())[
        PullRequestJSONKey.ERRORS
    ]
    assert raised.value.messages == [
        error[PullRequestJSONKey.MESSAGE] for error in recorded
    ]


# %% job logs


def test_a_job_log_is_followed_to_storage_without_the_token():
    """
    GitHub answers a job log with a redirect to blob storage, which must not be sent the
    token.
    """
    log_path = f"/{REPOSITORY.job_log_path(7)}"
    with ReplayedApi() as storage, ReplayedApi() as github:
        storage.answers[("GET", "/log")] = RecordedAnswer.from_file(
            HTTPStatus.OK, DatasetLocation.JOB_LOG
        )
        github.answers[("GET", log_path)] = RecordedAnswer(
            HTTPStatus.FOUND, headers={"Location": f"{storage.url}/log"}
        )

        log = GitHubApi(TOKEN, github.url).read_job_log(REPOSITORY, 7)

    assert log == DatasetLocation.JOB_LOG.read_text()
    assert storage.sent[0].authorization is None
