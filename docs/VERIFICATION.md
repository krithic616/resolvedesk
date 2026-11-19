# Milestone 1 verification

Verified on 19 November 2026 with Python 3.12.14. This records development evidence, not production performance.

## Passed

- Local SQLite suite: **20 passed, 1 skipped**. The skipped test requires PostgreSQL.
- PostgreSQL 17 suite in a non-root test container: **21 passed**. Includes simultaneous duplicate submissions (one 201, one 409) and UI-to-API interaction through Streamlit AppTest.
- Ruff lint and formatting checks.
- Python compilation of application and UI modules.
- Alembic upgrade and model/schema comparison on SQLite and PostgreSQL.
- Container image builds (test and runtime).
- Running local API: liveness and database readiness returned 200; unauthenticated case access returned 401.
- Running local Streamlit service health returned 200.

## Limits and follow-up

- The full Compose stack did not start: the cloud workspace ran out of disk while Docker created service containers. Temporary project images and the migration container were removed to recover space. Re-run the stack on a machine with sufficient disk before considering container deployment verified.
- The cloud proxy CA was supplied to Docker builds as an optional BuildKit secret (`build_ca`). TLS verification remained enabled. This is environment-specific and does not bundle a cloud certificate into the repository or runtime image.
- Starlette reports a deprecation warning about its HTTPX test transport; tests currently pass with the pinned versions.
- The test container reported an unwritable pytest cache directory; application tests passed. Test-image cache configuration was subsequently set to /tmp to prevent this warning on future builds; that Dockerfile-only adjustment has not been rebuilt after the disk-space failure.
- No throughput, production latency, FCR improvement, operational TAT improvement, or real customer outcome has been measured.
- Shared role keys are a demonstration mechanism, not individual bank employee authentication.
- GitHub repository creation was initially denied by the connected app (`Resource not accessible by integration (createRepository)`). The user created the repository, and milestone commit `6d91d86` was pushed to `main`.
- [GitHub Actions run 44482091040](https://github.com/krithic616/resolvedesk/actions/runs/44482091040) passed: lint, format, PostgreSQL migrations/schema comparison, all **21 tests**, and compilation.
- The user-created repository is public; generated local keys, database files, and the virtual environment are ignored. All tracked files were checked for the actual generated local credentials; none were present.

# Milestone 2 verification

Verified locally on 19 November 2026:

- SQLite suite: **40 passed, 2 skipped** (both skipped tests require PostgreSQL).
- Full UI answer-and-resolve scenario passed using Streamlit AppTest against the API.
- Existing case preservation passed through a milestone-1-to-milestone-2 migration on a disposable SQLite database.
- Ownership, manager review, unanswered questions, dependency states, outstanding commitments, stale versions, cross-case IDs, and auditor write denial are covered.
- Injected workflow audit failure rolled back both the question change and parent case version.
- A due time entered with the India offset was returned as its correct UTC equivalent.
- Ruff lint/format, application compilation, and Alembic schema comparison passed.

[GitHub Actions run 44508785024](https://github.com/krithic616/resolvedesk/actions/runs/44508785024) passed on PostgreSQL: **42 tests passed**, including simultaneous duplicate intake and competing workflow edits. Remote lint, format, migrations/schema comparison, and compilation also passed. Full multi-container startup remains unverified due to the earlier cloud disk-space limitation. No banking performance metrics or real customer outcomes are claimed.
