"""
Tests for the repository client's calls that open a pull request and read the repository
itself, against replayed REST answers.
"""

from __future__ import annotations

import json
from http import HTTPStatus

from basstler_domain_model.github.clients import GitHubApi
from basstler_domain_model.github.replayed_api import RecordedAnswer, ReplayedApi
from basstler_domain_model.github.repository_client import GitHubRepository
from basstler_domain_model.github.routes import RepositoryRoute
from basstler_domain_model.github.vocabulary import RestJSONKey
from basstler_domain_model.repository import Repository

REPOSITORY = Repository("an-owner", "a-repository")
"""
The repository every call in these tests is made against.
"""

ROUTE = RepositoryRoute(REPOSITORY)
"""
Its REST paths.
"""

# %% helpers


def client(api: ReplayedApi) -> GitHubRepository:
    """:param api: The replayed API.
    :return: A client calling it."""
    return GitHubRepository(REPOSITORY, GitHubApi("a-token", api.url))


def answer(status: HTTPStatus, body: dict[str, object]) -> RecordedAnswer:
    """:param status: The status to answer with.
    :param body: The body to answer with.
    :return: The answer."""
    return RecordedAnswer(status, json.dumps(body))


# %% opening a pull request


def test_a_draft_is_opened_from_the_head_onto_the_base():
    answers = {
        ("POST", f"/{ROUTE.pull_requests}"): answer(
            HTTPStatus.CREATED, {RestJSONKey.NUMBER: 7}
        )
    }

    with ReplayedApi(answers) as api:
        number = client(api).open_draft("feature", "main", "A title", "A body")

    assert number == 7
    assert api.sent[0].payload == {
        RestJSONKey.HEAD: "feature",
        RestJSONKey.BASE: "main",
        RestJSONKey.TITLE: "A title",
        RestJSONKey.BODY: "A body",
        RestJSONKey.DRAFT: True,
    }


# %% the repository itself


def test_the_default_branch_is_read_from_the_repository():
    answers = {
        ("GET", f"/{ROUTE.root}"): answer(
            HTTPStatus.OK, {RestJSONKey.DEFAULT_BRANCH: "trunk"}
        )
    }

    with ReplayedApi(answers) as api:
        assert client(api).default_branch() == "trunk"


def test_whether_merged_branches_are_deleted_is_read_from_the_repository():
    answers = {
        ("GET", f"/{ROUTE.root}"): answer(
            HTTPStatus.OK, {RestJSONKey.DELETE_BRANCH_ON_MERGE: False}
        )
    }

    with ReplayedApi(answers) as api:
        assert client(api).deletes_merged_branches() is False


# %% changing settings


def test_turning_on_merged_branch_deletion_asks_github_for_it():
    answers = {
        ("PATCH", f"/{ROUTE.root}"): answer(
            HTTPStatus.OK, {RestJSONKey.DELETE_BRANCH_ON_MERGE: True}
        )
    }

    with ReplayedApi(answers) as api:
        accepted = client(api).turn_on_merged_branch_deletion()

    assert accepted is True
    assert api.sent[0].payload == {RestJSONKey.DELETE_BRANCH_ON_MERGE: True}


def test_a_refused_settings_change_is_reported_rather_than_raised():
    answers = {
        ("PATCH", f"/{ROUTE.root}"): answer(
            HTTPStatus.FORBIDDEN, {"message": "settings writes are not permitted"}
        )
    }

    with ReplayedApi(answers) as api:
        assert client(api).turn_on_merged_branch_deletion() is False
