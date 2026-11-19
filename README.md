# ResolveDesk
### Banking Email Resolution & TAT Workbench

**Build status: Milestone 3 — business-calendar TAT and NFCR follow-up.**

This is a synthetic-data portfolio application. It is not an HDFC integration. The full approved design below describes our roadmap, including features not implemented yet.

## Start here

- [VS Code setup and first walkthrough](docs/GETTING_STARTED.md)
- [Milestones and verification](docs/MILESTONES.md)
- [Security boundaries](docs/SECURITY.md)

### Implemented in milestone 1

- Authenticated FastAPI case intake with agent, manager, and read-only auditor demo roles.
- Persistent case and query records, unique source-message IDs, and atomic creation audit events.
- Paginated case queue, case detail, and audit-history APIs.
- Streamlit intake and browsing interface.
- Alembic migrations, local SQLite mode, and PostgreSQL deployment configuration.

### Implemented in milestone 2

- Demo owner assignment, explicit state transitions, and API-enforced manager review.
- Per-question answers with evidence references or dependency notes.
- Customer commitments with timezone-aware due dates and completion evidence.
- Resolution checks, closure reasons, and reopening that resets the checklist while preserving prior answers in audit history.
- Optimistic concurrency with record versions and atomic audit entries for every workflow change.
- A migration tested against existing milestone-1 case data.

See [the milestone-2 walkthrough](docs/MILESTONE_2.md) for upgrade instructions and the synthetic service scenario.

### Implemented in milestone 3

- Versioned office calendars, holidays, category-specific targets, and persisted service-cycle snapshots.
- Separate first-response, initial same-day-action, and resolution deadlines; explicit policy-controlled customer-wait pauses.
- Owned NFCR tasks with business units, next actions, reviewed rescheduling, completion evidence, and resolution safeguards.
- APScheduler worker, deduplicated internal warnings/escalations, missed-breach recovery, and manager acknowledgement.
- Deadline and policy tabs, plus a migration that does not backdate legacy case clocks.

See [the milestone-3 upgrade and walkthrough](docs/MILESTONE_3.md). Use synthetic data only. The default calendar and targets are illustrative, not HDFC policies.

### Not implemented yet

Individual user authentication/SSO, actual response delivery, automated policy evidence verification, service KPI dashboards, and production hosting/operations remain later milestones. Do not present these as completed resume achievements.

---

## Approved project specification

# ResolveDesk
### Banking Email Resolution & TAT Workbench

> Status: Proposed portfolio application; implementation pending approval.
> Scope: Synthetic customer data and simulated banking services. No connection to HDFC Bank systems.

## Project overview and business problem
ResolveDesk is a Python application that helps a customer service employee manage banking email cases from intake to closure.

A bank needs accurate, timely responses and a reliable record of what happened. An email inbox alone does not clearly show case ownership, outstanding dependencies, customer commitments, or approaching deadlines.

ResolveDesk provides a structured workflow for:
- Capturing customer requests and associated interactions.
- Tracking every question raised in an email.
- Distinguishing cases that can be resolved immediately from cases requiring another team.
- Preparing responses from approved demonstration templates.
- Monitoring first-response, follow-up, and resolution deadlines.
- Maintaining an attributable history of actions and decisions.

It supports employee judgment. It does not independently verify real customers, access accounts, or send financial instructions.

## JD alignment
The application demonstrates email resolution, first contact resolution, NFCR follow-up, customer communication, same-day action monitoring, TAT adherence, and accurate interaction logging.

NFCR is interpreted as “non-first-contact resolution.” This is a working interpretation rather than a claim about HDFC’s internal terminology.

## System architecture and workflow
```
Synthetic email / manual case entry
                 |
       Input validation and deduplication
                 |
          Case and query checklist
                 |
      Agent review and categorization
          /                    \
Resolvable using          Business-unit input
verified demo data        or approval required
       |                         |
Response preparation      NFCR task + owner
       |                         |
Completeness check        Follow-up and escalation
          \                    /
          Human-approved response
                     |
           Resolution and closure
                     |
       Interaction history and reporting
```

### Application components
| Component | Responsibility |
| Streamlit interface | Case queue, case detail, response preparation, manager views |
| FastAPI service | Validation, permissions, workflow transitions, reporting endpoints |
| PostgreSQL | Cases, interactions, tasks, policies, and audit events |
| Scheduled worker | Deadline checks, reminders, and escalation processing |
| Synthetic mail adapter | Imports demonstration emails and records simulated outbound responses |

**Core data entities:** Customer reference, case, email message, query item, interaction, task, commitment, response, TAT policy, user, and audit event.

**Proposed case states:** New, Assigned, In Progress, Awaiting Business Unit, Awaiting Customer, Resolved, and Closed.

Reopening creates an explicit event and returns the case to an active state. Sending an interim response does not count as resolution.

