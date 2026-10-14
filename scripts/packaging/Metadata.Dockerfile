# Engineering prerequisite only: metadata API library, no production entrypoint.
FROM --platform=linux/amd64 python:3.12.13-slim-bookworm@sha256:4766d8b510c428e595d74b9cc5bbb2fae8e26316fffb4adc89908d79aacd58a2 AS dependencies
WORKDIR /opt/emailmonitor
COPY metadata-api/pyproject.toml metadata-api/uv.lock ./
RUN python -m pip install --no-cache-dir uv==0.12.23 && uv sync --locked --no-dev

FROM --platform=linux/amd64 python:3.12.13-slim-bookworm@sha256:4766d8b510c428e595d74b9cc5bbb2fae8e26316fffb4adc89908d79aacd58a2
WORKDIR /opt/emailmonitor
COPY --from=dependencies /opt/emailmonitor/.venv ./.venv
COPY metadata-api/src ./src
COPY manifest.json ./manifest.json
COPY notices ./notices
ENV PATH="/opt/emailmonitor/.venv/bin:$PATH" PYTHONPATH="/opt/emailmonitor/src" PYTHONDONTWRITEBYTECODE=1
USER 65532:65532
CMD ["python", "-c", "print('metadata-only-offline-prerequisite; working_extraction_service=false; production_ready=false')"]
