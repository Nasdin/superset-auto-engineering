"""Short durable lease serializing Knowledge reconciliation with operator edits."""

import time
import uuid
from contextlib import contextmanager

from .providers import ProviderError


@contextmanager
def learning_lease(store):
    owner = str(uuid.uuid4())
    with store.connect() as c:
        c.lock()
        changed = c.execute(
            "INSERT INTO learning_guard(id,owner,expires) VALUES('knowledge',:owner,:expires) "
            "ON CONFLICT(id) DO UPDATE SET owner=:owner,expires=:expires WHERE learning_guard.expires<:now",
            {"owner": owner, "expires": time.time() + 120, "now": time.time()},
        ).rowcount
        if not changed:
            raise ProviderError("Knowledge reconciliation is busy", category="knowledge")

    def renew():
        with store.connect() as c:
            changed = c.execute(
                "UPDATE learning_guard SET expires=:expires WHERE id='knowledge' AND owner=:owner AND expires>:now",
                {"owner": owner, "expires": time.time() + 120, "now": time.time()},
            ).rowcount
            if not changed:
                raise ProviderError("Knowledge reconciliation lease expired", category="knowledge")

    try:
        yield renew
    finally:
        with store.connect() as c:
            c.execute(
                "DELETE FROM learning_guard WHERE id='knowledge' AND owner=:owner", {"owner": owner}
            )
