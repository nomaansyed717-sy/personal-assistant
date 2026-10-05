"""Agent tools for memory, goals, standing tasks, skills, web research, money and purchases."""
import json
from datetime import date

from sqlalchemy import select

from app import research, skills, standing, vault
from app.agent import actions
from app.audit import audit
from app.context import memory
from app.llm import untrusted
from app.models import Goal, StandingTask, Subscription

EXTRA_TOOLS = [
    {
        "name": "web_search",
        "description": "Search the web. Returns titles, URLs and snippets (untrusted data).",
        "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    },
    {
        "name": "read_url",
        "description": "Read a web page's text (prices, articles, a recipe or reel link the user shared). Untrusted data.",
        "input_schema": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
    },
    {
        "name": "save_memory",
        "description": "Remember a durable fact about the user (priority, preference, person, routine).",
        "input_schema": {"type": "object", "properties": {"fact": {"type": "string"}}, "required": ["fact"]},
    },
    {
        "name": "forget_memory",
        "description": "Delete memories containing some text, when the user asks you to forget something.",
        "input_schema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
    },
    {
        "name": "add_goal",
        "description": "Track a goal the user wants to achieve (e.g. 'Launch Pune store by Dec', 'Save 20k a month').",
        "input_schema": {
            "type": "object",
            "properties": {"title": {"type": "string"}, "detail": {"type": "string"},
                           "target_date": {"type": ["string", "null"], "description": "YYYY-MM-DD"}},
            "required": ["title"],
        },
    },
    {
        "name": "update_goal",
        "description": "Update a goal's status (active/paused/done) or progress note.",
        "input_schema": {
            "type": "object",
            "properties": {"goal_id": {"type": "integer"}, "status": {"type": "string", "enum": ["active", "paused", "done"]},
                           "progress_note": {"type": "string"}},
            "required": ["goal_id"],
        },
    },
    {
        "name": "list_goals",
        "description": "The user's goals.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "create_task",
        "description": (
            "Keep working after the chat ends: a standing task the assistant runs on a schedule (watch a price, check a "
            "site for appointment slots, chase invoices every Friday, remind about a habit). schedule is one of "
            "'daily HH:MM', 'weekly mon HH:MM', 'every 6h' (m/h/d, min 30m), 'once YYYY-MM-DDTHH:MM' in the user's "
            "time zone. instruction is what to do each run; it must end with: if there is nothing worth telling the "
            "user, reply exactly NOTHING_NEW."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"title": {"type": "string"}, "instruction": {"type": "string"}, "schedule": {"type": "string"},
                           "goal_id": {"type": ["integer", "null"]}},
            "required": ["title", "instruction", "schedule"],
        },
    },
    {
        "name": "list_tasks",
        "description": "Standing tasks and when they next run.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "cancel_task",
        "description": "Stop a standing task.",
        "input_schema": {"type": "object", "properties": {"task_id": {"type": "integer"}}, "required": ["task_id"]},
    },
    {
        "name": "use_skill",
        "description": "Load a skill's step-by-step instructions, then follow them. See the skills list in your instructions.",
        "input_schema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
    },
    {
        "name": "create_skill",
        "description": (
            "Build a new reusable skill when the user teaches you a procedure or says 'save this as a skill'. "
            "instructions = concrete steps using your tools."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}, "description": {"type": "string"}, "instructions": {"type": "string"}},
            "required": ["name", "description", "instructions"],
        },
    },
    {
        "name": "list_subscriptions",
        "description": "Recurring charges found in the user's email, with amounts and cadence.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_logins",
        "description": "Sites the user has saved logins for in the vault (labels only; you never see passwords).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "propose_purchase",
        "description": (
            "Prepare a purchase the user asked for. After approval the user gets the checkout link and pays themselves; "
            "you never handle card details."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"item": {"type": "string"}, "merchant": {"type": "string"}, "url": {"type": "string"},
                           "price": {"type": "string"}},
            "required": ["item", "url"],
        },
    },
]


