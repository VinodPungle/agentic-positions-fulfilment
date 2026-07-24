# PRD — Agentic AI Recruitment Pipeline (Open Position Fulfillment)

## Original Problem Statement
Replace manual Google Sheets + Slack recruitment workflow with a multi-agent, A2A-compatible AI system automating: (1) candidate evaluation (JD vs CVs, ranked with reasoning), (2) interview allocation & scheduling (panel matching, calendar/Meet invites, feedback form), (3) interview monitoring & feedback collection (invite SLA, transcript summary), (4) stakeholder reporting. Multi-project account: per-project PMs, one DM + Staffing account-wide; role-aware scoped chat required. Cross-cutting: Slack+email on every status change, mandatory PM shortlist approval (HITL), DB replaces Sheets with CSV import migration, per-agent least-privilege credentials, full idempotency, per-agent chat + orchestrator chat, A2A versioned schemas.

## User Choices (confirmed)
- LLM: OpenAI (gpt-4o / gpt-5.4-mini) via Emergent Universal Key
- Integrations: REAL Slack, MOCKED Google Workspace (adapter/port pattern for later swap)
- Database: PostgreSQL (note: Emergent env default is MongoDB — hosted Postgres URL needed at deploy, or fall back to Mongo with same model)
- Migration: CSV/XLSX upload (no Google OAuth)
- First deliverable: architecture document only, build after review

## User Personas
- Project Manager (per-project scope; approves shortlists)
- Delivery Manager (account-wide)
- Staffing team (account-wide)
- Tech Architect (account-wide, report recipient)
- Admin

## Architecture (approved-pending-review)
Full document: /app/ARCHITECTURE.md
- 6 agents: Orchestrator (state machine + HITL + role-scoped chat), Evaluation, Scheduling, Monitoring, Reporting, Notifier (single egress, transactional outbox)
- Hybrid orchestration: central Postgres-backed state machine + A2A task protocol (AgentCard, a2a.task.v1 envelopes, versioned artifacts)
- Idempotency: task-level keys, transactional outbox, natural-key upserts
- Security: per-agent credentials/scopes, HMAC-signed A2A, server-side project scoping
- Migration: staged CSV import, validation, dry-run diff, idempotent upserts, dual-run cutover

## What's Been Done (June 2026)
- [x] Requirements gathering + confirmed choices
- [x] Full solution architecture & phased implementation plan (/app/ARCHITECTURE.md), updated for multi-project ownership + role-aware scoped chat
- [x] **Phase 1 MVP prototype built & fully tested (30/30 backend, 15/15 UI flows)** — all integrations MOCKED per user request:
  - PostgreSQL in-container (supervisor-managed); DATABASE_URL in backend/.env — swap to hosted Postgres (Neon/Supabase) at deploy
  - 6 agents with A2A agent cards, task log w/ idempotency keys, per-agent SSE-streaming chat (OpenAI gpt-5.4-mini via Emergent key)
  - Evaluation Agent: real LLM (gpt-4o) JD↔CV ranking, RankedCandidateList.v1 artifact, content-hash idempotent
  - Orchestrator state machine + events audit spine + transactional outbox (mock Slack feed + mock email inbox in Comms page)
  - PM approval gate (project-routed, DM override, staffing blocked), scheduling with skill/load interviewer matching, mock calendar/Meet
  - Monitoring: 1h invite SLA, sweep w/ idempotent reminders, simulated accept/decline, feedback + real AI transcript summary
  - Reporting: scoped summaries + idempotent daily digest distribution
  - Role-scoped everything via persona switcher (Diana dm / Priya pm-Phoenix / Pablo pm-Atlas / Sam staffing)
  - CSV import wizard (positions + interviewers, upsert = re-import safe)

## Backlog (prioritized)
### P1 — Phase 2 enhancements
- Slack interactive approvals; scheduled (cron) report distribution; reassignment flow after decline (auto re-match excluding declined interviewer is implemented; surface a dedicated button)
- Real login/auth (JWT or Google SSO) replacing persona switcher

### P2 — Phase 3–4
- Real Slack bot (token from user) behind existing Notifier
- Real Google Workspace adapters (Calendar/Meet/Gmail/Drive), per-agent service accounts
- Hosted PostgreSQL for deployment (CONFIRM AT DEPLOY TIME)
- Service split, analytics (time-to-fill, funnel)

## Next Tasks
1. User reviews prototype; feedback iterations
2. Phase 2: real Slack + interactive approvals when user provides bot token
3. At deploy: provide hosted Postgres URL (Neon/Supabase) — in-container Postgres is preview-only
