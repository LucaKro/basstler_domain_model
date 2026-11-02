"""
Tests for :mod:`basstler_domain_model.github.pull_request_fields`: reading a fetched
pull request field by field, and its head.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from basstler_domain_model.github.exceptions import MissingPullRequestFieldError
from basstler_domain_model.github.pull_request_fields import (
    PullRequestField,
    PullRequestHead,
    PullRequestHeadKey,
)
from basstler_domain_model.github.vocabulary import RestJSONKey

from .dataset.locations import DatasetLocation

# %% fixtures


@pytest.fixture
def record() -> dict[str, Any]:
    """:return: A pull request as REST answers it."""
    return json.loads(DatasetLocation.REST_PULL_REQUEST_RECORD.read_text())


# %% reading one field


def test_a_missing_required_field_is_refused_naming_it() -> None:
    record = json.loads(
        DatasetLocation.REST_PULL_REQUEST_RECORD_WITHOUT_DRAFT.read_text()
    )

    with pytest.raises(MissingPullRequestFieldError) as raised:
        PullRequestField.DRAFT.read(record, 10)

    assert raised.value.field_name is PullRequestField.DRAFT


def test_an_absent_optional_field_reads_as_none(record: dict[str, Any]) -> None:
    assert PullRequestField.BODY.read(record) is None


def test_a_nested_branch_reads_as_its_name(record: dict[str, Any]) -> None:
    assert (
        PullRequestField.BASE.read(record)
        == record[RestJSONKey.BASE][PullRequestHeadKey.REFERENCE]
    )


def test_labels_given_as_objects_read_as_their_names(record: dict[str, Any]) -> None:
    assert PullRequestField.LABELS.read(record) == [
        label[RestJSONKey.NAME] for label in record[RestJSONKey.LABELS]
    ]


# %% the head


def test_a_head_names_its_branch_repository_and_commit(
    record: dict[str, Any],
) -> None:
    head = record[RestJSONKey.HEAD]

    assert PullRequestHead.from_record(record, 10) == PullRequestHead(
        branch=head[PullRequestHeadKey.REFERENCE],
        repository=head[PullRequestHeadKey.HEAD_REPOSITORY][
            PullRequestHeadKey.FULL_NAME
        ],
        commit=head[RestJSONKey.SHA],
    )


def test_a_head_whose_repository_was_deleted_has_none() -> None:
    record = json.loads(
        DatasetLocation.REST_PULL_REQUEST_RECORD_HEAD_REPOSITORY_DELETED.read_text()
    )

    assert PullRequestHead.from_record(record, 10).repository is None


def test_a_head_without_its_commit_is_refused() -> None:
    record = json.loads(
        DatasetLocation.REST_PULL_REQUEST_RECORD_HEAD_WITHOUT_COMMIT.read_text()
    )

    with pytest.raises(MissingPullRequestFieldError) as raised:
        PullRequestHead.from_record(record, 10)

    assert raised.value.field_name is PullRequestField.HEAD
