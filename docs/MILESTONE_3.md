# Milestone 3 — business deadlines and NFCR follow-up

This release implements illustrative service targets, not HDFC's internal benchmarks or policy. NFCR is used here as a working abbreviation for non-first-contact resolution. No email, chat, external notification, bank-system update, or financial posting is sent by the worker.

## Windows upgrade (preserve your existing case)

1. Stop the API and Streamlit terminals with **Ctrl+C**. Stop an older worker too if one is running.
2. Make a fresh copy of `resolvedesk.db` in File Explorer named `resolvedesk.before-m3.db`. Keep `.env` and all previous backups. Do not overwrite an earlier backup.
3. In an idle VS Code terminal at the project root:

```powershell
git pull --ff-only
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m pytest -q
```

The new dependency is APScheduler. The migration adds tables without modifying existing case contents, versions, answers, audit records, or commitment records. Legacy cases receive no backdated service clocks. A manager can activate an open legacy case from now; reopening any case creates a fresh cycle from now.

4. Start the API in its own terminal:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

5. Start the interface in another terminal:

```powershell
.\.venv\Scripts\python.exe -m streamlit run ui/app.py
```

6. Start the scanner in a third running terminal:

```powershell
.\.venv\Scripts\python.exe -m app.worker
```

It scans immediately on startup, then every 60 seconds. Keep it running for automatic checks. For one scan without a long-running process:

```powershell
.\.venv\Scripts\python.exe -m app.worker --once
```

The manager can also use **Deadline alerts → Run deadline check now**. This uses the server's actual clock; users cannot supply an arbitrary scan time through the API.

On macOS/Linux, replace the Windows executable path with `./.venv/bin/python`. In Compose, the dedicated `worker` service uses the same PostgreSQL database as the API and waits for migration completion. Full Compose startup still requires verification on a host with sufficient disk space.

## Clock definitions

| Clock | Starts | Target | Stops / qualifying event |
| --- | --- | --- | --- |
| First response | Case intake or start of a new service cycle | 120 working minutes by default | Explicit simulated first-response record |
| Initial same-day action | First assignment in the cycle | Office close that business day; next office close for out-of-hours allocation | Start/resume work, save a question, record simulated response, or create/review/complete an NFCR task |
| Resolution | Case intake or start of a new cycle | 480 working minutes by default | Resolution recorded |
| NFCR task | Task creation or explicit rescheduling | 120 working minutes by default, or an explicit aware due timestamp | Task completion; a reschedule ends the previous schedule and retains its evidence |
| Commitment | Explicit promise record | Its recorded absolute due timestamp | Commitment completion |

The first two service targets and follow-up target can be overridden per category in the policy API using `category_targets`. For example:

```json
{
  "charges": {
    "response_minutes": 60,
    "resolution_minutes": 240,
    "followup_minutes": 60
  }
}
```

All three fields are required within a category override. Categories without an override use the policy's base values. Assignment itself does not count as a qualifying service action. Reassignment does not reset deadlines. This initial-action clock is not a daily recurring productivity metric.

A recorded first response is explicitly a simulation and does not deliver an email. It does not stop or extend the resolution clock. If a case resolves without a response record, response status remains `not_recorded` or `overdue`; the app does not invent successful contact.

## Calendar and policy rules

The built-in `DEMO-IST-V1` policy uses Monday–Friday, 09:00–17:00 in `Asia/Kolkata`, with no preloaded holidays. Managers must configure any required holiday dates; this is not an official bank calendar.

Supported business zones are `Asia/Kolkata` and `UTC`, both without daylight-saving transitions. Weekdays, office opening/closing times, and holiday dates are configurable. Overnight shifts are unsupported; windows must be at least 15 minutes. Calculations are bounded to 100 years. Timestamps are normalized to UTC before SQLite persistence. The interface labels displayed India-time deadlines and UTC record tables explicitly.

For example, 120 working minutes from Friday 20 November 2026 at 16:30 IST ends on Monday 23 November at 10:30 IST. Marking Monday as a holiday moves that deadline to Tuesday at 10:30 IST. Exactly-at-deadline completion is on time; overdue means strictly after the deadline.

Publishing a policy creates a new immutable record. The highest published ID is the active version for future cycles. Every clock stores its own effective category-specific policy snapshot. Publishing a new version cannot silently change an open case's deadlines. There is no policy-edit endpoint. Restoring a prior configuration means publishing it under a new version name.

## Wait states and pause rules

