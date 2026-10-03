"""Background worker: sync, extraction, daily briefs, the undo-window dispatcher, retention.

Run with:  python -m app.worker.run
"""
import logging
from datetime import timedelta

from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy import delete, select

from app import brief
from app.agent import actions
from app.agent.account import purge_raw
from app.config import get_settings
from app.context.extract import process_pending
from app.context.voice import build_voice_profile
from app.db import init_db, session_scope, utcnow
from app.integrations.sync import sync_user
from app.llm import get_llm
from app.messenger import send
from app.models import Connection, OAuthState, User

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("worker")


def _user_ids(states=("active",)) -> list[int]:
    with session_scope() as s:
        return list(s.scalars(select(User.id).where(User.onboarding_state.in_(states))).all())


def job_dispatch() -> None:
    with session_scope() as s:
        n = actions.run_due(s)
        if n:
            log.info("executed %d scheduled actions", n)


def job_sync() -> None:
    llm = get_llm()
    for uid in _user_ids():
        try:
            with session_scope() as s:
                user = s.get(User, uid)
                stats = sync_user(s, user)
                if "error" in stats:
                    conn = s.scalar(select(Connection).where(Connection.user_id == uid))
                    if conn and conn.status == "revoked":
                        send(s, user, "I've lost access to your Google account. Reply *connect* and I'll send a new link.")
                        user.onboarding_state = "awaiting_connect"
                    continue
                new = process_pending(s, user, llm)
                if new:
                    log.info("user %s: %d new commitments", uid, new)
        except Exception:  # noqa: BLE001 - one user's failure must not stop the others
            log.exception("sync failed for user %s", uid)


def job_briefs() -> None:
    llm = get_llm()
    for uid in _user_ids():
        try:
            with session_scope() as s:
                user = s.get(User, uid)
                if not brief.due_for_brief(user):
                    continue
                sync_user(s, user)
                process_pending(s, user, llm)
                send(s, user, brief.compose(s, user, llm))
                brief.mark_sent(user)
        except Exception:  # noqa: BLE001
            log.exception("brief failed for user %s", uid)


def job_daily() -> None:
    llm = get_llm()
    with session_scope() as s:
        purged = purge_raw(s, get_settings().raw_retention_days)
        s.execute(delete(OAuthState).where(OAuthState.created_at < utcnow() - timedelta(days=2)))
        log.info("purged raw text from %d events", purged)
    for uid in _user_ids():
        try:
            with session_scope() as s:
                build_voice_profile(s, s.get(User, uid), llm)
        except Exception:  # noqa: BLE001
            log.exception("voice refresh failed for user %s", uid)


def main() -> None:
    init_db()
    cfg = get_settings()
    sched = BlockingScheduler(timezone="UTC")
    sched.add_job(job_dispatch, "interval", seconds=20, max_instances=1, coalesce=True)
    sched.add_job(job_sync, "interval", minutes=cfg.sync_interval_minutes, max_instances=1, coalesce=True)
    sched.add_job(job_briefs, "cron", minute="*/5", max_instances=1, coalesce=True)
    sched.add_job(job_daily, "cron", hour=3, minute=17, max_instances=1, coalesce=True)
    log.info("worker started")
    sched.start()


if __name__ == "__main__":
    main()