## Tech stack and justification
The JD specifies no technical stack. These are implementation choices intended to keep the project understandable and practical.

| Technology | Why it is suitable |
| Python | Readable business rules, validation, and reporting |
| FastAPI + Pydantic | Validated API contracts and clear separation of interface from workflow rules |
| Streamlit | Rapid development of an internal operations workbench |
| PostgreSQL + SQLAlchemy | Relational integrity, transactions, and durable case history |
| Alembic | Versioned database schema changes |
| APScheduler in one dedicated worker | Simple scheduled checks without requiring a message broker |
| pytest + HTTPX | Business-rule, API, and integration verification |
| Docker Compose | Repeatable local application and database setup |
| GitHub Actions | Automated checks before merging changes |

The scheduler will use database-backed task records and idempotent processing. Its deployment will run as a single worker; additional workers would require a deliberate coordination design.

## Key features and edge cases
### Accurate customer resolution
- Represent multiple questions within one email as a checklist.
- Require an answer or documented dependency for every question.
- Separate draft preparation, response submission, and case closure.
- Require a closure reason and supporting resolution record.
- Use explicit references to synthetic policies and account information.

### NFCR and follow-up
- Record the responsible business unit, named owner, next action, and due date.
- Track interim responses separately from final responses.
- Escalate overdue dependencies.
- Preserve the case history when ownership changes.

### TAT handling
- Maintain separate clocks for first response, next action, and final resolution.
- Configure working hours, holidays, timezone, and case-category targets.
- Store timestamps in UTC and display them in the configured business timezone.
- Pause clocks only where a configured policy explicitly permits it.
- Measure same-day action separately from final resolution.

### Security and integrity
- Agent, manager, and auditor permissions enforced by the API.
- Synthetic customer identifiers with masking in list views.
- No sensitive email content or credentials in operational logs.
- Audit events for assignment, edits, responses, status changes, and exports.
- Optimistic concurrency checks to prevent one employee overwriting another’s updates.

### Edge cases
- Duplicate messages: deduplicate by source identifier; flag ambiguous matches.
- New questions in a resolved thread: reopen or create a linked case using explicit rules.
- Failed simulated sending: retain the response as unsent; do not mark it delivered.
- Worker restart: recompute outstanding deadlines from persisted records.
- Missing policy information: block unsupported resolution and create a review task.
- Out-of-hours allocation: apply the configured calendar rather than assuming a 24-hour SLA.

## Metrics and acceptance criteria
Metrics will use documented definitions:
- **First-response compliance:** Eligible cases receiving a qualifying response within their configured response target.
- **Resolution TAT compliance:** Eligible resolved cases completed within their resolution target.
- **Same-day action compliance:** Allocated cases with a qualifying action by the configured business-day cutoff.
- **FCR proxy:** Eligible resolved cases completed in the first qualifying response without a business-unit dependency or reopening during a stated observation period.
- **Record completeness:** Eligible records satisfying the required-field and workflow checks.

FCR results will be labeled as a portfolio proxy. Cases without a complete observation period will be excluded or shown separately.

Planned verification includes deadline calculations, duplicate intake, access controls, invalid transitions, reopened cases, concurrent updates, and failed response delivery. Performance reports will state dataset size, hardware, concurrency, and endpoint tested.

## Deployment and operational readiness
The planned deployment includes an application service, a dedicated worker, managed PostgreSQL, HTTPS, secret configuration, database migrations, health checks, structured logs, and backup/restore verification.

A deployment guide will cover local VS Code setup, environment configuration, schema migrations, demonstration data, troubleshooting, and rollback.

Production readiness will be assessed against documented checks. The portfolio will not claim certification or readiness for live bank customer data.

## Interview talking points
- “I translated email handling into a case lifecycle with ownership, deadlines, and evidence of resolution.”
- “I separated a prompt acknowledgement from complete resolution so the dashboard cannot reward empty holding responses.”
- “I used deterministic templates and human review because accuracy matters more than impressive-looking automation.”
- “Business calendars and reopen rules materially change TAT and FCR calculations.”
- “The system records commitments so another employee can continue the case without relying on memory.”

**Main trade-off:** A modular application is easier to build, test, and explain than microservices at this scale. Email ingestion and response delivery are isolated behind adapters for future integration.

## Resume-ready bullet templates
Use these after implementation, replacing brackets with measured results:
- Built a Python, FastAPI, and PostgreSQL banking service workbench to manage **[N] synthetic email cases**, achieving **[X%] required-record completeness** across a documented validation dataset.
- Implemented business-calendar TAT monitoring and NFCR follow-up workflows, detecting **[X/Y] seeded overdue cases** across **[N] deadline scenarios**.
- Developed query-completeness checks and reviewed response templates, reducing median case-preparation time from **[A] to [B] minutes** in **[N] controlled trials**.
- Enforced role-based access and attributable interaction logging, passing **[N] authorization and case-integrity scenarios** in automated testing.
