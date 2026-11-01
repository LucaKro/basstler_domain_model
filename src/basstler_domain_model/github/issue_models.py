"""
Issues as the REST API lists them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from basstler_domain_model.github.vocabulary import IssueState, JSONModel, RestJSONKey

# %% one issue


@dataclass(frozen=True)
class Issue(JSONModel):
    """
    One issue: its number, title, labels and whether it is open.
    """

    number: int
    """
    The issue's number.
    """

    title: str
    """
    Its title.
    """

    labels: tuple[str, ...]
    """
    The names of the labels it carries.
    """

    state: IssueState
    """
    Whether it is open.
    """

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Issue:
        return cls(
            data[RestJSONKey.NUMBER],
            data[RestJSONKey.TITLE],
            tuple(label[RestJSONKey.NAME] for label in data[RestJSONKey.LABELS]),
            IssueState(data[RestJSONKey.STATE]),
        )

    @staticmethod
    def is_pull_request(data: dict[str, Any]) -> bool:
        """
        :param data: One entry of an issue listing.
        :return: Whether it is a pull request, which the issues API lists among the
            issues.
        """
        return RestJSONKey.PULL_REQUEST in data
