from sqlalchemy.orm import Session

from app.models import AuditLog


def audit(session: Session, user_id: int, action: str, detail: str = "", actor: str = "assistant") -> None:
    session.add(AuditLog(user_id=user_id, actor=actor, action=action, detail=detail[:2000]))
