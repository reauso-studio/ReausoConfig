"""Interpolation expression parser using Lark.

This module provides parsing for interpolation expressions like:
- Config references: ${/model.lr}, ${./local}, ${model.lr}
- Environment variables: ${env:PATH}, ${env:HOME ?: "/default"}
- Expressions: ${/a * 2 + /b}, ${/list[0]}, ${/items | filter(x > 0)}

Thread-safe: The InterpolationParser singleton is protected by an internal lock.
"""

import re
import threading
from pathlib import Path
from typing import NamedTuple

from lark import Lark, Tree
from lark.exceptions import LarkError


class InterpolationMatch(NamedTuple):
    """A matched interpolation in a string.

    :param start: Start index of the ${...} in the original string.
    :param end: End index (exclusive) of the ${...}.
    :param expression: The expression inside ${...} (without the ${}).
    """

    start: int
    end: int
    expression: str


# Pattern to find ${...} in strings, handling nested braces
# Uses a simple approach: find ${ then match until } (no nested ${} support)
_INTERPOLATION_PATTERN = re.compile(r"\$\{([^}]+)\}")


class InterpolationParser:
    """Thread-safe parser for interpolation expressions using Lark grammar.

    This is a singleton-style class that lazily loads the grammar file
    and caches the Lark parser for reuse. Thread safety is ensured using
    double-checked locking pattern.

    Example::

        parser = InterpolationParser()
        tree = parser.parse("/model.lr * 2")
        # Returns a Lark parse tree
    """

    _instance: "InterpolationParser | None" = None
    _parser: Lark | None = None
    _lock = threading.Lock()

    def __new__(cls) -> "InterpolationParser":
        """Return the singleton instance (thread-safe)."""
        # Fast path: instance exists
        if cls._instance is not None:
            return cls._instance

        # Slow path: need lock
        with cls._lock:
            # Double-check after lock
            if cls._instance is None:
                cls._instance = super().__new__(cls)
        return cls._instance

    def _get_parser(self) -> Lark:
        """Get or create the Lark parser (thread-safe).

        :return: Configured Lark parser instance.
        """
        # Fast path: parser exists
        if self._parser is not None:
            return self._parser

        # Slow path: need lock
        with self._lock:
            # Double-check after lock
            if self._parser is None:
                grammar_path = Path(__file__).parent / "grammar.lark"
                InterpolationParser._parser = Lark(
                    grammar_path.read_text(),
                    parser="lalr",
                    maybe_placeholders=False,
                )
        return self._parser

    def parse(self, expression: str) -> Tree:
        """Parse an interpolation expression into an AST.

        :param expression: The expression to parse (without ${} wrapper).
        :return: Lark parse tree.
        :raises InterpolationSyntaxError: If the expression cannot be parsed.
        """
        from rconfig.errors import InterpolationSyntaxError

        try:
            return self._get_parser().parse(expression)
        except LarkError as e:
            raise InterpolationSyntaxError(expression, str(e)) from e


def find_interpolations(text: str) -> list[InterpolationMatch]:
    """Find all ${...} interpolation patterns in a string.

    :param text: The string to search for interpolations.
    :return: List of InterpolationMatch tuples with positions and expressions.

    Example::

        matches = find_interpolations("Hello ${env:USER}, your lr is ${/model.lr}")
        # Returns:
        # [
        #     InterpolationMatch(start=6, end=18, expression="env:USER"),
        #     InterpolationMatch(start=34, end=47, expression="/model.lr"),
        # ]
    """
    matches: list[InterpolationMatch] = []
    for match in _INTERPOLATION_PATTERN.finditer(text):
        matches.append(
            InterpolationMatch(
                start=match.start(),
                end=match.end(),
                expression=match.group(1),
            )
        )
    return matches


def has_interpolation(text: str) -> bool:
    """Check if a string contains any interpolation patterns.

    :param text: The string to check.
    :return: True if the string contains ${...} patterns.
    """
    return _INTERPOLATION_PATTERN.search(text) is not None


def is_standalone_interpolation(text: str) -> bool:
    """Check if a string is exactly one interpolation with no other content.

    Standalone interpolations preserve their resolved type (e.g., numbers
    stay as numbers). Embedded interpolations are always converted to strings.

    :param text: The string to check.
    :return: True if the string is exactly "${expression}" with no other text.

    Example::

        is_standalone_interpolation("${/model.lr}")  # True
        is_standalone_interpolation("lr: ${/model.lr}")  # False
        is_standalone_interpolation("${/a} and ${/b}")  # False
    """
    text = text.strip()
    if not text.startswith("${") or not text.endswith("}"):
        return False
    # Check there's exactly one interpolation
    matches = find_interpolations(text)
    return len(matches) == 1 and matches[0].start == 0 and matches[0].end == len(text)
