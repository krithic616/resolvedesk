"""Exercise the UI against the real API via its in-process test transport."""

import os
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from streamlit.testing.v1 import AppTest


def test_ui_case_intake_and_duplicate(client, monkeypatch):
    def transport(method, url, **kwargs):
        kwargs.pop("timeout", None)
        return client.request(method, urlsplit(url).path, **kwargs)

    monkeypatch.setattr(httpx, "request", transport)
    ui = AppTest.from_file(
        Path(__file__).resolve().parents[1] / "ui/app.py", default_timeout=15
    ).run()
    assert not ui.exception
    ui.sidebar.text_input[0].set_value(os.environ["AGENT_API_KEY"]).run()
    assert not ui.exception
    fields = {field.label: field for field in ui.text_input}
    fields["Unique email message ID"].set_value("ui-demo-001")
    fields["Synthetic customer reference"].set_value("SYN-UI-001")
    fields["Subject"].set_value("Explain my charge")
    ui.text_area[0].set_value("Please explain and review this synthetic fee.")
    ui.text_area[1].set_value("Why was the fee charged?\nCan it be waived?")
    next(b for b in ui.button if b.label == "Create case").click().run()
    assert not ui.exception
    assert len(ui.success) == 1
    assert ui.metric[0].value == "1"
    assert any(s.value == "Explain my charge" for s in ui.subheader)
    next(b for b in ui.button if b.label == "Create case").click().run()
    assert any("409" in e.value for e in ui.error)
    ui.sidebar.text_input[0].set_value(os.environ["AUDITOR_API_KEY"]).run()
    next(b for b in ui.button if b.label == "Create case").click().run()
    assert any("403" in e.value for e in ui.error)
    assert not ui.exception


def test_ui_answer_and_resolve_existing_case(client, payload, monkeypatch):
    from tests.conftest import auth
    from tests.test_workflow import working

    case = working(client, payload)

    def transport(method, url, **kwargs):
        kwargs.pop("timeout", None)
        return client.request(method, urlsplit(url).path, **kwargs)

    monkeypatch.setattr(httpx, "request", transport)
    ui = AppTest.from_file(
        Path(__file__).resolve().parents[1] / "ui/app.py", default_timeout=15
    ).run()
    ui.sidebar.text_input[0].set_value(os.environ["AGENT_API_KEY"]).run()
    for index in range(2):
        [w for w in ui.selectbox if w.label == "Question status"][index].set_value("answered")
        [w for w in ui.text_area if w.label == "Answer"][index].set_value(
            "Verified synthetic explanation."
        )
        [w for w in ui.text_input if w.label == "Evidence / policy reference"][index].set_value(
            "DEMO-001"
        )
        [w for w in ui.button if w.label == "Save question"][index].click().run()
        assert not ui.exception
    next(w for w in ui.text_area if w.label == "Resolution summary").set_value(
        "All synthetic questions addressed."
    )
    next(w for w in ui.button if w.label == "Resolve case").click().run()
    assert not ui.exception
    saved = client.get(f"/cases/{case['id']}", headers=auth()).json()
    assert saved["status"] == "resolved"
    assert any(w.label == "Reopen case" for w in ui.button)


def test_ui_nfcr_create_and_complete(client, payload, monkeypatch):
    from tests.conftest import auth
    from tests.test_workflow import working

    case = working(client, payload)

    def transport(method, url, **kwargs):
        kwargs.pop("timeout", None)
        return client.request(method, urlsplit(url).path, **kwargs)

    monkeypatch.setattr(httpx, "request", transport)
    ui = AppTest.from_file(
        Path(__file__).resolve().parents[1] / "ui/app.py", default_timeout=15
    ).run()
    ui.sidebar.text_input[0].set_value(os.environ["AGENT_API_KEY"]).run()
    next(w for w in ui.text_area if w.label == "What input is needed from the unit?").set_value(
        "Obtain synthetic fee details"
    )
    next(w for w in ui.text_input if w.label == "Next follow-up action").set_value(
        "Contact charges team"
    )
    next(w for w in ui.button if w.label == "Create NFCR task").click().run()
    assert not ui.exception
    data = client.get(f"/cases/{case['id']}/service", headers=auth()).json()
    assert len(data["followups"]) == 1
    task_id = data["followups"][0]["id"]
    next(w for w in ui.text_input if w.label == "Business-unit completion evidence").set_value(
        "Synthetic unit response received"
    )
    next(w for w in ui.button if w.label == f"Complete NFCR task #{task_id}").click().run()
    assert not ui.exception
    assert client.get(f"/cases/{case['id']}/service", headers=auth()).json()["followups"][0][
        "completed_at"
    ]
