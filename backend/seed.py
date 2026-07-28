import logging
from datetime import datetime, timezone, timedelta
from db import db, uid, now_iso, ensure_indexes
from pipeline import record_event, notify

logger = logging.getLogger(__name__)

JD_PYTHON = """Senior Backend Engineer (Python) — Project Levvia
Requirements: 6+ years backend engineering; expert Python (FastAPI/Django); PostgreSQL schema design & query optimization; event-driven architectures (Kafka/RabbitMQ); Docker & Kubernetes; CI/CD; AWS. Nice to have: Terraform, gRPC, observability (Prometheus/Grafana). Role: own microservices for the client billing platform, mentor 2 juniors, drive architecture reviews."""

JD_NODE = """Tech Lead (Node.js) — Project Spotlight
Requirements: 8+ years, 3+ leading teams; Node.js/TypeScript at scale; NestJS or Express; MongoDB & Redis; AWS ECS/Lambda; leading agile squads of 5-8; strong client communication. Role: technical leadership of the storefront platform team."""

CVS_PYTHON = [
    ("Ananya Rao", "ananya.rao@mail.demo", """Ananya Rao — Senior Software Engineer, 8 yrs.
Python (FastAPI, Django), PostgreSQL (partitioning, query tuning), Kafka event pipelines processing 2M msgs/day.
Led migration of monolith to 14 microservices on EKS (Kubernetes, Docker, Helm). AWS: ECS, RDS, SQS, Lambda.
CI/CD with GitHub Actions + ArgoCD. Terraform for infra. Mentored 3 junior engineers. Prometheus/Grafana dashboards."""),
    ("Marcus Chen", "marcus.chen@mail.demo", """Marcus Chen — Backend Engineer, 5 yrs.
Python (Flask), some FastAPI. MySQL mostly, 1 yr PostgreSQL. REST APIs for fintech startup.
Docker daily; Kubernetes exposure limited (managed by platform team). RabbitMQ for async jobs.
AWS EC2/S3. No Terraform. Strong algorithms background, competitive programmer."""),
    ("Elif Demir", "elif.demir@mail.demo", """Elif Demir — Staff Engineer, 10 yrs.
Java (Spring) 7 yrs, Python 3 yrs (FastAPI microservices). PostgreSQL expert incl. logical replication.
Kafka Streams, exactly-once pipelines. Kubernetes operators author. AWS + GCP. gRPC service mesh.
Tech lead for 6-person team, architecture review board member. Speaker at KubeCon."""),
    ("Diego Fuentes", "diego.fuentes@mail.demo", """Diego Fuentes — Full-stack Developer, 6 yrs.
JavaScript/React primary; Python (Django) for 2 yrs on side projects. MongoDB, some PostgreSQL.
Docker compose setups. No Kubernetes production experience. Firebase, Vercel deployments.
Strong UI skills, looking to move backend-heavy."""),
]

CVS_NODE = [
    ("Priyanka Shah", "priyanka.shah@mail.demo", """Priyanka Shah — Engineering Lead, 9 yrs.
Node.js/TypeScript 7 yrs, NestJS microservices, MongoDB sharded clusters, Redis caching layers.
Led 3 squads (18 engineers total) delivering e-commerce platform, 40k rpm peak. AWS ECS + Lambda.
Hiring panels, quarterly roadmaps, client-facing demos every sprint."""),
    ("Tomás Silva", "tomas.silva@mail.demo", """Tomás Silva — Senior Node Developer, 6 yrs.
Express + TypeScript, PostgreSQL, GraphQL APIs. Docker/K8s. Never formally led a team but mentors juniors.
Deep performance profiling experience (flame graphs, event loop tuning)."""),
    ("Grace Okoye", "grace.okoye@mail.demo", """Grace Okoye — Tech Lead, 8 yrs.
Node.js + Go. Led storefront re-platform for retail client (team of 6, 11 months, delivered early).
MongoDB Atlas, Redis, Kafka. AWS well-architected reviews. Strong stakeholder communication."""),
]

