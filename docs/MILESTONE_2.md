# Milestone 2 — ownership and resolution

## Upgrade your existing Windows copy

Run these steps from the project folder in VS Code. Keep your existing `.env` and database.

1. In the API terminal, press **Ctrl+C** to stop Uvicorn.
2. In the interface terminal, press **Ctrl+C** to stop Streamlit.
3. In File Explorer, copy `resolvedesk.db` to a backup named `resolvedesk.before-m2.db`. Do this before migrating; keep any earlier backup rather than replacing it.
4. In an idle terminal, run:

```powershell
git pull --ff-only
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m pytest -q
```

The migration preserves existing cases. It adds an unassigned owner, version 1, and open query states to old cases. It adds audit detail fields and a commitments table. Do not delete your database or regenerate keys.

5. Start the API:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

6. In a separate terminal start the interface:

```powershell
.\.venv\Scripts\python.exe -m streamlit run ui/app.py
```

7. Refresh http://localhost:8501 and use your existing `AGENT_API_KEY`.

For macOS/Linux, use `./.venv/bin/python` in place of the Windows executable path.

## Try the first complete synthetic service scenario

Use the existing charge-query case. The answers below rely on an explicitly invented training scenario: the synthetic charge record is DEMO-CHARGE-001, the demonstration policy is DEMO-FEE-POLICY-001 section 2, and a review decision DEMO-REVIEW-001 declines the waiver after manager review. These are illustrative references, not real HDFC policies or a waiver engine result. The present app stores references; it does not validate their existence.

1. In **Case queue**, open your existing case. Under **Case workflow**, choose `demo-agent` and click **Assign case**. Status becomes `assigned`.
2. Choose `in_progress`, enter `Begin synthetic charge investigation`, and click **Change status**.
3. Open the first **Answer question** expander. Set question status to `answered`. Enter `In this training scenario, the INR 500 fee is the service charge shown in synthetic record DEMO-CHARGE-001.` Use evidence `DEMO-CHARGE-001; DEMO-FEE-POLICY-001 section 2`. Click **Save question**.
4. For the second question, choose `answered`. Enter `Under this illustrative scenario, the proposed waiver is declined under the demonstration policy; manager review is required before finalizing this outcome.` Use evidence `DEMO-FEE-POLICY-001 section 2; proposed decision DEMO-REVIEW-001`. Save.
5. Try the optional commitment flow below before submitting for manager review.
6. Change status to `pending_review` with reason `Manager review required for the proposed waiver decline`.
7. Using the agent key, confirm the interface shows that a manager decision is required. Replace the sidebar key with `MANAGER_API_KEY` from your local `.env` file and press Enter.
8. Review both recorded answers. To request corrections, choose `in_progress` and record the review reason. For this training scenario, accept the illustrative outcome: enter resolution summary `Reviewed DEMO-CHARGE-001 and the illustrative policy. Both questions are addressed. The synthetic waiver decline has been reviewed; no financial transaction or email has been sent.` Click **Resolve case**.
9. Status becomes `resolved`. You can now change it to `closed` with reason `Synthetic service review complete; resolution record retained`.
10. Review audit history: assignment, state changes, answers, and resolution have attributable demo-role events and record versions. This verifies the recorded workflow, not the truth of a financial policy.

## Optional controls to try

- Before answering all questions, attempt resolution. Expect 409; no status change occurs.
- Mark a question `waiting` and enter a dependency note. Resolution remains blocked until it is answered with evidence.
- Add a customer commitment using an India-time due date/time. The API stores UTC and the table labels UTC. Attempt resolution while it is open; expect 409. Complete it with an evidence note before resolving. Dates may be in the past so existing missed promises can be recorded; deadline escalation is a later milestone.
- Reopen a resolved or closed case with a reason. It returns to `in_progress`, clears the current resolution, and resets questions to open. Previous answers remain in audit history.
- API edits include `expected_version`. Repeating an edit with an old version returns 409. The UI keys forms by record version and refreshes them when a newer case is loaded; stale form content is discarded rather than applied to the newer record.

## State and permission rules

| Current state | Allowed next action |
| --- | --- |
| new | Assign an owner |
| assigned | Start work (`in_progress`) |
| in_progress | Wait for unit/customer, request manager review, or resolve after checks |
| awaiting_business_unit / awaiting_customer | Resume work; record question updates and commitments |
| pending_review | Manager returns to work or resolves after completeness checks |
| resolved | Close with a reason, or reopen |
| closed | Reopen with a reason |

All resolution paths require every question answered with an evidence reference and all commitments complete. Query and commitment editing is available only while work is in progress or awaiting input. Manager review freezes these edits until a manager returns the case to work. Agents can edit the shared demo-agent owner's cases; managers can intervene across demo owners. Auditors are read-only.

## Architecture and interview explanation

The client submits the record version alongside each action. The API checks permissions, ownership, state, and completeness, then saves the changes and an audit event in one transaction. SQLAlchemy uses the old version in the database UPDATE predicate; if another transaction has changed the case, the second update fails and its entire transaction rolls back. This protects query and commitment writes as well as case status changes.

This provides safe concurrent editing without holding long-lived database locks while an employee fills out a form. Clients must refresh after conflicts. Shared role keys and manually supplied evidence references are deliberate portfolio limitations pending individual authentication and policy integrations.
