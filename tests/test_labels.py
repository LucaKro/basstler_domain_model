"""
Tests for :class:`basstler_domain_model.github.labels.GitHubLabel`: a caller's own set
of labels extends it.
"""

from __future__ import annotations

from enum import ReprEnum

from basstler_domain_model.github.labels import GitHubLabel

# %% an enumeration of labels


class EnumeratedLabel(GitHubLabel, ReprEnum):
    """
    A caller's labels, enumerated, each its own name and carrying its description.
    """

    def __new__(cls, label: str, description: str) -> EnumeratedLabel:
        """
        :param label: The label's name.
        :param description: What it means.
        :return: The member.
        """
        member = str.__new__(cls, label)
        member._value_ = label
        member.description = description
        return member

    READY = ("ready", "Ready for review")
    """
    A label the tests create.
    """


def test_an_enumerated_label_is_its_own_name():
    assert EnumeratedLabel.READY == EnumeratedLabel.READY.value


def test_an_enumerated_label_is_a_label():
    assert isinstance(EnumeratedLabel.READY, GitHubLabel)
