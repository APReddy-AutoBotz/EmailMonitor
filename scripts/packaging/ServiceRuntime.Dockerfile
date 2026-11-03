# Authored-source reference runtime. No credentials/grants or migrations at startup.
FROM --platform=linux/amd64 python:3.12.13-slim-bookworm@sha256:4766d8b510c428e595d74b9cc5bbb2fae8e26316fffb4adc89908d79aacd58a2 AS dependencies
WORKDIR /opt/emailmonitor/services/backend
COPY services/backend/pyproject.toml services/backend/uv.lock ./
RUN python -m pip install --no-cache-dir uv==0.12.23 && uv sync --locked --no-dev

FROM --platform=linux/amd64 python:3.12.13-slim-bookworm@sha256:4766d8b510c428e595d74b9cc5bbb2fae8e26316fffb4adc89908d79aacd58a2
WORKDIR /opt/emailmonitor
COPY --from=dependencies /opt/emailmonitor/services/backend/.venv ./services/backend/.venv
COPY services/backend/src ./services/backend/src
COPY fixtures ./fixtures
COPY contracts ./contracts
COPY static-web ./static-web
COPY manifest.json ./manifest.json
COPY notices ./notices
ENV PATH="/opt/emailmonitor/services/backend/.venv/bin:$PATH" PYTHONPATH="/opt/emailmonitor/services/backend/src" PYTHONDONTWRITEBYTECODE=1
USER 65532:65532
ENTRYPOINT ["python", "-m", "emailmonitor.runtime.entrypoint"]
CMD ["--help"]
