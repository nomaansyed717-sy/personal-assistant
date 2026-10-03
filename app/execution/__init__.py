"""The execution ladder: how an approved action actually happens.

1. Official APIs (Gmail, Google Calendar)        -> app/execution/api.py      (live)
2. Browser agent on the user's signed-in sites   -> app/execution/browser.py  (Phase 2 interface)
3. Desktop agent                                 -> app/execution/desktop.py  (Phase 2-3 interface)
4. Phone agent (Android)                         -> app/execution/phone.py    (Phase 3 interface)
   Voice calls                                   -> app/execution/voice.py    (Phase 2 interface)

Every executor takes (session, user, action) and returns a short human-readable result,
or raises ExecutionError. Executors never decide permissions; app/agent/actions.py does.
"""
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.models import Action, User


class ExecutionError(Exception):
    pass


class NotAvailable(ExecutionError):
    """The capability exists in the design but isn't switched on for this deployment yet."""


Executor = Callable[[Session, User, Action], str]
_registry: dict[str, Executor] = {}


def register(kind: str):
    def deco(fn: Executor) -> Executor:
        _registry[kind] = fn
        return fn

    return deco


def get_executor(kind: str) -> Executor:
    # Import modules so their @register decorators run.
    from app.execution import api, browser, desktop, phone, voice  # noqa: F401

    if kind not in _registry:
        raise NotAvailable(f"no executor for {kind}")
    return _registry[kind]
