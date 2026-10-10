import httpx
import pytest
from emailmonitor.api import Capabilities, create_app
from emailmonitor.config import Settings
from pydantic import ValidationError


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_public_metadata_is_truthful() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(Settings())), base_url="http://test"
    ) as client:
        assert (await client.get("/healthz")).json() == {"status": "ok"}
        assert (await client.get("/api/v1/capabilities")).json() == Capabilities().model_dump()
        spec = (await client.get("/openapi.json")).json()
        assert set(spec["paths"]) == {"/healthz", "/api/v1/capabilities"}
        assert spec["components"]["schemas"]["Capabilities"] == Capabilities.model_json_schema()


@pytest.mark.anyio
@pytest.mark.parametrize("tenant", ["tenant-a", "tenant-b"])
async def test_forged_tenant_cannot_enable_unimplemented_api(tenant: str) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/jobs", headers={"X-Organization-ID": tenant}, json={"organization_id": tenant}
        )
        assert response.status_code == 404


@pytest.mark.parametrize("environment", ["production", "development"])
@pytest.mark.parametrize("mode", ["fixture_mode", "identity_stub"])
def test_production_and_development_reject_test_modes(environment: str, mode: str) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({"environment": environment, mode: True})


@pytest.mark.parametrize(
    "flag",
    [
        "live_sources_enabled",
        "outbound_email_enabled",
        "external_ai_enabled",
        "wider_web_enabled",
        "ocr_enabled",
    ],
)
def test_unimplemented_outbound_features_are_rejected(flag: str) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({"environment": "test", flag: True})


def test_configuration_rejects_unknown_and_ambiguous_values() -> None:
    for env in (
        {"EMAILMONITOR_ALLOW_PRIVATE_URLS": "true"},
        {"EMAILMONITOR_FIXTURE_MODE": "1"},
        {"EMAILMONITOR_ENVIRONMENT": "prod"},
    ):
        with pytest.raises(ValueError):
            Settings.from_environment(env)
    assert Settings.from_environment({}).environment == "production"
    assert Settings.from_environment(
        {"EMAILMONITOR_ENVIRONMENT": "test", "EMAILMONITOR_FIXTURE_MODE": "true"}
    ).fixture_mode


@pytest.mark.parametrize("mode", ["FIXTURE_MODE", "IDENTITY_STUB"])
def test_actual_production_entrypoint_refuses_test_environment_switches(mode: str) -> None:
    import os
    import subprocess
    import sys
    from pathlib import Path

    env = {key: value for key, value in os.environ.items() if not key.startswith("EMAILMONITOR_")}
    env.update(
        {
            "EMAILMONITOR_ENVIRONMENT": "production",
            f"EMAILMONITOR_{mode}": "true",
            "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", "from emailmonitor.api import app"],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode != 0
    assert "require the test environment" in result.stderr
