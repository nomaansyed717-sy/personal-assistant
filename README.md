# Aide: a chief of staff in your contacts list

A personal assistant you text on WhatsApp. It reads your email and calendar and tracks what you've promised and what you're owed. Every morning it texts you the 3 to 5 things that need you, each with a reply ready to send. You approve with a number. Nothing goes out without your yes unless you've explicitly delegated it.

This repo is **Phases 0–1** of the product spec: the working core you can put in front of design partners. Phases 2–3 (web errands, phone calls, phone and desktop control, our own model) have their interfaces in place, and their executors switch on later.

## What it does today

| Capability | How |
| --- | --- |
| Text it on WhatsApp | WhatsApp Business Platform (Cloud API) webhook, signed and verified |
| Onboarding in chat | Consent → one-tap Google connect → first scan of 90 days → "here's what looks open" |
| Open-loop tracking | Claude reads each email thread and records commitments both ways, closing them when a later email fulfils them |
| People graph | Who you write to, who writes to you, relationship ("investor", "distributor"), learned importance |
| Daily brief | Your local time, today's calendar plus the top open loops, each with a drafted reply, nudge or reminder |
| Drafts in your voice | Style profile learned from your sent mail, refreshed nightly |
| Numbered approvals | `1, 3`, `all`, `skip 2`, `edit 2: make it warmer`, `done 1`, `snooze 3` |
| Ask anything | "Did Ravi reply about the invoice?", "Find 30 minutes with Anika next week", via an agent with Gmail and Calendar tools |
| Scheduling | Finds free slots and creates events with invites, after your approval |
| Delegation | `always send follow-ups`: known contacts only, 60-second undo window, `STOP` holds them |
| Your data, your control | `what do you know about Ravi`, `forget Ravi`, `what did you do today`, `delete everything` |
| Global by default | Time zone guessed from the phone number, replies in your language, works in any country WhatsApp works |

## Safety model

| Tier | Examples | Behaviour |
| --- | --- | --- |
| 0 Read | Search mail, check calendar | Always allowed |
| 1 Private | Reminders, marking loops done | Acts, reports in the brief |
| 2 Known contacts | Email someone you've written to before; calendar invites | Asks; can be delegated |
| 3 New contacts / calls / errands | First email to anyone new | Shows the full text, asks every time, never delegable |
| 4 Money | Payments | Not supported; the user does it |

- **Prompt injection.** Email, calendar and search content reaches Claude only inside `<untrusted>` tags, with instructions to treat it as data. The agent has no tool that sends directly or changes autonomy. Delegation and deletion are parsed from the user's own words in `router.py`, never chosen by the model. Anything the model proposes to a new address is flagged tier 3.
- **Encryption.** Tokens and raw text are encrypted with a per-user key derived from `MASTER_KEY` (HKDF + Fernet).
- **Retention.** Raw email text is dropped after 90 days. Structured facts stay until the user deletes them.
- **Audit log.** Every proposal, approval and execution is logged, and the user can read the log in chat.

## Run it locally (10 minutes)

```bash
cp .env.example .env            # set MASTER_KEY and ANTHROPIC_API_KEY at minimum
docker compose up -d db
pip install -r requirements-dev.txt

# Try the brain with a sample mailbox, no WhatsApp or Google needed:
python scripts/chat.py --demo
```

