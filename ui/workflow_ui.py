"""Workflow controls; the API independently enforces every permission and invariant."""

from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st


def render_workflow(case, request, role):
    case_id = case["id"]
    version = case["version"]
    root = f"/cases/{case_id}"
    status = case["status"]
    st.caption(f"Owner: {case['owner'] or 'Unassigned'} • Record version: {version}")
    snapshot_key = f"snapshot_{case_id}"
    previous_version = st.session_state.get(snapshot_key)
    if previous_version is not None and previous_version != version:
        st.info("This case changed. The forms below now show the latest saved version.")
    st.session_state[snapshot_key] = version

    def save(method, path, payload, message):
        result = request(method, root + path, json={"expected_version": version, **payload})
        if result:
            st.session_state["workflow_notice"] = message
            st.rerun()

    for query in case["queries"]:
        st.write(f"Question {query['id']}: {query['disposition']}")
        if query["answer"]:
            st.text(f"Answer: {query['answer']}")
            st.text(f"Evidence: {query['evidence_reference']}")
        if query["dependency"]:
            st.text(f"Waiting on: {query['dependency']}")
    if case["resolution_note"]:
        st.markdown("**Recorded resolution (no email has been sent)**")
        st.text(case["resolution_note"])
    if case["closure_reason"]:
        st.text(f"Closure reason: {case['closure_reason']}")
    if case["commitments"]:
        st.markdown("**Customer commitments — due times in UTC**")
        st.dataframe(case["commitments"], hide_index=True)
    if role == "auditor":
        st.info("Read-only auditor access. Workflow changes require an agent or manager.")
        return
    st.markdown("**Case workflow**")
    form_suffix = f"{case_id}_{version}"
    if status not in {"resolved", "closed"}:
        with st.form(f"assignment_{form_suffix}"):
            choices = ["demo-agent", "demo-manager"] if role == "manager" else ["demo-agent"]
            owner = st.selectbox("Assign to demo owner", choices)
            assign = st.form_submit_button("Assign case")
        if assign:
            save("POST", "/assignment", {"owner": owner}, "Case assigned.")

    targets = {
        "assigned": ["in_progress"],
        "in_progress": ["awaiting_business_unit", "awaiting_customer", "pending_review"],
        "awaiting_business_unit": ["in_progress"],
        "awaiting_customer": ["in_progress"],
        "pending_review": ["in_progress"] if role == "manager" else [],
        "resolved": ["closed"],
    }.get(status, [])
    if targets:
        with st.form(f"transition_{form_suffix}"):
            target = st.selectbox("Next status", targets)
            reason = st.text_input("Reason for status change")
            transition = st.form_submit_button("Change status")
        if transition:
            save("POST", "/transition", {"target": target, "reason": reason}, "Status updated.")
    if status in {"in_progress", "awaiting_business_unit", "awaiting_customer"}:
        st.caption(
            "Use approved synthetic policies as evidence. A reference records your source; "
            "it does not verify the answer automatically."
        )
        for query in case["queries"]:
            with st.expander(f"Answer question {query['id']}: {query['question']}"):
                with st.form(f"query_{query['id']}_{form_suffix}"):
                    options = ["open", "answered", "waiting"]
                    disposition = st.selectbox(
                        "Question status", options, index=options.index(query["disposition"])
                    )
                    answer = st.text_area("Answer", value=query["answer"] or "")
                    evidence = st.text_input(
                        "Evidence / policy reference", value=query["evidence_reference"] or ""
                    )
                    dependency = st.text_area(
                        "Dependency note (for waiting questions)", value=query["dependency"] or ""
                    )
                    submitted = st.form_submit_button("Save question")
                if submitted:
                    save(
                        "PUT",
                        f"/queries/{query['id']}",
                        {
                            "disposition": disposition,
                            "answer": answer if disposition == "answered" else "",
                            "evidence_reference": evidence if disposition == "answered" else "",
                            "dependency": dependency if disposition == "waiting" else "",
                        },
                        "Question saved.",
                    )
        with st.expander("Add or complete a customer commitment"):
            with st.form(f"commitment_{form_suffix}"):
                description = st.text_input("Commitment description")
                now = datetime.now(ZoneInfo("Asia/Kolkata"))
                day = st.date_input("Due date (India time)", value=now.date())
                clock = st.time_input(
                    "Due time (India time)", value=now.time().replace(second=0, microsecond=0)
                )
                add = st.form_submit_button("Add commitment")
            if add:
                due = datetime.combine(day, clock, tzinfo=ZoneInfo("Asia/Kolkata"))
                save(
                    "POST",
                    "/commitments",
                    {"description": description, "due_at": due.isoformat()},
                    "Commitment added.",
                )
            for commitment in case["commitments"]:
                if commitment["completed_at"]:
                    continue
                with st.form(f"complete_{commitment['id']}_{form_suffix}"):
                    st.write(commitment["description"])
                    note = st.text_input("Completion evidence / note")
                    complete = st.form_submit_button("Complete commitment")
                if complete:
                    save(
                        "POST",
                        f"/commitments/{commitment['id']}/complete",
                        {"completion_note": note},
                        "Commitment completed.",
                    )
    if status in {"in_progress", "pending_review"}:
        if status == "pending_review" and role != "manager":
            st.info(
                "Awaiting a manager's review. Switch to the manager demo key to review this case."
            )
        else:
            with st.form(f"resolve_{form_suffix}"):
                resolution = st.text_area("Resolution summary")
                st.caption(
                    "All questions must be answered with evidence and all commitments completed. "
                    "This records a resolution; it does not send an email or post a waiver."
                )
                resolved = st.form_submit_button("Resolve case")
            if resolved:
                save("POST", "/resolve", {"resolution_note": resolution}, "Case resolved.")
    if status in {"resolved", "closed"}:
        with st.form(f"reopen_{form_suffix}"):
            reason = st.text_input("Reason for reopening")
            st.caption(
                "Reopening resets the question checklist. Previous answers remain in audit history."
            )
            reopened = st.form_submit_button("Reopen case")
        if reopened:
            save(
                "POST", "/reopen", {"reason": reason}, "Case reopened; review every question again."
            )
