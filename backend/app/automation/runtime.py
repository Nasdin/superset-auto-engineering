"""Composition root shared by the API and single worker process."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager

from .config import Settings
from .engine import Engine
from .providers import Providers
from .store import Store


@contextmanager
def create_runtime(
    settings: Settings,
    *,
    provider_factory: Callable[[Settings], Providers] = Providers,
) -> Iterator[Engine]:
    """Own one connection pool; close it even if startup or execution fails."""
    providers = provider_factory(settings)
    try:
        yield Engine(settings, Store(settings.database), providers)
    finally:
        providers.close()
