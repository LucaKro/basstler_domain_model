"""
What a label is, and the complete label set a pull request has to be written back with.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from basstler_domain_model.github.exceptions import ContradictoryLabelWriteError

# %% labels


class GitHubLabel(str):
    """
    A label as GitHub stores it: the label is its own name, and carries what it means.

    The base a caller's own set of labels extends, an enumeration of them included.
    """

    description: str
    """
    What the label means, which it is created with.
    """


# %% label writes


@dataclass(frozen=True)
class LabelWrite:
    """
    The complete label set a pull request has to be written back with.

    GitHub's label write replaces the whole set rather than adding to it, so the labels
    a change leaves untouched still have to be sent. Computing them from the intended
    change alone is what silently strips the rest.
    """

    labels: tuple[str, ...]
    """
    Every label the pull request will carry once written, in the order it will carry
    them.
    """

    @classmethod
    def replacing(
        cls,
        current: Iterable[str],
        added: Iterable[str] = (),
        removed: Iterable[str] = (),
    ) -> LabelWrite:
        """
        Work out the full set that adding and removing labels leaves behind.

        :param current: The labels the pull request carries now.
        :param added: Labels it must carry afterwards.
        :param removed: Labels it must not carry afterwards.
        :return: The complete set to write.
        :raises ContradictoryLabelWriteError: If a label is both added and removed.
        """
        added, removed = tuple(added), tuple(removed)
        contradictory = tuple(label for label in added if label in removed)
        if contradictory:
            raise ContradictoryLabelWriteError(contradictory)
        kept = [label for label in current if label not in removed]
        return cls(tuple(kept + [label for label in added if label not in kept]))
