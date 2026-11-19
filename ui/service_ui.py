"""TAT/NFCR screens with clearly separated create, review, and completion forms."""

from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st


def local_time(value):
    if not value:
        return "—"
    return (
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        .astimezone(ZoneInfo("Asia/Kolkata"))
        .strftime("%d %b %Y, %I:%M:%S %p IST")
    )


def notice(message):
    st.session_state["workflow_notice"] = message
    st.rerun()


def due_inputs(prefix, day=None, clock=None):
    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    date = st.date_input(
        "Custom due date (India time)", value=day or now.date(), key=f"{prefix}_day"
    )
    time = st.time_input(
        "Custom due time (India time)",
        value=clock or now.time().replace(second=0, microsecond=0),
        key=f"{prefix}_time",
    )
    return datetime.combine(date, time, tzinfo=ZoneInfo("Asia/Kolkata")).isoformat()


def render_service(case, request, role):
    base = f"/cases/{case['id']}"
    service = request("GET", base + "/service")
    if service is None:
        return
    st.markdown("### Service deadlines and NFCR follow-up")
    version = case["version"]
    suffix = f"{case['id']}_{version}"
    if service["tracked"]:
        clock = service["clocks"][-1]
        st.caption(
            f"Cycle {clock['cycle']} • Policy {clock['policy_snapshot']['name']} "
            "• Displayed in India time"
        )
        st.dataframe(
            [
                {
                    "Deadline": "First simulated response",
                    "Due": local_time(clock["response_due_at"]),
                    "State": clock["response_state"],
                },
                {
                    "Deadline": "Same-day qualifying action",
                    "Due": local_time(clock["action_due_at"]),
                    "State": clock["action_state"],
                },
                {
                    "Deadline": "Resolution",
                    "Due": local_time(clock["resolution_due_at"]),
                    "State": clock["resolution_state"],
                },
            ],
            hide_index=True,
        )
        if clock["paused_at"]:
            st.info(
                "Resolution is paused under this policy. "
                "First-response and task deadlines continue running."
            )
        if (
            role != "auditor"
            and case["status"] not in {"new", "resolved", "closed"}
            and not clock["first_response_at"]
        ):
            with st.form(f"response_{suffix}"):
                st.markdown("**Record a simulated first response**")
                response_note = st.text_input("Response evidence / note (simulation only)")
                response = st.form_submit_button("Record simulated first response")
            if response and request(
                "POST",
                base + "/first-response",
                json={"expected_version": version, "note": response_note},
            ):
                notice("Simulated first response recorded. No email was sent.")
    else:
        st.info(
            "This historical case has no service clock. "
            "New cases and reopened cases get a new clock; "
            "old deadlines are not backdated."
        )
        if role == "manager" and case["status"] not in {"resolved", "closed"}:
            if st.button("Activate tracking from now", key=f"activate_{suffix}"):
                if request(
                    "POST", base + "/service-clock/start", json={"expected_version": version}
                ):
                    notice("Service tracking activated from now.")
    tasks = service["followups"]
    if tasks:
        st.markdown("**NFCR task records — timestamps in UTC**")
        st.dataframe(tasks, hide_index=True)
    editable = case["status"] in {"in_progress", "awaiting_business_unit", "awaiting_customer"}
    if role != "auditor" and editable and service["tracked"]:
        with st.expander("Create a new NFCR follow-up task"):
            with st.form(f"followup_new_{suffix}"):
                unit = st.selectbox(
                    "Responsible business unit",
                    ["charges", "cards", "payments", "branch_operations"],
                )
                owner = st.text_input("Business-unit demo owner", value="demo-charges-team")
                description = st.text_area("What input is needed from the unit?")
                action = st.text_input("Next follow-up action")
                policy_due = st.checkbox("Use the policy follow-up target", value=True)
                st.caption(
                    "Custom dates below apply only when the policy-target checkbox is unchecked. "
                    "Past dates can represent an overdue synthetic backlog task."
                )
                due = due_inputs("create_" + suffix)
                create = st.form_submit_button("Create NFCR task")
            if create:
                payload = {
                    "expected_version": version,
                    "unit": unit,
                    "owner": owner,
                    "description": description,
                    "next_action": action,
                }
                if not policy_due:
                    payload["due_at"] = due
                if request("POST", base + "/follow-ups", json=payload):
                    notice("NFCR task created with an owner, next action, and deadline.")
        for task in tasks:
            if task["completed_at"]:
                continue
            task_id = task["id"]
            with st.expander(f"Review or complete NFCR task #{task_id}: {task['description']}"):
                st.markdown(f"**Owner:** {task['owner']} • **Due:** {local_time(task['due_at'])}")
                with st.form(f"review_{task_id}_{suffix}"):
                    st.markdown("**Record a follow-up review**")
                    review_note = st.text_input("Review evidence / note")
                    next_action = st.text_input(
                        "Next action after review", value=task["next_action"]
                    )
                    next_owner = st.text_input("Task owner after review", value=task["owner"])
                    reschedule = st.checkbox("Set a new due date with this review", value=False)
                    due = due_inputs(f"review_{task_id}_{suffix}")
                    review = st.form_submit_button(f"Record review for NFCR task #{task_id}")
                if review:
                    payload = {
                        "expected_version": version,
                        "note": review_note,
                        "next_action": next_action,
                        "owner": next_owner,
                    }
                    if reschedule:
                        payload["due_at"] = due
                    if request("POST", f"{base}/follow-ups/{task_id}/review", json=payload):
                        notice("NFCR follow-up review recorded.")
                with st.form(f"finish_{task_id}_{suffix}"):
                    st.markdown("**Complete this existing task**")
                    evidence = st.text_input("Business-unit completion evidence")
                    finish = st.form_submit_button(f"Complete NFCR task #{task_id}")
                if finish and request(
                    "POST",
                    f"{base}/follow-ups/{task_id}/complete",
                    json={"expected_version": version, "completion_note": evidence},
                ):
                    notice("NFCR task completed; resume case work before resolution.")
    if service["alerts"]:
        st.markdown("**Deadline alerts for this case (latest 200)**")
        st.dataframe(service["alerts"], hide_index=True)


