# Build milestones

## 1 — Foundation and intake

Implemented: validated case intake, query checklist storage, persistent queue/detail, role-based demo access, duplicate protection, creation audit, Streamlit interface, schema migrations, and PostgreSQL CI configuration.

Verification results are recorded in `docs/VERIFICATION.md`. Resume metrics remain placeholders until measured. A test count is evidence about tested behavior, not banking performance.

## 2 — Ownership and resolution

Assignment, allowed state transitions, per-query answers and dependencies, manager review, commitments, reopen handling, and optimistic concurrency. Build and test the first complete service scenario.

## 3 — TAT and NFCR

Versioned business-calendar policies, response and resolution clocks, pause rules, persisted follow-up tasks, single scheduled worker, and escalation processing. Verify holidays, cutoffs, timezones, and worker restarts.

## 4 — Response simulation and reporting

Reviewed templates, interim/final response distinction, simulated delivery failures, KPI definitions with explicit denominators, and synthetic datasets.

## 5 — Deployment and measured portfolio release

Individual user authentication, managed PostgreSQL, HTTPS, secrets, monitoring, backups and restore exercise, release/rollback procedure, measured load tests, and final resume bullets. Select hosting with the user before incurring costs.

The full approved specification is retained in README.md. Each release must clearly distinguish implemented behavior from planned capabilities.
