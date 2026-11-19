"""Verify upgrades preserve a milestone-1 customer's existing case and audit history."""

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, text


def test_upgrade_preserves_existing_case(tmp_path):
    url = "sqlite:///" + (tmp_path / "legacy.db").as_posix()
    env = os.environ | {"DATABASE_URL": url}
    root = Path(__file__).resolve().parents[1]

    def migrate(target):
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", target],
            cwd=root,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )

    migrate("6dfc89ab9882")
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(
            text("""INSERT INTO cases
            (id, source_message_id, customer_reference, subject, body, category, status, created_at)
            VALUES ('legacy', 'legacy-mail', 'SYN-001', 'Existing case', 'Existing body',
                    'charges', 'new', '2026-11-19 00:00:00')""")
        )
        conn.execute(
            text("""INSERT INTO query_items (case_id, position, question)
                             VALUES ('legacy', 0, 'Existing question?')""")
        )
        conn.execute(
            text("""INSERT INTO audit_events (case_id, actor, action, created_at)
                             VALUES ('legacy', 'demo-agent', 'case.created',
                                     '2026-11-19 00:00:00')""")
        )
    migrate("head")
    with engine.connect() as conn:
        row = conn.execute(text("SELECT version, owner, body FROM cases")).one()
        assert tuple(row) == (1, None, "Existing body")
        assert conn.execute(text("SELECT disposition FROM query_items")).scalar() == "open"
        assert conn.execute(text("SELECT details FROM audit_events")).scalar() == "{}"
    subprocess.run(
        [sys.executable, "-m", "alembic", "check"],
        cwd=root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM service_clocks")).scalar() == 0
        assert conn.execute(text("SELECT COUNT(*) FROM deadline_alerts")).scalar() == 0
    engine.dispose()