You'll get the onboarding brief for a sample inbox. Then try `1`, `edit 2: shorter`, `what's open`, `find time with Anika tomorrow`, or `what did you do today`.

Full stack with web and worker: `docker compose up --build`. The simulator endpoint is `POST /dev/simulate {"phone": "+447911123456", "text": "hi"}` and only works while `WHATSAPP_TOKEN` is empty.

Tests (all external services are mocked):

```bash
TEST_DATABASE_URL=postgresql+psycopg://assistant:assistant@localhost:5432/assistant pytest -q
```

## Go live

### 1. Deploy (Render, one click)
New → Blueprint → select this repo. `render.yaml` creates the Postgres database, the web service and the worker. Fill in the secrets it asks for. `MASTER_KEY` is generated for you and `BASE_URL` is picked up from Render automatically. `GET /setup-status` lists any settings still missing. Railway, Fly.io or any Docker host work too: run the image twice, once with the worker command `python -m app.worker.run`.

### 2. WhatsApp (Meta)
1. On developers.facebook.com, create an app of type Business, then add **WhatsApp**.
2. Add a phone number. This is the assistant's number, the one users save.
3. Webhook: callback URL `${BASE_URL}/webhooks/whatsapp`, verify token `WHATSAPP_VERIFY_TOKEN`, then subscribe to **messages**.
4. Create a permanent token from a System User with `whatsapp_business_messaging` and set it as `WHATSAPP_TOKEN`. Set `WHATSAPP_PHONE_NUMBER_ID`, plus `WHATSAPP_APP_SECRET` from App settings → Basic.
5. **Submit one message template** (Utility category), named `assistant_update`:
   > Hi {{1}}, I have an update for you. Reply to see it.

   WhatsApp only allows free-form messages within 24 hours of the user's last message. Outside that window, the app sends this template and holds the brief until the user replies.
6. Complete business verification to raise messaging limits beyond test numbers.

### 3. Google
1. In console.cloud.google.com, create a project and enable the **Gmail API** and **Google Calendar API**.
2. OAuth consent screen: External. Add the scopes `gmail.readonly`, `gmail.send`, `calendar.events`, `openid` and `email`.
3. Credentials: OAuth client (Web). Redirect URI `${BASE_URL}/oauth/google/callback`.
4. While the app is in **Testing**, add up to 100 test users. That's enough for the design-partner pilot.
5. **Before a public launch:** `gmail.readonly` is a restricted scope. It needs Google's OAuth app verification plus an annual third-party security assessment. Start this early, because it takes weeks.

### 4. Before real users
- Have counsel review `/privacy` and the onboarding consent text for your launch countries: GDPR, CCPA/CPRA, India's DPDP Rules, and others.
- Back up `MASTER_KEY` in a secrets manager. If it's lost, stored tokens and raw text can't be decrypted.

## What users can text

| Say | Does |
| --- | --- |
| `1, 3` / `all` | Approve those items |
| `skip 2` / `edit 2: …` | Reject or rewrite a draft |
| `done 1` / `snooze 1 for 7 days` | Close or postpone a loop |
| `brief` / `what's open` | Brief now |
| `always send follow-ups` / `ask me first` | Delegate or revoke |
| `STOP` / `resume` | Hold pending sends, pause proactive messages, resume |
| `brief at 7` / `timezone Europe/London` | Settings |
| `what do you know [about X]` / `forget X` | See or delete what it knows |
| `what did you do today` | Audit log |
| `delete everything` → `DELETE` | Wipe the account and revoke Google access |
| Anything else | The agent: questions, drafting, scheduling, tracking new commitments |

## Code map

```
app/
  main.py               HTTP: WhatsApp webhook, Google OAuth, privacy page, dev simulator
  worker/run.py         Scheduler: sync every 15 min, briefs at local time, undo-window dispatcher, retention
  channels/             WhatsApp adapter (24h window, templates); console channel for dev. SMS/iMessage/Telegram plug in here
  integrations/         Google OAuth, Gmail, Calendar (plain REST); incremental sync
  context/              The context engine: commitment extraction, people graph, ranking, voice profile
  agent/
    router.py           Every inbound message: deterministic commands first, then the agent
    agent.py, tools.py  Claude tool loop; read tools + propose-only write tools
    actions.py          Permission tiers, approvals, delegation, undo window, execution
    drafts.py           Turn an open loop into a reply, nudge or reminder
    onboarding.py       Consent → connect → first insights
    account.py          Audit log, what-I-know, forget, delete everything, retention purge
  execution/            The execution ladder: api.py live; browser, voice, desktop, phone are Phase 2-3 interfaces
  brief.py              Daily brief
  crypto.py             Per-user encryption
tests/                  27 tests: full onboarding-to-sent-email flow, safety, injection, data controls
scripts/chat.py         Terminal chat, with a --demo mailbox
```

## Next (from the spec)
- **Phase 2:** the browser agent (`execution/browser.py`) and outbound AI calls (`execution/voice.py`). Approvals and tiers already route these action kinds. Outlook/Microsoft 365 integration. Voice-note input via transcription.
- **Phase 3:** Android phone agent, opt-in location and screen context, standing routines, and fine-tuned models trained on consented approve/edit/reject traces (every Action row is already a label).
- Database migrations: the schema is created on startup. Add Alembic before the first schema change after real users are on it.
