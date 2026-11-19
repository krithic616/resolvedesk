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
- GitHub repository creation was denied by the connected app (`Resource not accessible by integration (createRepository)`). Remote publishing awaits an empty repository owned by the user. CI is configured but has not run remotely.
