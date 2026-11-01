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

    STACK_CREATED = DIRECTORY / "stacks" / "create.json"
    """
    A stack of two pull requests, as creating it answered.
    """

    STACK_GROWN = DIRECTORY / "stacks" / "add.json"
    """
    The same stack with a third pull request put on top, as adding it answered.
    """

    STACK_READ = DIRECTORY / "stacks" / "get.json"
    """
    The same stack, read by its number.
    """

    STACKS_HOLDING_A_PULL_REQUEST = DIRECTORY / "stacks" / "find.json"
    """
    The stacks holding the stack's middle pull request: the stack itself.
    """

    STACKS_HOLDING_NOTHING = DIRECTORY / "stacks" / "find-none.json"
    """
    The stacks holding a pull request no stack holds: none.
    """

    STACKS_LISTED = DIRECTORY / "stacks" / "list.json"
    """
    Every stack in the repository, one page.
    """

    STACK_WITH_ITS_BOTTOM_MERGED = DIRECTORY / "stacks" / "find-bottom-merged.json"
    """
    The stack found by pull request, its bottom pull request merged.
    """

    GRAPHQL_DATA = DIRECTORY / "api" / "graphql-data.json"
    """
    A GraphQL answer carrying data.
    """

    GRAPHQL_ERRORS = DIRECTORY / "api" / "graphql-errors.json"
    """
    A GraphQL answer carrying errors instead of data.
    """

    PAGE_ONE = DIRECTORY / "api" / "page-one.json"
    """
    The first page of a listing.
    """

    PAGE_TWO = DIRECTORY / "api" / "page-two.json"
    """
    The second and last page of the same listing.
    """

    JOB_LOG = DIRECTORY / "api" / "job-log.txt"
    """
    A job's log, as blob storage serves it.
    """

    REFUSAL = DIRECTORY / "api" / "refusal.json"
    """
    The body of a refused call.
    """

    GH_STUB = DIRECTORY / "stubs" / "gh.sh"
    """
    A ``gh`` that only answers ``gh auth token``, with ``STUB_TOKEN``.
    """
