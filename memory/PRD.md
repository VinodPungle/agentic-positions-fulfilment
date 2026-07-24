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

## Backlog (prioritized)
### P0 — Phase 1 MVP (awaiting user approval to build)
- Postgres schema + events + outbox + FileStore
- Evaluation Agent (JD/CV upload → ranked list, human + machine formats)
- Orchestrator: state machine, project-routed PM approval gate, role-scoped chat
- Scheduling Agent with mock calendar/email adapters (in-app viewers)
- Notifier with real Slack (needs bot token from user) + mock email
- Import wizard (positions/interviewers CSV, CV zip)
- Dashboard: pipeline board, approval queue, per-agent chats, notification log
- Seeded demo users (DM, 2 PMs, Staffing)

### P1 — Phase 2
- Monitoring Agent (invite SLA, Slack reminders, feedback form, transcript → LLM summary)
- Reporting Agent (scheduled + on-change, role-scoped distribution)
- Slack interactive approvals

### P2 — Phases 3–4
- Real Google Workspace adapters (Calendar/Meet/Gmail/Drive), per-agent service accounts
- Service split, SSO, analytics

## Next Tasks
1. User reviews architecture → approval or change requests
2. Collect Slack bot token + channel(s); optional sample JD/CVs/sheet exports
3. Decide build-time DB detail (in-container Postgres for MVP; hosted URL at deploy)
4. Begin Phase 1 implementation
