"""Lazy, import-free access to pandas (§14).

``import better_calendar`` must not import pandas. Two distinct needs follow:

* **Detection.** Deciding whether an object is a ``pd.Timestamp`` must never import
  pandas — and it never has to: if pandas has not been imported by *anyone*, no live
  object can be an instance of one of its classes. :func:`loaded_pandas` therefore
  reads ``sys.modules`` and nothing else.
* **Construction.** Returning a ``DatetimeIndex`` genuinely requires the package.
  :func:`require_pandas` imports on demand and raises an actionable
  :class:`~better_calendar.core.errors.ProviderError` if it is absent, while
  :func:`optional_pandas` returns ``None`` so callers can degrade to numpy (I6).
"""

from __future__ import annotations

import sys
from types import ModuleType
from typing import Any

from better_calendar.core.errors import ProviderError

__all__ = ["is_pandas_object", "loaded_pandas", "optional_pandas", "require_pandas"]

_MISSING: object = object()
_optional: Any = _MISSING


def loaded_pandas() -> ModuleType | None:
    """Return pandas if it is *already* imported, else ``None``. Never imports.

    Examples:
        >>> loaded_pandas() is None or loaded_pandas().__name__ == "pandas"
        True
    """
    return sys.modules.get("pandas")


def optional_pandas() -> ModuleType | None:
    """Import pandas on demand, returning ``None`` if it is not installed.

    The result is memoised, so a missing pandas costs one failed import per process.

    Examples:
        >>> optional_pandas() is None or optional_pandas().__name__ == "pandas"
        True
    """
    global _optional
    if _optional is _MISSING:
        try:
            import pandas
        except ImportError:  # pragma: no cover - depends on the environment
            _optional = None
        else:
            _optional = pandas
    return _optional  # type: ignore[no-any-return]  # narrowed to ModuleType | None


def require_pandas(feature: str) -> ModuleType:
    """Import pandas or raise a :class:`ProviderError` naming ``feature``.

    Args:
        feature: What the caller was trying to do, used in the error message.

    Returns:
        The pandas module.

    Raises:
        ProviderError: If pandas is not installed.

    Examples:
        >>> require_pandas("Timestamp output").__name__
        'pandas'
    """
    module = optional_pandas()
    if module is None:  # pragma: no cover - depends on the environment
        raise ProviderError.missing_dependency("pandas", "pandas", feature)
    return module


def is_pandas_object(value: object, *names: str) -> bool:
    """Return whether ``value`` is an instance of one of the named pandas classes.

    Returns ``False`` without importing anything when pandas is not already loaded.

    Args:
        value: The object to test.
        *names: Attribute names on the pandas namespace, e.g. ``"Timestamp"``.

    Returns:
        ``True`` if pandas is loaded and ``value`` is an instance of one of them.

    Examples:
        >>> is_pandas_object(42, "Timestamp")
        False
    """
    pandas = loaded_pandas()
    if pandas is None:
        return False
    classes = tuple(getattr(pandas, name) for name in names)
    return isinstance(value, classes)
