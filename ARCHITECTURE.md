# Agentic AI Recruitment Pipeline — Solution Architecture & Implementation Plan

**Status:** For review (no code written yet)
**Confirmed choices:** OpenAI (gpt-4o / gpt-5.4-mini) via the OpenAI API · Real Slack + Mocked Google Workspace (adapter pattern) · PostgreSQL · CSV/XLSX migration import

---

## 1. Executive Summary

Replace the Sheets + Slack manual workflow with an **event-driven, hybrid-orchestrated multi-agent system**: a central **Orchestrator** owns the pipeline state machine and human-in-the-loop gates, while five specialist agents communicate over **A2A-compatible, versioned JSON task envelopes**. All external side effects (email, Slack, calendar) flow through a single **transactional outbox**, which is what makes the entire pipeline idempotent and safe to retry.

I deliberately **diverged from a naive "one agent per business step" decomposition** in two ways:

1. **Notifications are extracted into their own agent.** Steps 2, 3, 4 and the cross-cutting "every status change → Slack + email" requirement all send messages. Centralizing this gives one place for dedupe, templating, channel routing, and rate-limit handling instead of four.
2. **Orchestration is hybrid, not pure peer-to-peer.** Pure A2A mesh makes the PM-approval gate, SLA timers, and failure recovery hard to reason about. A central state machine owns *when* things happen; agents own *how*. Agents still expose full A2A endpoints so they can be invoked directly (by humans via chat, or by other agents for sub-tasks) — satisfying the A2A compatibility requirement without sacrificing auditability.

---

## 2. Agent Decomposition (Recommended)

```
                        ┌────────────────────────────────────────────┐
                        │        ORCHESTRATOR AGENT (Conductor)      │
                        │  • Pipeline state machine per position     │
                        │  • HITL gates (PM approval)                │
                        │  • SLA timers / scheduled triggers         │
                        │  • System-level chat interface             │
                        └──────┬──────┬──────┬──────┬──────┬─────────┘
                               │ A2A  │ A2A  │ A2A  │ A2A  │ A2A
        ┌──────────────┐ ┌─────▼────┐ ┌─────▼─────┐ ┌──▼───────┐ ┌───▼──────┐
        │ EVALUATION   │ │SCHEDULING│ │ MONITORING│ │REPORTING │ │NOTIFIER  │
        │ AGENT        │ │AGENT     │ │ AGENT     │ │AGENT     │ │AGENT     │
        │ JD↔CV rank   │ │panel     │ │invite SLA │ │status    │ │outbox →  │
        │ + reasoning  │ │match +   │ │feedback   │ │reports   │ │Slack +   │
        │              │ │calendar  │ │transcript │ │          │ │email     │
        └──────┬───────┘ └────┬─────┘ └────┬──────┘ └────┬─────┘ └───┬──────┘
               │              │            │             │           │
        ┌──────▼──────────────▼────────────▼─────────────▼───────────▼──────┐
        │                    INTEGRATION LAYER (MCP-style tool servers)     │
        │   SlackAdapter(REAL)  CalendarAdapter(MOCK)  EmailAdapter(MOCK)   │
        │   MeetAdapter(MOCK)   TranscriptAdapter(MOCK)  FileStore          │
        └───────────────────────────────┬───────────────────────────────────┘
                                        │
                              ┌─────────▼─────────┐
                              │    PostgreSQL     │
                              │  (source of truth │
                              │  + outbox + audit)│
                              └───────────────────┘
```

### 2.1 Agent responsibilities & boundaries

