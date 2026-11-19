FROM python:3.12-slim AS base
WORKDIR /app
COPY requirements.txt .
RUN --mount=type=secret,id=build_ca \
    if [ -f /run/secrets/build_ca ]; then export PIP_CERT=/run/secrets/build_ca; fi; \
    pip install --no-cache-dir -r requirements.txt && useradd --create-home appuser
COPY --chown=appuser:appuser . .

FROM base AS test
ENV PYTEST_ADDOPTS="-o cache_dir=/tmp/pytest-cache"
RUN --mount=type=secret,id=build_ca \
    if [ -f /run/secrets/build_ca ]; then export PIP_CERT=/run/secrets/build_ca; fi; \
    pip install --no-cache-dir -r requirements-dev.txt
USER appuser
CMD ["pytest", "-q"]

FROM base AS runtime
USER appuser
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
