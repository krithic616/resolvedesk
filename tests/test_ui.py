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