def render_operations(request, role):
    st.subheader("Internal deadline reminders and escalations")
    st.caption(
        "Warnings prompt the owner. Overdue alerts require manager review. "
        "These are internal records; no external messages are sent."
    )
    if role == "manager" and st.button("Run deadline check now"):
        result = request("POST", "/operations/deadline-scan")
        if result is not None:
            notice(
                "Another scanner is running."
                if result["busy"]
                else f"Deadline check finished: {result['created']} new alerts."
            )
    alerts = request("GET", "/alerts")
    if alerts is not None:
        st.dataframe(alerts, hide_index=True)
        open_alerts = [a for a in alerts if not a["acknowledged_at"]]
        if open_alerts and role == "manager":
            choices = {a["id"]: f"#{a['id']}: {a['source']} — {a['level']}" for a in open_alerts}
            selected = st.selectbox("Alert to acknowledge", choices, format_func=choices.get)
            if st.button("Acknowledge selected alert"):
                if request("POST", f"/alerts/{selected}/acknowledge"):
                    notice(
                        "Alert acknowledged. Its underlying deadline or task still requires action."
                    )
    st.info(
        "Automatic checks require a separate terminal running: python -m app.worker. "
        "The manager button above performs a single immediate scan."
    )


def render_policies(request, role):
    data = request("GET", "/service-policies")
    if data is None:
        return
    st.subheader("Versioned demonstration service policies")
    st.caption(
        "The highest published policy ID applies to new service cycles only. "
        "Existing clock snapshots are preserved. "
        "These are illustrative targets, not HDFC benchmarks."
    )
    st.json(data["active"])
    if role != "manager":
        return
    with st.expander("Publish a new policy version"):
        with st.form("publish_policy"):
            name = st.text_input("Unique policy version name", placeholder="DEMO-IST-V2")
            zone = st.selectbox("Business timezone", ["Asia/Kolkata", "UTC"])
            opens = st.time_input("Office opens", value=datetime.strptime("09:00", "%H:%M").time())
            closes = st.time_input(
                "Office closes", value=datetime.strptime("17:00", "%H:%M").time()
            )
            days = st.multiselect(
                "Working weekdays (Monday = 0)", list(range(7)), default=[0, 1, 2, 3, 4]
            )
            holidays = st.text_input("Holiday dates, comma separated (YYYY-MM-DD)")
            response = st.number_input(
                "First-response target (working minutes)", min_value=1, max_value=10080, value=120
            )
            resolution = st.number_input(
                "Resolution target (working minutes)", min_value=1, max_value=10080, value=480
            )
            followup = st.number_input(
                "Follow-up target (working minutes)", min_value=1, max_value=10080, value=120
            )
            warning = st.number_input(
                "Reminder lead (working minutes)", min_value=1, max_value=480, value=30
            )
            pause = st.checkbox(
                "Permit resolution-clock pause while awaiting customer", value=False
            )
            publish = st.form_submit_button("Publish immutable policy version")
        if publish:
            config = {
                "timezone": zone,
                "opens_at": opens.isoformat(),
                "closes_at": closes.isoformat(),
                "weekdays": days,
                "holidays": [h.strip() for h in holidays.split(",") if h.strip()],
                "response_minutes": response,
                "resolution_minutes": resolution,
                "followup_minutes": followup,
                "warning_minutes": warning,
                "pause_on_customer": pause,
            }
            if request("POST", "/service-policies", json={"name": name, "configuration": config}):
                notice("Policy version published for future service cycles.")
