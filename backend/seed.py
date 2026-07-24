from datetime import timedelta
from db import SessionLocal, engine
from models import (Base, Project, User, UserProjectAssignment, Position, Candidate,
                    Evaluation, Interviewer, Interview, Approval, Outbox)
from pipeline import record_event, notify, now

JD_PYTHON = """Senior Backend Engineer (Python) — Project Phoenix
Requirements: 6+ years backend engineering; expert Python (FastAPI/Django); PostgreSQL schema design & query optimization; event-driven architectures (Kafka/RabbitMQ); Docker & Kubernetes; CI/CD; AWS. Nice to have: Terraform, gRPC, observability (Prometheus/Grafana). Role: own microservices for the client billing platform, mentor 2 juniors, drive architecture reviews."""

JD_NODE = """Tech Lead (Node.js) — Project Atlas
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


def seed():
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        if db.query(Project).first():
            return False
        phoenix = Project(name='Phoenix', client='Aurora Retail Group')
        atlas = Project(name='Atlas', client='Northwind Logistics')
        db.add_all([phoenix, atlas])
        db.flush()

        dm = User(email='diana@delivery.demo', name='Diana Kessler', role='dm')
        pm1 = User(email='priya@delivery.demo', name='Priya Nair', role='pm')
        pm2 = User(email='pablo@delivery.demo', name='Pablo Ortiz', role='pm')
        staff = User(email='sam@delivery.demo', name='Sam Whitfield', role='staffing')
        db.add_all([dm, pm1, pm2, staff])
        db.flush()
        db.add_all([UserProjectAssignment(user_id=pm1.id, project_id=phoenix.id),
                    UserProjectAssignment(user_id=pm2.id, project_id=atlas.id)])

        interviewers = [
            Interviewer(name='Rohit Malhotra', email='rohit@panel.demo', role='Principal Engineer',
                        skills=['python', 'fastapi', 'postgresql', 'kafka', 'kubernetes', 'aws'], seniority='principal'),
            Interviewer(name='Lena Fischer', email='lena@panel.demo', role='Staff Engineer',
                        skills=['python', 'django', 'postgresql', 'terraform', 'aws'], seniority='staff'),
            Interviewer(name='Kwame Mensah', email='kwame@panel.demo', role='Engineering Manager',
                        skills=['node.js', 'typescript', 'mongodb', 'leadership', 'aws'], seniority='manager'),
            Interviewer(name='Yuki Tanaka', email='yuki@panel.demo', role='Senior Frontend Engineer',
                        skills=['react', 'typescript', 'javascript', 'css'], seniority='senior'),
            Interviewer(name='Olga Petrova', email='olga@panel.demo', role='DevOps Architect',
                        skills=['kubernetes', 'terraform', 'aws', 'ci/cd', 'docker'], seniority='architect'),
            Interviewer(name='Arjun Iyer', email='arjun@panel.demo', role='Tech Lead',
                        skills=['node.js', 'nestjs', 'mongodb', 'redis', 'leadership'], seniority='lead'),
        ]
        db.add_all(interviewers)
        db.flush()

        # POS-101: ready for live evaluation demo
        p101 = Position(project_id=phoenix.id, ticket_number='POS-101', title='Senior Backend Engineer (Python)',
                        jd_text=JD_PYTHON, status='OPEN', priority='high',
                        meta={'skills': ['python', 'fastapi', 'postgresql', 'kafka', 'kubernetes', 'aws']})
        db.add(p101)
        db.flush()
        for name, email, cv in CVS_PYTHON:
            db.add(Candidate(position_id=p101.id, name=name, email=email, cv_text=cv, source='sheets-import'))
        record_event(db, p101.id, 'POSITION_OPENED', 'human', 'priya@delivery.demo', {'ticket': 'POS-101'})

        # POS-102: pending PM approval with pre-seeded evaluation
        p102 = Position(project_id=phoenix.id, ticket_number='POS-102', title='Tech Lead (Node.js)',
                        jd_text=JD_NODE, status='PENDING_PM_APPROVAL', priority='high',
                        meta={'skills': ['node.js', 'nestjs', 'mongodb', 'redis', 'leadership']})
        db.add(p102)
        db.flush()
        cand_ids = []
        for name, email, cv in CVS_NODE:
            c = Candidate(position_id=p102.id, name=name, email=email, cv_text=cv, source='sheets-import')
            db.add(c)
            db.flush()
            cand_ids.append((c.id, name))
        ranked = {
            "schema": "RankedCandidateList.v1",
            "candidates": [
                {"candidate_id": cand_ids[0][0], "name": "Priyanka Shah", "rank": 1, "score": 92,
                 "strengths": ["7y Node/TS + NestJS", "Led 3 squads", "MongoDB+Redis at scale", "Client-facing"],
                 "gaps": ["No Go exposure"],
                 "reasoning": "Near-perfect JD match: leadership scope, stack depth and client communication all evidenced with concrete scale numbers."},
                {"candidate_id": cand_ids[2][0], "name": "Grace Okoye", "rank": 2, "score": 87,
                 "strengths": ["Led storefront re-platform", "Strong stakeholder skills", "Kafka + MongoDB"],
                 "gaps": ["Slightly less NestJS-specific depth"],
                 "reasoning": "Proven tech lead with directly relevant retail storefront delivery; marginally behind on framework specificity."},
                {"candidate_id": cand_ids[1][0], "name": "Tomás Silva", "rank": 3, "score": 68,
                 "strengths": ["Deep Node performance expertise", "Mentoring"],
                 "gaps": ["No formal team leadership", "PostgreSQL not MongoDB"],
                 "reasoning": "Strong IC but the JD requires 3+ years leading teams, which he lacks; better fit for a senior IC role."},
            ],
            "summary": "Two strong lead-level candidates (Shah, Okoye); Silva recommended only as fallback senior IC."
        }
        ev = Evaluation(position_id=p102.id, model='gpt-4o', ranked_list=ranked,
                        human_report="Priyanka Shah is the standout (92/100) with directly relevant squad leadership; Grace Okoye a close second (87). Tomás Silva lacks required leadership experience.",
                        input_hash='seed-pos-102')
        db.add(ev)
        db.flush()
        db.add(Approval(position_id=p102.id, evaluation_id=ev.id, status='pending'))
        record_event(db, p102.id, 'EVALUATION_COMPLETED', 'agent', 'evaluation', {'candidates': 3})
        record_event(db, p102.id, 'STATUS_PENDING_PM_APPROVAL', 'agent', 'orchestrator', {'from': 'EVALUATING', 'to': 'PENDING_PM_APPROVAL'})
        notify(db, 'slack', '#recruitment-phoenix', 'POS-102 shortlist ready',
               '[POS-102] Tech Lead (Node.js) — AI shortlist ready. @Priya Nair approval required before scheduling.',
               key='slack:seed:pos102:approval', meta={'ticket': 'POS-102'})

        # POS-103: invite sent, SLA already breached (demo for monitoring)
        p103 = Position(project_id=atlas.id, ticket_number='POS-103', title='React Frontend Engineer',
                        jd_text='React 18+, TypeScript, state management, testing library, design systems. 4+ yrs.',
                        status='INTERVIEW_INVITE_SENT', priority='medium',
                        meta={'skills': ['react', 'typescript', 'javascript', 'css']})
        db.add(p103)
        db.flush()
        c103 = Candidate(position_id=p103.id, name='Nadia Belkacem', email='nadia.b@mail.demo',
                         cv_text='Nadia Belkacem — Frontend Engineer, 5 yrs. React, TypeScript, Redux Toolkit, Storybook design systems, Jest/RTL, Next.js.', source='sheets-import')
        db.add(c103)
        db.flush()
        iv103 = Interview(position_id=p103.id, candidate_id=c103.id, interviewer_id=interviewers[3].id,
                          scheduled_at=now() + timedelta(days=1), meet_link='https://meet.mock/pos-103-nadia',
                          calendar_event_id='cal-evt-mock-103', feedback_form_ref='form-103',
                          invite_status='pending', invite_sla_deadline=now() - timedelta(minutes=35),
                          transcript_text=MOCK_TRANSCRIPT.format(skill='React'),
                          match_reason='Yuki Tanaka matched: 4/4 required skills (react, typescript, javascript, css), current load 0.',
                          idempotency_key=f'sched:{p103.id}:{c103.id}:1')
        db.add(iv103)
        record_event(db, p103.id, 'STATUS_INTERVIEW_INVITE_SENT', 'agent', 'scheduling', {'to': 'INTERVIEW_INVITE_SENT'})
        notify(db, 'email', 'yuki@panel.demo', 'Interview invite: Nadia Belkacem / POS-103',
               'Fitment interview scheduled (Meet + transcription enabled). Feedback form linked. Please accept within 1 hour.',
               key='email:seed:pos103:invite', meta={'ticket': 'POS-103'})

        # POS-104: accepted, awaiting feedback (demo feedback + transcript summary)
        p104 = Position(project_id=atlas.id, ticket_number='POS-104', title='DevOps Engineer',
                        jd_text='Kubernetes, Terraform, AWS, CI/CD pipelines, observability. 5+ yrs.',
                        status='INTERVIEW_ACCEPTED', priority='high',
                        meta={'skills': ['kubernetes', 'terraform', 'aws', 'ci/cd']})
        db.add(p104)
        db.flush()
        c104 = Candidate(position_id=p104.id, name='Viktor Hansen', email='viktor.h@mail.demo',
                         cv_text='Viktor Hansen — DevOps Engineer, 7 yrs. EKS clusters, Terraform modules, GitHub Actions, Datadog, cost optimization saved 30% infra spend.', source='sheets-import')
        db.add(c104)
        db.flush()
        iv104 = Interview(position_id=p104.id, candidate_id=c104.id, interviewer_id=interviewers[4].id,
                          scheduled_at=now() - timedelta(hours=2), meet_link='https://meet.mock/pos-104-viktor',
                          calendar_event_id='cal-evt-mock-104', feedback_form_ref='form-104',
                          invite_status='accepted', invite_sla_deadline=now() - timedelta(days=1),
                          transcript_text=MOCK_TRANSCRIPT.format(skill='Kubernetes and Terraform'),
                          match_reason='Olga Petrova matched: 4/4 required skills, current load 1.',
                          idempotency_key=f'sched:{p104.id}:{c104.id}:1')
        db.add(iv104)
        record_event(db, p104.id, 'INVITE_ACCEPTED', 'human', 'olga@panel.demo', {})

        # POS-105: filled
        p105 = Position(project_id=phoenix.id, ticket_number='POS-105', title='QA Automation Engineer',
                        jd_text='Playwright/Cypress, API testing, CI integration. 3+ yrs.', status='FILLED',
                        priority='low', filled_at=now() - timedelta(days=3), meta={'skills': ['playwright', 'testing']})
        db.add(p105)
        db.flush()
        record_event(db, p105.id, 'STATUS_FILLED', 'human', 'sam@delivery.demo', {'to': 'FILLED'})

        # POS-106: open, no candidates yet
        p106 = Position(project_id=atlas.id, ticket_number='POS-106', title='Data Engineer',
                        jd_text='Spark, Airflow, dbt, Snowflake, Python. 4+ yrs.', status='OPEN', priority='medium',
                        meta={'skills': ['python', 'spark', 'airflow']})
        db.add(p106)

        notify(db, 'slack', '#recruitment-atlas', 'SLA warning',
               '[POS-103] Interviewer Yuki Tanaka has not accepted the invite within SLA. Reminder queued.',
               key='slack:seed:pos103:sla', meta={'ticket': 'POS-103'})
        db.commit()
        return True
    finally:
        db.close()


if __name__ == '__main__':
    print('seeded:', seed())