| Agent | Owns | Does NOT do | Chat interface |
|---|---|---|---|
| **Orchestrator** | Position lifecycle state machine; dispatching A2A tasks; PM approval gate (routed to the **owning project's PM**); SLA timer scheduling; retry/compensation decisions; **role-aware query engine** backing the system chat | Any domain logic (ranking, matching, messaging) | Role-scoped conversational UI: "What's the status of SR-042?", "How many open positions for Tech Lead?", "Fulfillment status for Project Phoenix", "Approve the shortlist for SR-042" — answers filtered to the caller's scope |
| **Evaluation Agent** | Parse JD + CVs (PDF/DOCX/text); score & rank candidates vs JD with per-candidate reasoning; emit both human-readable report and machine-readable `RankedCandidateList v1` artifact | Scheduling, notifying | "Why was candidate X ranked #2?", "Re-evaluate with more weight on Kubernetes" |
| **Scheduling Agent** | Interviewer↔candidate matching (skills, role level, availability, load balancing); create calendar event + Meet link + transcription flag (via adapter); attach feedback form link; write `interviews` records | Sending notifications directly (delegates to Notifier); SLA tracking | "Who is free to interview a senior Java candidate this week?", "Reschedule interview INT-17" |
| **Monitoring Agent** | Watch invite acceptance vs SLA (default 1h); watch feedback submission; on feedback: fetch transcript, generate LLM summary, assemble combined packet; update position status | Sending the reminder itself (emits `SLA_BREACHED` event → Notifier) | "Which interviews are pending feedback?", "Show me the transcript summary for INT-17" |
| **Reporting Agent** | Periodic + on-status-change fulfillment reports; **scope-aware distribution**: each PM gets their project(s) only, DM/Staffing/Tech Architect get account-wide rollups; per-role formatting | Raw data mutation | "Give me this week's fulfillment summary for Project Phoenix" (scoped to caller's role) |
| **Notification Agent** | Single egress point for ALL Slack + email; consumes the transactional outbox; templating; channel routing rules; dedupe by idempotency key; rate-limit/backoff handling | Deciding *when* to notify (that's event-driven) | "Resend the invite email for INT-17", "What notifications went out today for SR-042?" |

### 2.2 Why not other decompositions

- **One mega-agent:** un-testable, no least-privilege boundaries, single blast radius.
- **Pure P2P A2A mesh (agents calling each other freely):** approval gates and SLA timers end up duplicated inside multiple agents; failure recovery requires distributed tracing across the mesh. The hybrid keeps a single audit spine.
- **Separate "Transcript/Summary agent":** too thin — it's one LLM call inside Monitoring's feedback flow. Split later only if transcript volume/latency demands it.

---

## 3. Orchestration & Communication Pattern

### 3.1 Hybrid: central state machine + A2A task protocol

**Position lifecycle state machine (owned by Orchestrator, persisted in Postgres):**

```
OPEN → EVALUATING → SHORTLIST_READY → PENDING_PM_APPROVAL
     → APPROVED → SCHEDULING → INTERVIEW_INVITE_SENT
     → INTERVIEW_ACCEPTED | SLA_BREACHED(→reminder→loop)
     → INTERVIEW_DONE → FEEDBACK_PENDING → FEEDBACK_RECEIVED
     → PASSED | FAILED (per candidate) → FILLED | REOPENED → CLOSED
```

Every transition is an **event row** (append-only `events` table). Transitions trigger:
1. Outbox entries (Slack + email per the cross-cutting rule) — same DB transaction.
2. Next A2A task dispatch, if any.

### 3.2 A2A message schema (versioned, machine-readable)

Aligned with the A2A protocol model (AgentCard + task lifecycle). Each agent serves:

- `GET /api/agents/{agent}/card` → AgentCard: name, version, skills, input/output schemas.
- `POST /api/agents/{agent}/tasks` → create task; `GET .../tasks/{id}` → poll status/artifacts.
- `POST /api/agents/{agent}/chat` → human chat interface (same skills, conversational wrapper).

**Task envelope:**
```json
{
  "schema": "a2a.task.v1",
  "task_id": "uuid",
  "idempotency_key": "eval:SR-042:jd-sha256:cvset-sha256",
  "skill": "evaluate_candidates",
  "issued_by": "orchestrator",
  "correlation": {"position_id": "SR-042", "pipeline_run_id": "uuid"},
  "input": { "...skill-specific, versioned schema..." },
  "status": "submitted|working|input_required|completed|failed",
  "artifacts": [{"type": "RankedCandidateList", "schema_version": "v1", "data": {}}]
}
```

Key artifact schemas (all versioned): `RankedCandidateList.v1`, `InterviewAssignment.v1`, `FeedbackPacket.v1`, `FulfillmentReport.v1`.

### 3.3 Role-aware chat & query scoping

The account spans **multiple projects**: each project has its own PM; one Delivery Manager and the Staffing team are accountable across all projects. This is enforced in one place — a **scoped query layer** inside the Orchestrator that every chat interface (orchestrator chat, agent chats, Reporting) passes through:

- Every user has a role (`pm | dm | staffing | tech_architect | admin`) and, for PMs, explicit project assignments.
- Chat requests are LLM-parsed into structured queries (intent + filters), then executed **with a scope filter injected server-side** (`project_id IN caller_scope`) — the LLM never decides access; the database layer does.
- Examples: a PM asking "how many open positions for Tech Lead?" gets counts for *their* project(s); the DM asking the same gets the account-wide count with a per-project breakdown; a PM asking about another project's ticket gets a polite scope-denied answer.
- The same scope filter applies to dashboards, reports, and approval queues.

### 3.4 Human-in-the-loop checkpoints

| Gate | Mechanism |
|---|---|
| **PM approves shortlist** (mandatory) | Orchestrator halts at `PENDING_PM_APPROVAL` and routes the gate to the **PM(s) assigned to the position's project**; Notifier sends Slack message + email with approve/reject link; PM approves via dashboard button or orchestrator chat ("approve SR-042"). Approval recorded in `approvals` table with actor + timestamp. Supports partial approval (approve subset / reorder). DM/admin can approve as escalation fallback (logged as override). |
| Reschedule / override interviewer | Via Scheduling agent chat or dashboard; produces a new event, old invite cancelled through outbox. |
| Manual status override | Orchestrator chat, guarded by role; always logged as an event with `actor_type=human`. |

---

## 4. Data Model (PostgreSQL)

**Why PostgreSQL fits here:** the pipeline is a transactional state machine — approvals, outbox, SLA timers, and status transitions need ACID guarantees and `SELECT ... FOR UPDATE SKIP LOCKED` (perfect for outbox/worker polling). JSONB columns handle the semi-structured parts (CV parse results, LLM reasoning, A2A payloads), so we lose nothing vs a document DB.

### Core tables (outline)

```sql
projects(id, name, client, description, active, created_at)

user_project_assignments(user_id FK, project_id FK, role_in_project,
                         PRIMARY KEY(user_id, project_id))
  -- PMs get explicit rows; DM/Staffing/Tech Architect have account-wide
  -- scope by role (no rows needed)

positions(id, project_id FK, ticket_number UNIQUE, title, jd_file_ref,
          jd_text, status, priority, opened_at, filled_at, metadata JSONB)

candidates(id, position_id FK, name, email, cv_file_ref, cv_text,
           parsed_profile JSONB, source, created_at)

evaluations(id, position_id FK, pipeline_run_id, model, prompt_version,
            ranked_list JSONB,          -- RankedCandidateList.v1 artifact
            human_report TEXT, input_hash UNIQUE, created_at)

interviewers(id, name, email, slack_user_id, role, skills JSONB,
             seniority, availability JSONB, max_weekly_interviews, active)

interviews(id, position_id FK, candidate_id FK, interviewer_id FK,
           scheduled_at, meet_link, calendar_event_id, feedback_form_ref,
           invite_status,               -- pending|accepted|declined|expired
           invite_sla_deadline, result, -- pass|fail|null
           transcript_ref, transcript_summary TEXT,
           idempotency_key UNIQUE)

feedback(id, interview_id FK UNIQUE, result, comments, submitted_by,
         submitted_at, raw JSONB)

approvals(id, position_id FK, evaluation_id FK, gate_type, status,
          approved_candidate_ids JSONB, actor, decided_at, comment)

events(id, position_id, entity_type, entity_id, event_type,
       actor_type,                     -- agent|human|system
       actor_id, payload JSONB, created_at)        -- append-only audit spine

outbox(id, idempotency_key UNIQUE, channel,        -- slack|email|calendar
       recipient, template, payload JSONB,
       status,                          -- pending|sent|failed|dead
       attempts, next_retry_at, sent_at, external_ref)

a2a_tasks(id, agent, skill, idempotency_key UNIQUE, status,
          input JSONB, artifacts JSONB, error, correlation JSONB,
          created_at, updated_at)

agent_chat_sessions(id, agent, user_id, messages JSONB, created_at)

import_jobs(id, source_type,            -- positions_csv|interviewers_csv|cvs_zip
            file_ref, status, row_counts JSONB, validation_report JSONB,
            created_at)

users(id, email, name, role,            -- pm|dm|tech_architect|staffing|admin
      slack_user_id, notification_prefs JSONB)
  -- scope resolution: role in (dm, staffing, tech_architect, admin) → all
  -- projects; role = pm → projects from user_project_assignments
```

**Note on the deployment environment:** the default managed database is MongoDB. Two options when we build: (a) run Postgres in-container for the MVP and move to a hosted Postgres (Neon/Supabase — you'd provide a connection string) for deployment, or (b) keep the identical schema shape on MongoDB. I recommend (a) with a hosted Postgres URL at deploy time; flagging it now so it's not a surprise. **[Decision needed at build time — resolved: the app was ultimately built and deployed on MongoDB, option (b).]**

---

## 5. Technology Stack

| Layer | Choice | Rationale |
|---|---|---|
| Agent runtime & API | **FastAPI (Python)** — one service, agents as modules each mounting `/api/agents/{name}/…` | A2A endpoints + chat + dashboard API in one deployable; agents split into services later without changing contracts |
| LLM | **OpenAI gpt-4o (evaluation, summaries) + gpt-5.4-mini (chat, light tasks)** via the **OpenAI SDK directly** | Your confirmed choice; standard OpenAI API key |
| Orchestration | Custom **Postgres-backed state machine + outbox worker** (APScheduler/async loop for SLA timers) | Durable, inspectable, exactly-once side effects; avoids heavyweight infra (Temporal/Kafka) at this scale — revisit if volume grows |
| Messaging (real) | **Slack Bolt SDK** — bot token, channel + DM notifications, interactive approve buttons (Phase 2+) | Confirmed real |
| Google Workspace | **Adapter interfaces** (`CalendarPort`, `EmailPort`, `MeetPort`, `TranscriptPort`) with **mock implementations**: in-app calendar view, in-app inbox, fake Meet links, uploadable/sample transcripts | Confirmed mocked; real Google API adapters drop in behind the same ports in Phase 3 with zero agent-code changes |
| CV/JD parsing | PyMuPDF + python-docx → text → LLM structured extraction | Robust across formats |
| Frontend | **React dashboard**: pipeline kanban per position, approval queue, per-agent chat panels, orchestrator chat, notification log, import wizard, mock inbox/calendar viewers | |
| Files | Local/object storage via FileStore abstraction (CVs, JDs, transcripts) | Object storage integration at deploy |

---

## 6. Security & Access Model (Per-Agent Least Privilege)

Even in a single deployable, each agent gets its **own credential set and scope envelope**, enforced by the integration layer (adapters check the calling agent's identity token before executing).

| Agent | Slack scopes | Google scopes (when real, Phase 3) | DB access (via role/RLS) |
|---|---|---|---|
| Orchestrator | none (delegates) | none | read all; write `positions.status`, `a2a_tasks`, `events`, `approvals` |
| Evaluation | none | `drive.readonly` (JD/CV fetch) | read `positions`,`candidates`; write `evaluations` |
| Scheduling | none | `calendar.events` (own calendar only) | read `interviewers`,`candidates`; write `interviews` |
| Monitoring | none | `calendar.events.readonly`, Meet transcript read (Drive scoped folder) | read `interviews`; write `feedback`, `interviews.status` |
| Notifier | `chat:write`, `users:read.email` | `gmail.send` (dedicated sender SA) | read/write `outbox` only |
| Reporting | none | none | read-only all domain tables |

- **Secrets:** all in backend `.env` (never in code/repo); one env var per agent credential (`SLACK_BOT_TOKEN`, later `GOOGLE_SA_SCHEDULING_JSON`, …). Per-agent Google **service accounts with domain-wide delegation limited to exact scopes** — no shared credentials.
- **Internal A2A auth:** each agent signs task requests with a per-agent secret (HMAC); tasks record `issued_by`, verified on receipt.
- **Humans:** role-based (PM/DM/Architect/Staffing/Admin); only PM+Admin can act on approval gates. (Auth method for the app itself — JWT vs Google SSO — to be chosen at build time.)
- **Audit:** every side effect and transition lands in `events` with actor identity.

---

## 7. Idempotency & Failure Recovery

### 7.1 Idempotency — three layers

1. **Task level:** every A2A task carries a deterministic `idempotency_key` (e.g., `eval:{position}:{sha256(jd)}:{sha256(cv_set)}`). Unique constraint on `a2a_tasks.idempotency_key` → a retried dispatch returns the existing task instead of re-running. Evaluation reuse is content-hash based: same JD+CVs ⇒ same evaluation, no duplicate LLM spend.
2. **Side-effect level (the critical one):** **transactional outbox.** Agents never call Slack/email/calendar directly. The state transition and its outbox rows commit in **one DB transaction**; a separate worker drains the outbox with `FOR UPDATE SKIP LOCKED`, marks `sent` with the provider's message ID. Unique `outbox.idempotency_key` (e.g., `slack:SR-042:INTERVIEW_INVITE_SENT:INT-17`) makes duplicate sends structurally impossible — retrying any workflow re-derives the same keys and hits the constraint.
3. **Entity level:** unique constraints on natural keys (`positions.ticket_number`, `interviews.idempotency_key = sched:{position}:{candidate}:{round}`) so re-imports and re-schedules upsert instead of duplicate.

### 7.2 Failure recovery

| Failure | Recovery |
|---|---|
| LLM call fails / times out | Task → `failed` with error; exponential backoff retry (3×); then position flagged `NEEDS_ATTENTION` + Slack alert to admin |
| Slack/email provider error | Outbox row retried with backoff (`next_retry_at`); after N attempts → `dead` + surfaced in dashboard dead-letter view for manual resend |
| Worker/process crash mid-task | State machine + outbox are durable in Postgres; on restart, orchestrator sweeps `working` tasks past a heartbeat timeout and re-dispatches (idempotency keys make this safe) |
| Interviewer never accepts (SLA) | Monitoring emits `SLA_BREACHED` → reminder via Slack; after 2nd breach → orchestrator proposes reassignment to PM |
| Partial pipeline (e.g., invite sent, tracker update failed) | Impossible by construction: tracker update and outbox entry are one transaction; the send itself is retried until acknowledged |
| Bad approval / wrong shortlist approved | Compensating action: PM "revoke approval" → cancellation events → outbox cancel-invite messages; nothing is hard-deleted (event-sourced audit) |

---

## 8. Google Sheets Migration Plan (CSV/XLSX upload)

**Principle: dual-run, staged, non-destructive — recruitment never stops.**

1. **Templates & mapping:** Import wizard accepts your exported CSV/XLSX for (a) Open Positions tracker, (b) Interviewer panel roster, (c) Candidate lists + CV files (zip upload). Column-mapping UI with saved mapping presets.
2. **Stage → validate → commit:** rows land in a staging area; validation report shows per-row errors (missing emails, unknown statuses, duplicate ticket numbers). Nothing touches live tables until you click **Commit** (dry-run diff shown first).
3. **Idempotent re-import:** upserts keyed on `ticket_number` / interviewer email — re-uploading a newer export updates rather than duplicates, so you can keep working in Sheets during the transition and re-sync daily.
4. **Cutover:** run both for 1–2 weeks (DB is system of record for new positions; Sheets frozen read-only after final sync). Reporting agent can export a Sheets-compatible CSV during transition so downstream consumers aren't broken.
5. **In-flight positions:** imported with their current status; state machine picks them up mid-lifecycle (e.g., a position already at "Interview Invite Sent" resumes at monitoring, not evaluation).

---

## 9. Phased Implementation Plan

### Phase 1 — MVP (first build)
- Postgres schema (incl. projects + role/scope model) + event/outbox spine + FileStore
- **Evaluation Agent** (JD/CV upload → ranked list + reasoning, human + machine formats)
- **Orchestrator** with state machine + **PM approval gate (project-routed)** + **role-aware scoped chat** (ticket status, open-position counts by role/project, account rollups)
- **Scheduling Agent** with mock Calendar/Meet/Email adapters (in-app calendar + inbox viewers so the flow is fully demonstrable)
- **Notification Agent** with **real Slack** (status-change notifications) + mock email
- Import wizard (CSV/XLSX for positions + interviewers, CV zip; positions mapped to projects during import)
- Seeded role-based demo users (1 DM, 2 PMs on different projects, 1 Staffing) to demonstrate scoping
- Dashboard: pipeline board, approval queue, per-agent chat, notification log
- *You provide:* Slack bot token + target channel(s) *(I'll give exact scopes needed: `chat:write`, `channels:read`, `users:read.email`)*

### Phase 2 — Monitoring, Feedback & Reporting
- Monitoring Agent: invite-acceptance SLA (mock calendar responses simulated / manually togglable), Slack reminders, feedback form capture (in-app form), transcript upload/mock → LLM summary → combined packet distribution
- Reporting Agent: on-change + scheduled stakeholder reports (role-tailored), Slack + mock email delivery
- Slack interactive approvals (approve shortlist from Slack)

### Phase 3 — Real Google Workspace
- Swap mock adapters for real Calendar/Meet/Gmail/Drive behind the same ports; per-agent service accounts with domain-wide delegation
- Real Meet transcription retrieval (Drive artifacts)
- **Key risks here:** Workspace admin consent for domain-wide delegation; Meet transcription requires eligible Workspace editions and transcript files land with delay (poll Drive); Gmail/Calendar API quotas → outbox pacing already absorbs this

### Phase 4 — Hardening & Scale
- Split agents into separate services if load requires (contracts already A2A); SSO; RLS enforcement; analytics (time-to-fill, funnel conversion); optional Temporal migration if workflow volume demands

### Key risks & dependencies (summary)
| Risk | Mitigation |
|---|---|
| Google Workspace admin permissions / delegation approval lead time | Mock-first design decouples build from org approvals (already chosen) |
| Meet transcript access (edition/permission-gated, delayed availability) | TranscriptPort polls with backoff; manual transcript upload always available as fallback |
| Slack rate limits (1 msg/sec/channel) | Outbox worker paces sends; batching digest option |
| LLM ranking quality/bias | Reasoning shown per candidate; PM gate is mandatory; prompt versioning in `evaluations` for auditability |
| Hosted Postgres needed for deployment | Provide Neon/Supabase URL at deploy, or fall back to MongoDB with same model shape |

---

## 10. What I Need From You to Start Phase 1

1. ✅ Approval of this architecture (or requested changes)
2. Slack: bot token for your workspace + channel name(s) for notifications (I'll send precise setup steps)
3. Sample data if available: 1 JD file, 2–3 CVs, a small export of your Open Positions sheet and interviewer roster (any format — used to shape parsers and import mappings)
vailable: 1 JD file, 2–3 CVs, a small export of your Open Positions sheet and interviewer roster (any format — used to shape parsers and import mappings)