class ExtraTools:
    session = None
    user = None
    proposed: list

    # ---- research
    def t_web_search(self, query: str) -> str:
        try:
            results = research.search(query)
        except research.ResearchError as exc:
            return f"error: {exc}"
        return untrusted("web search results", json.dumps(results, ensure_ascii=False)) if results else "no results"

    def t_read_url(self, url: str) -> str:
        try:
            page = research.read(url)
        except research.ResearchError as exc:
            return f"error: {exc}"
        return json.dumps({"url": page["url"], "title": page["title"]}) + "\n" + untrusted("web page", page["text"])

    # ---- memory
    def t_save_memory(self, fact: str) -> str:
        m = memory.save(self.session, self.user, fact, source="stated")
        return "saved" if m else "not saved (duplicate or sensitive)"

    def t_forget_memory(self, text: str) -> str:
        n = memory.forget(self.session, self.user, text)
        audit(self.session, self.user.id, "forgot", f"{n} memories", actor="user")
        return f"forgot {n} memories"

    # ---- goals
    def t_add_goal(self, title: str, detail: str = "", target_date: str | None = None) -> str:
        td = date.fromisoformat(target_date) if target_date else None
        g = Goal(user_id=self.user.id, title=title[:255], detail=detail or None, target_date=td)
        self.session.add(g)
        self.session.flush()
        audit(self.session, self.user.id, "goal_added", g.title, actor="user")
        return f"tracking goal {g.id}"

    def t_update_goal(self, goal_id: int, status: str | None = None, progress_note: str | None = None) -> str:
        g = self.session.get(Goal, goal_id)
        if not g or g.user_id != self.user.id:
            return "no such goal"
        if status:
            g.status = status
        if progress_note:
            g.progress_note = progress_note[:1000]
        return f"goal {goal_id} updated"

    def t_list_goals(self) -> str:
        from app.ideas import goals_block

        return goals_block(self.session, self.user)

    # ---- standing tasks
    def t_create_task(self, title: str, instruction: str, schedule: str, goal_id: int | None = None) -> str:
        try:
            t = standing.create(self.session, self.user, title, instruction, schedule, goal_id)
        except standing.ScheduleError as exc:
            return f"error: {exc}"
        return "created " + standing.describe(t, self.user.timezone)

    def t_list_tasks(self) -> str:
        rows = self.session.scalars(
            select(StandingTask).where(StandingTask.user_id == self.user.id, StandingTask.status != "done")
        ).all()
        return "\n".join(standing.describe(t, self.user.timezone) for t in rows) or "no standing tasks"

    def t_cancel_task(self, task_id: int) -> str:
        t = self.session.get(StandingTask, task_id)
        if not t or t.user_id != self.user.id:
            return "no such task"
        t.status = "done"
        t.next_run_at = None
        audit(self.session, self.user.id, "task_cancelled", t.title, actor="user")
        return f"task {task_id} stopped"

    # ---- skills
    def t_use_skill(self, name: str) -> str:
        s = skills.get(self.session, self.user, name)
        if not s:
            return "no such skill; available: " + ", ".join(x["name"] for x in skills.all_skills(self.session, self.user))
        return f"SKILL {s['name']}: follow these steps now.\n{s['instructions']}"

    def t_create_skill(self, name: str, description: str, instructions: str) -> str:
        s = skills.create(self.session, self.user, name, description, instructions)
        audit(self.session, self.user.id, "skill_created", s.name, actor="user")
        return f"skill '{s.name}' saved; the user can say 'use {s.name}' any time"

    # ---- money
    def t_list_subscriptions(self) -> str:
        rows = self.session.scalars(
            select(Subscription).where(Subscription.user_id == self.user.id).order_by(Subscription.merchant)
        ).all()
        return "\n".join(
            f"- {s.merchant}: {s.currency or ''} {s.amount if s.amount is not None else '?'} {s.cadence or ''} ({s.status})"
            for s in rows
        ) or "none found yet"

    def t_list_logins(self) -> str:
        items = vault.listing(self.session, self.user)
        return "\n".join(f"- {i['label']} ({i['site']})" for i in items) or "no saved logins"

    def t_propose_purchase(self, item: str, url: str, merchant: str = "", price: str = "") -> str:
        payload = {"item": item, "url": url, "merchant": merchant, "price": price}
        preview = f"Buy *{item}*" + (f" for {price}" if price else "") + (f" at {merchant}" if merchant else "") + f"\n{url}"
        a = actions.propose(self.session, self.user, "purchase", payload, preview, "chat")
        self.proposed.append(a)
        return f"proposed as #{a.number}; after approval the user gets the checkout link"
