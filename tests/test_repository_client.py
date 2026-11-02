"""
Tests for the repository client's calls that open a pull request and read the repository
itself, against replayed REST answers.
"""

from __future__ import annotations

import json
from http import HTTPStatus
from urllib.parse import parse_qs, urlsplit

import pytest

from basstler_domain_model.github.clients import GitHubApi
from basstler_domain_model.github.exceptions import NotAnIssueError
from basstler_domain_model.github.issue_models import Issue, IssueComment
from basstler_domain_model.github.labels import GitHubLabel
from basstler_domain_model.github.replayed_api import RecordedAnswer, ReplayedApi
from basstler_domain_model.github.repository_client import GitHubRepository
from basstler_domain_model.github.routes import QueryParameter, RepositoryRoute
from basstler_domain_model.github.vocabulary import (
    ClosingKeyword,
    IssueState,
    IssueStateReason,
    RestJSONKey,
)
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


# %% issues and Actions


def test_whether_issues_are_on_is_read_from_the_repository():
    answers = {
        ("GET", f"/{ROUTE.root}"): answer(
            HTTPStatus.OK, {RestJSONKey.HAS_ISSUES: False}
        )
    }

    with ReplayedApi(answers) as api:
        assert client(api).issues_enabled() is False


def test_turning_on_issues_asks_github_for_them():
    answers = {("PATCH", f"/{ROUTE.root}"): answer(HTTPStatus.OK, {})}

    with ReplayedApi(answers) as api:
        accepted = client(api).turn_on_issues()

    assert accepted is True
    assert api.sent[0].payload == {RestJSONKey.HAS_ISSUES: True}


def test_whether_actions_may_run_is_read_from_their_permissions():
    answers = {
        ("GET", f"/{ROUTE.actions_permissions}"): answer(
            HTTPStatus.OK, {RestJSONKey.ENABLED: False}
        )
    }

    with ReplayedApi(answers) as api:
        assert client(api).actions_enabled() is False


def test_actions_a_credential_may_not_read_are_unknown():
    answers = {
        ("GET", f"/{ROUTE.actions_permissions}"): answer(
            HTTPStatus.FORBIDDEN, {"message": "not permitted"}
        )
    }

    with ReplayedApi(answers) as api:
        assert client(api).actions_enabled() is None


def test_turning_on_actions_asks_github_for_them():
    answers = {("PUT", f"/{ROUTE.actions_permissions}"): answer(HTTPStatus.OK, {})}

    with ReplayedApi(answers) as api:
        accepted = client(api).turn_on_actions()

    assert accepted is True
    assert api.sent[0].payload == {RestJSONKey.ENABLED: True}


# %% the issue board


def issue_entry(number: int, labels: list[str]) -> dict[str, object]:
    """:param number: The issue's number.
    :param labels: The names of its labels.
    :return: The issue as the issues API lists it."""
    return {
        RestJSONKey.NUMBER: number,
        RestJSONKey.TITLE: f"Issue {number}",
        RestJSONKey.LABELS: [{RestJSONKey.NAME: label} for label in labels],
        RestJSONKey.STATE: IssueState.OPEN.value,
    }


def test_an_issue_is_filed_with_its_labels():
    answers = {
        ("POST", f"/{ROUTE.issues()}"): answer(
            HTTPStatus.CREATED, {RestJSONKey.NUMBER: 12}
        )
    }

    with ReplayedApi(answers) as api:
        number = client(api).open_issue("A title", "A body", ["finding"])

    assert number == 12
    assert api.sent[0].payload == {
        RestJSONKey.TITLE: "A title",
        RestJSONKey.BODY: "A body",
        RestJSONKey.LABELS: ["finding"],
    }


def test_listed_issues_leave_the_pull_requests_out():
    listing = ROUTE.listing(
        ROUTE.issues(),
        {QueryParameter.LABELS: "finding", QueryParameter.STATE: IssueState.OPEN},
    )
    pull_request = {**issue_entry(2, ["finding"]), RestJSONKey.PULL_REQUEST: {}}
    answers = {
        ("GET", f"/{listing}"): RecordedAnswer(
            HTTPStatus.OK, json.dumps([issue_entry(1, ["finding"]), pull_request])
        )
    }

    with ReplayedApi(answers) as api:
        issues = client(api).issues(["finding"], IssueState.OPEN)

    assert issues == [Issue(1, "Issue 1", ("finding",), IssueState.OPEN)]


