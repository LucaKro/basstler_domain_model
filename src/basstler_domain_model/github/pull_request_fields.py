"""
Reading a fetched pull request field by field.

A fetch that drops a field is not partially correct, so every field is declared with how
to read it and whether it may be absent, and a pull request omitting a required one is
rejected rather than defaulted.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum, StrEnum
from typing import Any

from basstler_domain_model.github.exceptions import MissingPullRequestFieldError
from basstler_domain_model.github.vocabulary import RestJSONKey

PullRequestPayload = Mapping[str, Any]
"""
One pull request as the REST API answers it, before any field is read.
"""

# %% the fields a pull request is read by


class PullRequestHeadKey(StrEnum):
    """
    The keys of the object a pull request's head arrives as, beyond its commit.
    """

    REFERENCE = "ref"
    """
    The head branch's name.
    """

    HEAD_REPOSITORY = "repo"
    """
    The repository the head branch lives in, ``null`` once that repository is deleted.
    """

    FULL_NAME = "full_name"
    """
    A repository's ``owner/name``, under :attr:`HEAD_REPOSITORY`.
    """


class PullRequestFieldShape(StrEnum):
    """
    How one pull-request field's value has to be read.

    The API answers some fields with a nested object where a plain value would do, so
    reading is per-field rather than uniform.
    """

    VALUE = "value"
    """
    Taken as it comes.
    """

    BRANCH_REFERENCE = "branch-reference"
    """
    A branch, given either plainly or as an object carrying a ``ref``.
    """

    LABEL_NAMES = "label-names"
    """
    A list of labels, each given either plainly or as an object carrying a ``name``.
    """


@dataclass(frozen=True)
class PullRequestFieldSpecification:
    """
    What one pull-request field is called, how to read it, and whether it may be absent.
    """

    key: str
    """
    The key the API answers under.
    """

    shape: PullRequestFieldShape = PullRequestFieldShape.VALUE
    """
    How its value has to be read.
    """

    required: bool = False
    """
    Whether a record omitting it is rejected rather than read.
    """


class PullRequestField(PullRequestFieldSpecification, Enum):
    """
    Every pull-request field read out of a fetched pull request, and how to read it.

    Each member *is* a specification, so nothing outside this enum knows that ``head``
    arrives nested while ``draft`` does not, or which fields a pull request cannot be
    read without.

    A member is written as the specification it carries, and :meth:`__init__` unpacks it
    onto the member itself - so ``PullRequestField.HEAD.key`` reads directly and the
    member is a :class:`PullRequestFieldSpecification` in its own right.
    """

    def __init__(self, specification: PullRequestFieldSpecification) -> None:
        """
        Carry the specification's values on the member itself.

        Without this the mixin would receive the whole specification as its first
        argument - silently, landing the instance in :attr:`key` - since an enum passes
        a member's value straight to the type it mixes in.

        :param specification: What this field is called and how to read it.
        """
        for field in dataclasses.fields(PullRequestFieldSpecification):
            object.__setattr__(self, field.name, getattr(specification, field.name))

    NUMBER = PullRequestFieldSpecification(key=RestJSONKey.NUMBER, required=True)
    """
    The pull request's number.
    """
    HEAD = PullRequestFieldSpecification(
        key=RestJSONKey.HEAD,
        shape=PullRequestFieldShape.BRANCH_REFERENCE,
        required=True,
    )
    """The branch the pull request would merge - the stack node it names."""
    BASE = PullRequestFieldSpecification(
        key=RestJSONKey.BASE,
        shape=PullRequestFieldShape.BRANCH_REFERENCE,
        required=True,
    )
    """The branch it would merge into - its parent in the stack."""
    DRAFT = PullRequestFieldSpecification(key=RestJSONKey.DRAFT, required=True)
    """
    Whether its author has yet reviewed it themselves.
    """
    LABELS = PullRequestFieldSpecification(
        key=RestJSONKey.LABELS, shape=PullRequestFieldShape.LABEL_NAMES, required=True
    )
    """
    The labels it carries, which the workflow reads as state.
    """
    BODY = PullRequestFieldSpecification(key=RestJSONKey.BODY)
    """
    Its description, read for the session link and the promotion prefill.
    """
    TITLE = PullRequestFieldSpecification(key=RestJSONKey.TITLE)
    """
    Its title, which prefills the upstream pull request.
    """
    MERGEABLE_STATE = PullRequestFieldSpecification(key=RestJSONKey.MERGEABLE_STATE)
    """
    GitHub's own verdict on whether it currently conflicts with its base.
    """
    STATE = PullRequestFieldSpecification(key=RestJSONKey.STATE)
    """
    Whether it is open or closed, a merged one included among the closed.
    """
    MERGED_AT = PullRequestFieldSpecification(key=RestJSONKey.MERGED_AT)
    """
    When GitHub merged it, absent for one never merged through GitHub.
    """
    HTML_URL = PullRequestFieldSpecification(key=RestJSONKey.HTML_URL)
    """
    Its page on GitHub, which the issues API answers under the same key.
    """

    def read(self, record: PullRequestPayload, number: int | None = None) -> Any:
        """
        Read this field out of a fetched pull request.

        :param record: The fetched pull request.
        :param number: The pull request being read, named in any rejection.
        :return: The field's value, read according to its shape.
        :raises MissingPullRequestFieldError: If a required field is absent, or its
            value carries no name where its shape says one belongs.
        """
        value = record.get(self.key)
        if value is None:
            if self.required:
                raise MissingPullRequestFieldError(self, number)
            return None
        match self.shape:
            case PullRequestFieldShape.BRANCH_REFERENCE:
                return self._branch_reference(value, number)
            case PullRequestFieldShape.LABEL_NAMES:
                return [
                    label if isinstance(label, str) else str(label[RestJSONKey.NAME])
                    for label in value
                ]
            case _:
                return value

    def _branch_reference(self, value: Any, number: int | None) -> str:
        """:param value: The field's value, plain or nested.
        :param number: The pull request being read, named in any rejection.
        :return: The branch it names.
        :raises MissingPullRequestFieldError: If it names none."""
        if isinstance(value, str):
            return value
        if isinstance(value, Mapping) and value.get(PullRequestHeadKey.REFERENCE):
            return str(value[PullRequestHeadKey.REFERENCE])
        raise MissingPullRequestFieldError(self, number)


# %% the pull request's head


@dataclass(frozen=True)
class PullRequestHead:
    """
    The branch a pull request would merge, where it lives, and the commit it is at.
    """

    branch: str
    """
    The head branch's name.
    """

    repository: str | None
    """
    The ``owner/name`` of the repository the head branch lives in, ``None`` once that
    repository is deleted.
    """

    commit: str
    """
    The commit the head branch points at.
    """

    @classmethod
    def from_record(cls, record: PullRequestPayload, number: int) -> PullRequestHead:
        """
        :param record: The fetched pull request.
        :param number: The pull request being read, named in any rejection.
        :return: Its head.
        :raises MissingPullRequestFieldError: If the head does not say where it lives or
            which commit it is at.
        """
        head = record.get(PullRequestField.HEAD.key)
        if (
            not isinstance(head, Mapping)
            or PullRequestHeadKey.HEAD_REPOSITORY not in head
            or not head.get(RestJSONKey.SHA)
        ):
            raise MissingPullRequestFieldError(PullRequestField.HEAD, number)
        repository = head[PullRequestHeadKey.HEAD_REPOSITORY]
        return cls(
            branch=PullRequestField.HEAD.read(record, number),
            repository=(
                None
                if repository is None
                else str(repository[PullRequestHeadKey.FULL_NAME])
            ),
            commit=str(head[RestJSONKey.SHA]),
        )