MOCK_TRANSCRIPT = """[00:00] Interviewer: Thanks for joining. Let's start with your experience on {skill}.
[02:14] Candidate: I spent the last three years building {skill} systems... (discusses architecture, tradeoffs, incident war stories)
[11:40] Interviewer: How would you design a rate limiter for a multi-tenant API?
[12:05] Candidate: I'd start with a token bucket per tenant in Redis... (details sliding window fallback, hot key mitigation)
[24:30] Interviewer: Tell me about a conflict in a past team.
[25:01] Candidate: A senior peer disagreed on service boundaries... (describes resolution via ADR + spike)
[38:20] Interviewer: Questions for me?
[38:31] Candidate: What does success look like in the first 90 days?
[41:00] Interview ends."""


def iso_in(**kw):
    return (datetime.now(timezone.utc) + timedelta(**kw)).isoformat()


def iso_ago(**kw):
    return (datetime.now(timezone.utc) - timedelta(**kw)).isoformat()


def seed():
    ensure_indexes()
    if db.projects.find_one():
        logger.debug('Seed skipped: projects collection already has data')
        return False
    logger.info('Seeding demo data (empty database detected)')

    phoenix = {'id': uid(), 'name': 'Levvia', 'client': 'Aurora Retail Group', 'active': True}
    atlas = {'id': uid(), 'name': 'Spotlight', 'client': 'Northwind Logistics', 'active': True}
    db.projects.insert_many([phoenix, atlas])

    sll = {'id': uid(), 'email': 'shantanu@delivery.demo', 'name': 'Shantanu', 'role': 'service_line_leader'}
    pm1 = {'id': uid(), 'email': 'hitesh@delivery.demo', 'name': 'Hitesh', 'role': 'pm'}
    pm2 = {'id': uid(), 'email': 'suchita@delivery.demo', 'name': 'Suchita', 'role': 'pm'}
    staff = {'id': uid(), 'email': 'disha@delivery.demo', 'name': 'Disha', 'role': 'staffing'}
    db.users.insert_many([sll, pm1, pm2, staff])
    db.user_project_assignments.insert_many([
        {'user_id': pm1['id'], 'project_id': phoenix['id']},
        {'user_id': pm2['id'], 'project_id': atlas['id']},
    ])

    interviewers = [
        {'id': uid(), 'name': 'Rohit Malhotra', 'email': 'rohit@panel.demo', 'role': 'Principal Engineer',
         'skills': ['python', 'fastapi', 'postgresql', 'kafka', 'kubernetes', 'aws'], 'seniority': 'principal', 'max_weekly': 5, 'active': True},
        {'id': uid(), 'name': 'Lena Fischer', 'email': 'lena@panel.demo', 'role': 'Staff Engineer',
         'skills': ['python', 'django', 'postgresql', 'terraform', 'aws'], 'seniority': 'staff', 'max_weekly': 5, 'active': True},
        {'id': uid(), 'name': 'Kwame Mensah', 'email': 'kwame@panel.demo', 'role': 'Engineering Manager',
         'skills': ['node.js', 'typescript', 'mongodb', 'leadership', 'aws'], 'seniority': 'manager', 'max_weekly': 5, 'active': True},
        {'id': uid(), 'name': 'Yuki Tanaka', 'email': 'yuki@panel.demo', 'role': 'Senior Frontend Engineer',
         'skills': ['react', 'typescript', 'javascript', 'css'], 'seniority': 'senior', 'max_weekly': 5, 'active': True},
        {'id': uid(), 'name': 'Olga Petrova', 'email': 'olga@panel.demo', 'role': 'DevOps Architect',
         'skills': ['kubernetes', 'terraform', 'aws', 'ci/cd', 'docker'], 'seniority': 'architect', 'max_weekly': 5, 'active': True},
        {'id': uid(), 'name': 'Arjun Iyer', 'email': 'arjun@panel.demo', 'role': 'Tech Lead',
         'skills': ['node.js', 'nestjs', 'mongodb', 'redis', 'leadership'], 'seniority': 'lead', 'max_weekly': 5, 'active': True},
    ]
    db.interviewers.insert_many(interviewers)

    def add_position(project, ticket, title, jd, status, priority, skills, **extra):
        p = {'id': uid(), 'project_id': project['id'], 'ticket_number': ticket, 'title': title,
             'jd_text': jd, 'status': status, 'priority': priority, 'opened_at': now_iso(),
             'internal_fit_decided_at': extra.get('internal_fit_decided_at'), 'meta': {'skills': skills}}
        db.positions.insert_one(p)
        return p

    def add_candidate(p, name, email, cv):
        c = {'id': uid(), 'position_id': p['id'], 'name': name, 'email': email,
             'cv_text': cv, 'source': 'sheets-import', 'created_at': now_iso()}
        db.candidates.insert_one(c)
        return c

    # SR-101: ready for live evaluation demo
    p101 = add_position(phoenix, 'SR-101', 'Senior Backend Engineer (Python)', JD_PYTHON, 'OPEN', 'high',
                        ['python', 'fastapi', 'postgresql', 'kafka', 'kubernetes', 'aws'])
    for name, email, cv in CVS_PYTHON:
        add_candidate(p101, name, email, cv)
    record_event(p101['id'], 'POSITION_OPENED', 'human', 'hitesh@delivery.demo', {'ticket': 'SR-101'})

    # SR-102: pending PM approval with pre-seeded evaluation
    p102 = add_position(phoenix, 'SR-102', 'Tech Lead (Node.js)', JD_NODE, 'PENDING_PM_APPROVAL', 'high',
                        ['node.js', 'nestjs', 'mongodb', 'redis', 'leadership'])
    cands = [add_candidate(p102, n, e, cv) for n, e, cv in CVS_NODE]
    ranked = {
        "schema": "RankedCandidateList.v1",
        "candidates": [
            {"candidate_id": cands[0]['id'], "name": "Priyanka Shah", "rank": 1, "score": 92,
             "strengths": ["7y Node/TS + NestJS", "Led 3 squads", "MongoDB+Redis at scale", "Client-facing"],
             "gaps": ["No Go exposure"],
             "reasoning": "Near-perfect JD match: leadership scope, stack depth and client communication all evidenced with concrete scale numbers."},
            {"candidate_id": cands[2]['id'], "name": "Grace Okoye", "rank": 2, "score": 87,
             "strengths": ["Led storefront re-platform", "Strong stakeholder skills", "Kafka + MongoDB"],
             "gaps": ["Slightly less NestJS-specific depth"],
             "reasoning": "Proven tech lead with directly relevant retail storefront delivery; marginally behind on framework specificity."},
            {"candidate_id": cands[1]['id'], "name": "Tomás Silva", "rank": 3, "score": 68,
             "strengths": ["Deep Node performance expertise", "Mentoring"],
             "gaps": ["No formal team leadership", "PostgreSQL not MongoDB"],
             "reasoning": "Strong IC but the JD requires 3+ years leading teams, which he lacks; better fit for a senior IC role."},
        ],
        "summary": "Two strong lead-level candidates (Shah, Okoye); Silva recommended only as fallback senior IC."
    }
    ev = {'id': uid(), 'position_id': p102['id'], 'model': 'gpt-4o', 'ranked_list': ranked,
          'human_report': "Priyanka Shah is the standout (92/100) with directly relevant squad leadership; Grace Okoye a close second (87). Tomás Silva lacks required leadership experience.",
          'input_hash': 'seed-sr-102', 'created_at': now_iso()}
    db.evaluations.insert_one(ev)
    db.approvals.insert_one({'id': uid(), 'position_id': p102['id'], 'evaluation_id': ev['id'],
                             'status': 'pending', 'approved_candidate_ids': [], 'actor': None,
                             'comment': None, 'decided_at': None, 'created_at': now_iso()})
    record_event(p102['id'], 'EVALUATION_COMPLETED', 'agent', 'evaluation', {'candidates': 3})
    record_event(p102['id'], 'STATUS_PENDING_PM_APPROVAL', 'agent', 'orchestrator', {'from': 'EVALUATING', 'to': 'PENDING_PM_APPROVAL'})
    notify('slack', '#recruitment-levvia', 'SR-102 shortlist ready',
           '[SR-102] Tech Lead (Node.js) — AI shortlist ready. @Hitesh approval required before scheduling.',
           key='slack:seed:sr102:approval', meta={'ticket': 'SR-102'})

    # SR-103: invite sent, SLA already breached
    p103 = add_position(atlas, 'SR-103', 'React Frontend Engineer',
                        'React 18+, TypeScript, state management, testing library, design systems. 4+ yrs.',
                        'INTERVIEW_INVITE_SENT', 'medium', ['react', 'typescript', 'javascript', 'css'])
    c103 = add_candidate(p103, 'Nadia Belkacem', 'nadia.b@mail.demo',
                         'Nadia Belkacem — Frontend Engineer, 5 yrs. React, TypeScript, Redux Toolkit, Storybook design systems, Jest/RTL, Next.js.')
    db.interviews.insert_one({'id': uid(), 'position_id': p103['id'], 'candidate_id': c103['id'],
                              'interviewer_id': interviewers[3]['id'], 'scheduled_at': iso_in(days=1),
                              'meet_link': 'https://meet.mock/sr-103-nadia', 'calendar_event_id': 'cal-evt-mock-103',
                              'feedback_form_ref': 'form-103', 'invite_status': 'pending',
                              'invite_sla_deadline': iso_ago(minutes=35),
                              'result': None, 'transcript_text': MOCK_TRANSCRIPT.format(skill='React'),
                              'transcript_summary': None,
                              'match_reason': 'Yuki Tanaka matched: 4/4 required skills (react, typescript, javascript, css), current load 0.',
                              'idempotency_key': f"sched:{p103['id']}:{c103['id']}:1", 'created_at': now_iso()})
    record_event(p103['id'], 'STATUS_INTERVIEW_INVITE_SENT', 'agent', 'scheduling', {'to': 'INTERVIEW_INVITE_SENT'})
    notify('email', 'yuki@panel.demo', 'Interview invite: Nadia Belkacem / SR-103',
           'Fitment interview scheduled (Meet + transcription enabled). Feedback form linked. Please accept within 1 hour.',
           key='email:seed:sr103:invite', meta={'ticket': 'SR-103'})

    # SR-104: accepted, awaiting feedback
    p104 = add_position(atlas, 'SR-104', 'DevOps Engineer',
                        'Kubernetes, Terraform, AWS, CI/CD pipelines, observability. 5+ yrs.',
                        'INTERVIEW_ACCEPTED', 'high', ['kubernetes', 'terraform', 'aws', 'ci/cd'])
    c104 = add_candidate(p104, 'Viktor Hansen', 'viktor.h@mail.demo',
                         'Viktor Hansen — DevOps Engineer, 7 yrs. EKS clusters, Terraform modules, GitHub Actions, Datadog, cost optimization saved 30% infra spend.')
    db.interviews.insert_one({'id': uid(), 'position_id': p104['id'], 'candidate_id': c104['id'],
                              'interviewer_id': interviewers[4]['id'], 'scheduled_at': iso_ago(hours=2),
                              'meet_link': 'https://meet.mock/sr-104-viktor', 'calendar_event_id': 'cal-evt-mock-104',
                              'feedback_form_ref': 'form-104', 'invite_status': 'accepted',
                              'invite_sla_deadline': iso_ago(days=1),
                              'result': None, 'transcript_text': MOCK_TRANSCRIPT.format(skill='Kubernetes and Terraform'),
                              'transcript_summary': None,
                              'match_reason': 'Olga Petrova matched: 4/4 required skills, current load 1.',
                              'idempotency_key': f"sched:{p104['id']}:{c104['id']}:1", 'created_at': now_iso()})
    record_event(p104['id'], 'INVITE_ACCEPTED', 'human', 'olga@panel.demo', {})

    # SR-105: internal fitment interview complete, PM marked the candidate Internal
    # Fit — the profile is ready to go forward to the client (a manual step outside
    # this app). Seeded with the full trail (feedback + transcript summary + fitment
    # decision already recorded) so the scenario is demoable without waiting on a
    # live LLM call.
    p105 = add_position(phoenix, 'SR-105', 'QA Automation Engineer',
                        'Playwright/Cypress, API testing, CI integration. 3+ yrs.', 'INTERNAL_FIT', 'low',
                        ['playwright', 'testing'], internal_fit_decided_at=iso_ago(days=1))
    c105 = add_candidate(p105, 'Noor Fatima', 'noor.fatima@mail.demo',
                         'Noor Fatima — QA Automation Engineer, 4 yrs. Playwright + Cypress end-to-end suites, '
                         'API contract testing (Postman/Newman in CI), reduced regression cycle from 2 days to 3 hours.')
    iv105_id = uid()
    iv105_key = f"sched:{p105['id']}:{c105['id']}:1"
    db.interviews.insert_one({'id': iv105_id, 'position_id': p105['id'], 'candidate_id': c105['id'],
                              'interviewer_id': interviewers[3]['id'], 'scheduled_at': iso_ago(days=2),
                              'meet_link': 'https://meet.mock/sr-105-noor', 'calendar_event_id': 'cal-evt-mock-105',
                              'feedback_form_ref': 'form-105', 'invite_status': 'accepted',
                              'invite_sla_deadline': iso_ago(days=3),
                              'result': 'pass',
                              'transcript_text': MOCK_TRANSCRIPT.format(skill='Playwright and CI test automation'),
                              'transcript_summary': (
                                  "- Strong hands-on Playwright/Cypress depth; walked through a real flaky-test "
                                  "triage from a past project\n"
                                  "- Comfortable owning CI integration end-to-end, not just writing tests\n"
                                  "- Communicated tradeoffs clearly when asked about test-pyramid balance\n"
                                  "- No concerns raised on either side; candidate asked sharp questions about "
                                  "the client's release cadence"),
                              'match_reason': 'Yuki Tanaka matched: adjacent frontend/testing overlap, current load 0.',
                              'fitment_decision': 'fit',
                              'fitment_comment': 'Ready to share with the client — strong technical round, no reservations.',
                              'fitment_decided_by': 'hitesh@delivery.demo', 'fitment_decided_at': iso_ago(days=1),
                              'idempotency_key': iv105_key, 'created_at': iso_ago(days=2)})
    db.feedback.insert_one({'id': uid(), 'interview_id': iv105_id, 'result': 'pass',
                            'comments': 'Confident, hands-on, good communicator. Recommend moving forward.',
                            'submitted_by': 'yuki@panel.demo', 'submitted_at': iso_ago(days=1, hours=6)})
    record_event(p105['id'], 'INVITE_ACCEPTED', 'human', 'yuki@panel.demo', {})
    record_event(p105['id'], 'FEEDBACK_SUBMITTED', 'human', 'yuki@panel.demo', {'result': 'pass'})
    record_event(p105['id'], 'STATUS_FEEDBACK_RECEIVED', 'agent', 'monitoring', {'to': 'FEEDBACK_RECEIVED'})
    record_event(p105['id'], 'INTERNAL_FIT_MARKED', 'human', 'hitesh@delivery.demo', {'candidate': 'Noor Fatima'})
    record_event(p105['id'], 'STATUS_INTERNAL_FIT', 'human', 'hitesh@delivery.demo',
                 {'from': 'FEEDBACK_RECEIVED', 'to': 'INTERNAL_FIT'})

    # SR-106: open, no candidates yet
    add_position(atlas, 'SR-106', 'Data Engineer', 'Spark, Airflow, dbt, Snowflake, Python. 4+ yrs.',
                 'OPEN', 'medium', ['python', 'spark', 'airflow'])

    # SR-107: the other outcome — internal interview went fine technically, but the
    # PM rejected internal fitment anyway after reading the transcript summary. This
    # is deliberately not a copy of the interviewer's own pass/fail: it demonstrates
    # why the fitment decision is a separate step from feedback, not the same one
    # relabeled — the interviewer's technical read and the PM's client-fit read can
    # differ, and only the PM's decision moves (or doesn't move) the position forward.
    p107 = add_position(atlas, 'SR-107', 'Site Reliability Engineer',
                        'Kubernetes, on-call ownership, incident response, Terraform. Client requires on-site presence '
                        '3 days/week. 5+ yrs.', 'INTERNAL_FIT_REJECTED', 'medium',
                        ['kubernetes', 'terraform', 'incident-response'], internal_fit_decided_at=iso_ago(hours=6))
    c107 = add_candidate(p107, 'Lukas Weber', 'lukas.weber@mail.demo',
                         'Lukas Weber — SRE, 6 yrs. Kubernetes at scale, on-call rotations, Terraform, remote-first '
                         'roles only — has not worked on-site in 4 years.')
    iv107_id = uid()
    iv107_key = f"sched:{p107['id']}:{c107['id']}:1"
    db.interviews.insert_one({'id': iv107_id, 'position_id': p107['id'], 'candidate_id': c107['id'],
                              'interviewer_id': interviewers[4]['id'], 'scheduled_at': iso_ago(hours=8),
                              'meet_link': 'https://meet.mock/sr-107-lukas', 'calendar_event_id': 'cal-evt-mock-107',
                              'feedback_form_ref': 'form-107', 'invite_status': 'accepted',
                              'invite_sla_deadline': iso_ago(days=1),
                              'result': 'pass',
                              'transcript_text': MOCK_TRANSCRIPT.format(skill='Kubernetes incident response'),
                              'transcript_summary': (
                                  "- Deep incident-response experience, walked through a real production outage well\n"
                                  "- Terraform and Kubernetes fundamentals are solid\n"
                                  "- When asked about the client's on-site expectation, was candid that he has been "
                                  "remote-first for 4+ years and would prefer to stay remote\n"
                                  "- Technically a strong hire; the on-site requirement is the open question, not the skillset"),
                              'match_reason': 'Olga Petrova matched: 3/3 required skills, current load 1.',
                              'fitment_decision': 'reject',
                              'fitment_comment': ('Technically strong and the interviewer feedback was positive, but the '
                                                  'client mandate is 3 days/week on-site and the candidate was explicit '
                                                  'about needing remote. Not a fit for this particular client engagement '
                                                  '— worth keeping in mind for a remote-eligible role.'),
                              'fitment_decided_by': 'suchita@delivery.demo', 'fitment_decided_at': iso_ago(hours=6),
                              'idempotency_key': iv107_key, 'created_at': iso_ago(hours=8)})
    db.feedback.insert_one({'id': uid(), 'interview_id': iv107_id, 'result': 'pass',
                            'comments': 'Strong technically, no red flags from the interview itself.',
                            'submitted_by': 'olga@panel.demo', 'submitted_at': iso_ago(hours=7)})
    record_event(p107['id'], 'INVITE_ACCEPTED', 'human', 'olga@panel.demo', {})
    record_event(p107['id'], 'FEEDBACK_SUBMITTED', 'human', 'olga@panel.demo', {'result': 'pass'})
    record_event(p107['id'], 'STATUS_FEEDBACK_RECEIVED', 'agent', 'monitoring', {'to': 'FEEDBACK_RECEIVED'})
    record_event(p107['id'], 'INTERNAL_FIT_REJECTED', 'human', 'suchita@delivery.demo', {'candidate': 'Lukas Weber'})
    record_event(p107['id'], 'STATUS_INTERNAL_FIT_REJECTED', 'human', 'suchita@delivery.demo',
                 {'from': 'FEEDBACK_RECEIVED', 'to': 'INTERNAL_FIT_REJECTED'})

    # SR-108: the live-demo scenario — feedback and the Monitoring Agent's transcript
    # summary are already in, but nobody has made the fitment call yet. Deliberately
    # left pending (unlike SR-105/107, which are already decided) so "PM marks a
    # candidate Internal Fit or Rejected" can be demonstrated as a real, clickable
    # action instead of narrated over an already-decided record.
    p108 = add_position(phoenix, 'SR-108', 'Backend Engineer (Node.js)',
                        'Node.js/TypeScript, NestJS, MongoDB, REST API design. Client-facing role. 5+ yrs.',
                        'FEEDBACK_RECEIVED', 'high', ['node.js', 'typescript', 'nestjs', 'mongodb'])
    c108 = add_candidate(p108, 'Farah Haddad', 'farah.haddad@mail.demo',
                         'Farah Haddad — Backend Engineer, 5 yrs. Node.js/NestJS microservices, MongoDB schema '
                         'design, built and owns a public REST API used by 3 external partners.')
    iv108_id = uid()
    iv108_key = f"sched:{p108['id']}:{c108['id']}:1"
    db.interviews.insert_one({'id': iv108_id, 'position_id': p108['id'], 'candidate_id': c108['id'],
                              'interviewer_id': interviewers[2]['id'], 'scheduled_at': iso_ago(hours=20),
                              'meet_link': 'https://meet.mock/sr-108-farah', 'calendar_event_id': 'cal-evt-mock-108',
                              'feedback_form_ref': 'form-108', 'invite_status': 'accepted',
                              'invite_sla_deadline': iso_ago(days=1),
                              'result': 'pass',
                              'transcript_text': MOCK_TRANSCRIPT.format(skill='Node.js and API design'),
                              'transcript_summary': (
                                  "- Solid NestJS/MongoDB depth, owns a real external-facing API in production\n"
                                  "- Explained a schema-migration tradeoff clearly when pushed on it\n"
                                  "- Client-facing role: candidate has done partner-facing API support before, "
                                  "comfortable fielding technical questions from external teams\n"
                                  "- No concerns raised by the interviewer; candidate is available to start within 3 weeks"),
                              'match_reason': 'Kwame Mensah matched: 3/4 required skills (node.js, mongodb, leadership), current load 0.',
                              'idempotency_key': iv108_key, 'created_at': iso_ago(days=1)})
    db.feedback.insert_one({'id': uid(), 'interview_id': iv108_id, 'result': 'pass',
                            'comments': 'Solid all-round. Comfortable with the client-facing part of the role.',
                            'submitted_by': 'kwame@panel.demo', 'submitted_at': iso_ago(hours=20)})
    record_event(p108['id'], 'INVITE_ACCEPTED', 'human', 'kwame@panel.demo', {})
    record_event(p108['id'], 'FEEDBACK_SUBMITTED', 'human', 'kwame@panel.demo', {'result': 'pass'})
    record_event(p108['id'], 'STATUS_FEEDBACK_RECEIVED', 'agent', 'monitoring', {'to': 'FEEDBACK_RECEIVED'})

    notify('slack', '#recruitment-spotlight', 'SLA warning',
           '[SR-103] Interviewer Yuki Tanaka has not accepted the invite within SLA. Reminder queued.',
           key='slack:seed:sr103:sla', meta={'ticket': 'SR-103'})
    return True


if __name__ == '__main__':
    print('seeded:', seed())
