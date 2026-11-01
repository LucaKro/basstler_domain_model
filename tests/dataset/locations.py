"""
The files the tests read their payloads from, each named once.
"""

from __future__ import annotations

from pathlib import Path

from basstler_domain_model.locations import PathEnumeration


class DatasetLocation(PathEnumeration):
    """
    The recorded GitHub payloads the tests parse.
    """

    DIRECTORY = Path(__file__).parent
    """
    The directory holding every payload.
    """

    GRAPHQL_BRANCH_PULL_REQUEST_MERGED = (
        DIRECTORY / "graphql-branch-pull-request-merged.json"
    )
    """
    A pull request a GraphQL head-branch search found, merged.
    """

    REST_PULL_REQUEST_MERGED = DIRECTORY / "rest-pull-request-merged.json"
    """
    A pull request as REST describes it once merged: closed, with a merge time.
    """

    REST_PULL_REQUEST_CLOSED_UNMERGED = (
        DIRECTORY / "rest-pull-request-closed-unmerged.json"
    )
    """
    A pull request as REST describes it once closed without merging.
    """