- `awaiting_business_unit` requires at least one open NFCR task with a unit, owner, description, next action, and due date. Business-unit waiting does **not** pause the resolution clock.
- `awaiting_customer` does not pause by default. A published policy may explicitly enable a resolution pause for that state.
- A permitted pause shifts only the resolution deadline by working time spent paused. Weekends and holidays do not add extra pause credit.
- An already-overdue resolution cannot be hidden by starting a pause. First response, same-day action, task, and commitment deadlines never pause with the resolution clock.
- Resuming work persists the shifted resolution deadline. A restart cannot lose the pause start timestamp.

Query dependency notes remain separate from owned follow-up tasks. Recording a note alone does not establish NFCR ownership or a deadline.

## NFCR walkthrough using a new synthetic case

Keep your closed milestone-2 case as evidence. Create a separate case, such as message ID `nfcr-email-001`, customer `SYN-002`, subject `Synthetic charge requires business-unit input`.

1. Assign the new case to `demo-agent` and start work. Observe its first-response, same-day-action, and resolution deadlines under **Service deadlines and NFCR follow-up**.
2. Record a simulated first response with a note such as `Synthetic acknowledgement; charges-unit input requested`. Verify only the first-response clock stops.
3. Expand **Create a new NFCR follow-up task**. Select `charges`, owner `demo-charges-team`, and describe the synthetic evidence needed. Record the next action, such as `Ask the charges team for the charge record`. Leave the policy target enabled for a normal deadline.
4. Change the case to `awaiting_business_unit` with an explanatory reason. There is now a named dependency, an owner, and a deadline; the resolution clock continues.
5. Open **Review or complete NFCR task #...**. Record a review note and next action. If setting a new deadline, explicitly tick the reschedule checkbox. The previous schedule stays in audit history.
6. When the fictional unit input is available, use **Business-unit completion evidence** and the task-specific **Complete NFCR task #...** button. Do not create a new task to complete an existing one.
7. Resume `in_progress`, answer each customer question with fictional evidence, and finish the normal manager-review/resolution/closure workflow. Open follow-up tasks block resolution even when all questions and commitments are complete.

## Demonstrate an overdue escalation without waiting

Use a clearly described **synthetic backlog task**. When creating it, uncheck **Use the policy follow-up target** and set a custom due date in the past, in India time. This records an intentionally overdue demonstration dependency; it does not change the machine clock or API scan time.

Switch to the manager demo key and choose **Deadline alerts → Run deadline check now**. The task should produce an `overdue` alert requiring manager review. Run the check again: it must not create the same alert again. The scheduled worker performs the same check automatically.

A manager can acknowledge the alert. Acknowledgement records that it was seen; it does not complete the task or resolve the case. Complete or review/reschedule the underlying work separately. Old alerts remain as historical evidence after rescheduling. A breach that happened before rescheduling is recovered from review history even if the scanner was offline at that time.

## Reminders, recovery, and concurrency

Warnings are due when no more than the configured number of **working minutes** remain. At the default lead of 30 minutes, a reminder may appear outside office hours if only 30 working minutes remain until the target. A warning is not a breach. Completed-on-time work does not produce a later breach simply because the worker was restarted.

Overdue alerts are recovered for late completion or an old, breached task schedule. For a response missing at case resolution, the response obligation is evaluated at the recorded resolution time rather than indefinitely extending after closure.

A unique deduplication key includes the case, source type, source record, schedule/cycle generation, and alert level. Each generation gets at most one warning and one overdue alert. Rescheduling creates a new task generation. Resuming a resolution pause does not reset warning history.

Run one scheduled worker. PostgreSQL transaction advisory locks serialize overlapping scans; SQLite uses an immediate write transaction. The same controls protect overlaps with the manager's manual scan. Alert insertion and its `system-worker` audit event commit atomically. On database failure, the scheduled process logs a sanitized error and retries on the next tick. The one-shot command exits with a nonzero code on failure.

Worker alerts and acknowledgements add audit records without changing customer case versions. Workflow edits still use optimistic concurrency. Therefore the number of audit entries can exceed the case version from this milestone onward.

## Interview explanation

“I separated response, action, and resolution obligations because an acknowledgement does not resolve a customer's request. I calculate deadlines against a versioned office calendar and save the effective policy with each service cycle. Business-unit dependencies require a follow-up owner and deadline. A restart-safe scanner turns persisted obligations into deduplicated internal reminders and escalations, and preserves old breaches when a task is rescheduled.”

Trade-offs: fixed-offset office zones and batch scans make the behavior explainable. This release scans the recorded dataset rather than using a high-volume distributed scheduling system. Indexed/batched due queues, individual identities, worker heartbeat monitoring, external delivery, and production retention policies remain later deployment work. No throughput or real customer impact is claimed.