def test_one_issue_is_read_with_its_labels():
    answers = {
        ("GET", f"/{ROUTE.issue(4)}"): answer(
            HTTPStatus.OK, issue_entry(4, ["finding", "urgent"])
        )
    }

    with ReplayedApi(answers) as api:
        issue = client(api).issue(4)

    assert issue == Issue(4, "Issue 4", ("finding", "urgent"), IssueState.OPEN)


def test_reading_a_pull_request_as_an_issue_is_refused():
    pull_request = {**issue_entry(5, []), RestJSONKey.PULL_REQUEST: {}}
    answers = {("GET", f"/{ROUTE.issue(5)}"): answer(HTTPStatus.OK, pull_request)}

    with ReplayedApi(answers) as api, pytest.raises(NotAnIssueError):
        client(api).issue(5)


def test_added_labels_are_sent_alone():
    answers = {("POST", f"/{ROUTE.issue_labels(6)}"): answer(HTTPStatus.OK, {})}

    with ReplayedApi(answers) as api:
        client(api).add_labels(6, ["finding", "urgent"])

    assert api.sent[0].payload == {RestJSONKey.LABELS: ["finding", "urgent"]}


def test_a_removed_label_is_named_in_the_path():
    answers = {
        ("DELETE", f"/{ROUTE.issue_label(7, 'priority: low')}"): answer(
            HTTPStatus.OK, {}
        )
    }

    with ReplayedApi(answers) as api:
        client(api).remove_label(7, "priority: low")

    assert [request.method for request in api.sent] == ["DELETE"]


def test_a_slash_in_an_issue_label_stays_within_its_path_segment():
    assert ROUTE.issue_label(8, "type/bug") == f"{ROUTE.issue_labels(8)}/type%2Fbug"


def test_an_issue_is_closed_with_its_reason():
    answers = {("PATCH", f"/{ROUTE.issue(3)}"): answer(HTTPStatus.OK, {})}

    with ReplayedApi(answers) as api:
        client(api).close_issue(3, IssueStateReason.NOT_PLANNED)

    assert api.sent[0].payload == {
        RestJSONKey.STATE: IssueState.CLOSED,
        RestJSONKey.STATE_REASON: IssueStateReason.NOT_PLANNED,
    }


def test_a_label_with_a_colour_is_created_in_it():
    class ColouredLabel(GitHubLabel):
        description = "A coloured label"
        color = "b60205"

    answers = {("POST", f"/{ROUTE.labels}"): answer(HTTPStatus.CREATED, {})}

    with ReplayedApi(answers) as api:
        client(api).create_label(ColouredLabel("urgent"))

    assert api.sent[0].payload == {
        RestJSONKey.NAME: "urgent",
        RestJSONKey.DESCRIPTION: ColouredLabel.description,
        RestJSONKey.COLOR: ColouredLabel.color,
    }


def test_an_issue_s_comments_are_read_with_their_authors():
    listing = ROUTE.listing(ROUTE.issue_comments(9))
    entries = [
        {RestJSONKey.USER: {RestJSONKey.LOGIN: "an-owner"}, RestJSONKey.BODY: "First"},
        {RestJSONKey.USER: {RestJSONKey.LOGIN: "someone"}, RestJSONKey.BODY: "Second"},
    ]
    answers = {
        ("GET", f"/{listing}"): RecordedAnswer(HTTPStatus.OK, json.dumps(entries))
    }

    with ReplayedApi(answers) as api:
        comments = client(api).comments(9)

    assert comments == [
        IssueComment("an-owner", "First"),
        IssueComment("someone", "Second"),
    ]


def test_a_closing_reference_is_the_keyword_before_the_issue_s_number():
    assert ClosingKeyword.FIXES.reference(3) == f"{ClosingKeyword.FIXES} #3"


# %% review requests


def test_the_pull_requests_awaiting_my_review_are_counted():
    answers = {
        ("GET", f"/{ROUTE.review_requests()}"): answer(
            HTTPStatus.OK, {RestJSONKey.TOTAL_COUNT: 2, "items": []}
        )
    }

    with ReplayedApi(answers) as api:
        assert client(api).awaiting_my_review() == 2


def test_only_the_repository_s_review_requests_are_searched():
    query = parse_qs(urlsplit(ROUTE.review_requests()).query)

    assert f"repo:{REPOSITORY.full_name}" in query[QueryParameter.SEARCH][0].split()
