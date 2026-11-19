"""Streamlit client; all permissions and writes remain in the API."""

import os

import httpx
import streamlit as st

from ui.service_ui import render_operations, render_policies, render_service
from ui.workflow_ui import render_workflow

st.set_page_config(page_title="ResolveDesk", page_icon="✉", layout="wide")
st.title("ResolveDesk")
st.caption("Banking email resolution workbench • Synthetic data only • Milestone 3")
api_url = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
key = st.sidebar.text_input("Demo API key", type="password")
st.sidebar.caption(
    "Use a key from your local .env file. Auditors can view cases; "
    "agents and managers can create them."
)


def request(method, path, **kwargs):
    try:
        response = httpx.request(
            method,
            f"{api_url}{path}",
            headers={"Authorization": f"Bearer {key}"},
            timeout=15,
            **kwargs,
        )
    except httpx.RequestError:
        st.error("Cannot reach the API. Check that it is running.")
        return None
    if response.is_error:
        try:
            detail = response.json().get("detail", "Request failed")
        except ValueError:
            detail = "Request failed"
        st.error(f"{response.status_code}: {detail}")
        return None
    return response.json()


if not key:
    st.info("Enter your demo API key in the sidebar to begin.")
    st.stop()
identity = request("GET", "/session")
if not identity:
    st.stop()
notice = st.session_state.pop("workflow_notice", None)
if notice:
    st.success(notice)
queue, intake, operations, policies = st.tabs(
    ["Case queue", "Create case", "Deadline alerts", "Service policies"]
)
with intake:
    with st.form("intake", clear_on_submit=False):
        source = st.text_input("Unique email message ID", placeholder="demo-email-001")
        customer = st.text_input("Synthetic customer reference", placeholder="SYN-001")
        subject = st.text_input("Subject")
        body = st.text_area("Customer email")
        category = st.selectbox(
            "Category", ["charges", "cards", "account_service", "payments", "other"]
        )
        questions = st.text_area("Customer questions — one per line")
        submitted = st.form_submit_button("Create case")
    if submitted:
        result = request(
            "POST",
            "/cases",
            json={
                "source_message_id": source,
                "customer_reference": customer,
                "subject": subject,
                "body": body,
                "category": category,
                "questions": [q for q in questions.splitlines() if q.strip()],
            },
        )
        if result:
            st.success(f"Case created: {result['id']}. Refresh the queue to see it.")
with queue:
    st.button("Refresh queue")
    page = st.number_input("Page", min_value=1, value=1, step=1)
    data = request("GET", "/cases", params={"limit": 25, "offset": (page - 1) * 25})
    if data:
        st.metric("Total cases", data["total"])
        st.dataframe(data["items"], use_container_width=True, hide_index=True)
        if data["items"]:
            choices = {item["id"]: item["subject"] for item in data["items"]}
            selected = st.selectbox(
                "Open case", choices, format_func=lambda x: f"{choices[x]} ({x[:8]})"
            )
            case = request("GET", f"/cases/{selected}")
            if case:
                st.subheader(case["subject"])
                st.write(f"Customer: {case['customer_reference']} | Status: {case['status']}")
                st.text(case["body"])
                st.markdown("**Query checklist**")
                for query in case["queries"]:
                    st.write(f"• {query['question']}")
                render_service(case, request, identity["role"])
                render_workflow(case, request, identity["role"])
                st.markdown("**Audit history**")
                events = request("GET", f"/cases/{selected}/audit")
                if events is not None:
                    st.dataframe(events, hide_index=True)

with operations:
    render_operations(request, identity["role"])
with policies:
    render_policies(request, identity["role"])
