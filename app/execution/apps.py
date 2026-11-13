"""Connected apps (MCP servers): run an approved tool call."""
from sqlalchemy.orm import Session

from app import connectors
from app.execution import ExecutionError, register
from app.models import Action, Connector, User


@register("app_action")
def app_action(session: Session, user: User, action: Action) -> str:
    p = action.payload
    c = session.get(Connector, p.get("connector_id"))
    if c is None or c.user_id != user.id:
        raise ExecutionError("that app is no longer connected")
    try:
        out = connectors.call(session, c, p["tool"], p.get("arguments") or {})
    except connectors.ConnectorError as exc:
        raise ExecutionError(str(exc)) from exc
    first = out.strip().splitlines()[0][:200] if out.strip() else "done"
    return f"Done in {c.name}: {first}"
