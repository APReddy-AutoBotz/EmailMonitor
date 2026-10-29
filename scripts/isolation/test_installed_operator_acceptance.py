"""Required disposable CI: materialized service CLI, HTTPS login and built operator UI.

Missing SQL/broker infrastructure is an explicit local skip. Enabling the required
CI marker makes missing prerequisites fail. Nothing here provisions a live system.
"""

import hashlib
import io
import json
import os
import signal
import socket
import ssl
import subprocess
import sys
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import partial
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4
from zipfile import ZipFile

import httpx
import pytest
from emailmonitor.runtime.api_entrypoint import ReferenceAPI, ReferenceIdentity
from emailmonitor.runtime.authority import ServiceProcess
from emailmonitor.runtime.delegation import ServiceBinding, ServiceBindings
from emailmonitor.runtime.worker import ServiceRuntimeConfig, broker_application
from installed_operator_issuer import synthetic_issuer
from installed_operator_relay import application
from installed_operator_stage import InstalledStage, report_stage
from operator_ui_protocol import asset_manifest
from run_installed_operator import run_installed
from service_artifacts import (
    collect_service,
    tracked_service_sources,
    verify_service_archive,
)
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from test_admission_broker import close_owned
from test_real_broker_jobs import wait_for
from test_runtime_publisher_broker import declare_owned
from test_tenant_foundation import Scenario
from test_tenant_foundation import scenario as scenario

from artifacts import archive, materialize
from run_acceptance import runtime_versions

ROOT = Path(__file__).resolve().parents[2]
REQUIRED = (
    "EM_TEST_ADMIN_DATABASE_URL",
    "EM_TEST_DATABASE_URL",
    "EM_TEST_AUTH_DATABASE_URL",
    "EM_TEST_BROKER_URL",
)


def require_installed_ci(environment: dict[str, str]) -> None:
    missing = [key for key in REQUIRED if not environment.get(key)]
    if missing:
        if environment.get("EM_REQUIRE_INSTALLED_OPERATOR") == "true":
            pytest.fail("Required installed operator SQL/broker prerequisites unavailable")
        pytest.skip("Installed operator acceptance needs disposable PostgreSQL and RabbitMQ")
    expected = {
        "EM_TEST_ADMIN_DATABASE_URL": (
            "postgresql+pg8000://postgres:emailmonitor-ci-only@127.0.0.1:5432/postgres"
        ),
        "EM_TEST_DATABASE_URL": (
            "postgresql+pg8000://em_ci_runtime:emailmonitor-ci-runtime-only@127.0.0.1:5432/postgres"
        ),
        "EM_TEST_AUTH_DATABASE_URL": (
            "postgresql+pg8000://em_ci_authenticator:emailmonitor-ci-auth-only@127.0.0.1:5432/postgres"
        ),
        "EM_TEST_BROKER_URL": ("pyamqp://em_fixture:emailmonitor-ci-broker-only@127.0.0.1:5672//"),
    }
    if any(environment.get(key) != value for key, value in expected.items()):
        raise RuntimeError("Exact existing disposable operator CI services required")
    if (
        environment.get("GITHUB_ACTIONS") != "true"
        or environment.get("EM_REQUIRE_OPERATOR_UI") != "true"
        or environment.get("EM_TEST_DISPOSABLE_BROKER") != "true"
        or environment.get("EM_REQUIRE_INSTALLED_OPERATOR") != "true"
    ):
        raise RuntimeError("Explicit reviewed installed operator CI only")


@pytest.fixture
def installed_scenario(request: pytest.FixtureRequest) -> Scenario:
    # Gate before resolving the SQL fixture, not after its mutating setup.
    require_installed_ci(dict(os.environ))
    value: Scenario = request.getfixturevalue("scenario")
    return value


def config_file(directory: Path, value: str) -> Path:
    path = directory / (uuid4().hex + ".json")
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as output:
        output.write(value)
    return path


def command(installed: Path, action: str, config: Path) -> list[str]:
    # -I ignores user site/PYTHONPATH; only the materialized package is inserted.
    # run_module is the standard -m path, with the actual production CLI unchanged.
    return [
        sys.executable,
        "-I",
        "-B",
        "-c",
        "import runpy,sys;sys.path.insert(0,sys.argv.pop(1));"
        "runpy.run_module('emailmonitor.runtime.entrypoint',run_name='__main__')",
        str(installed / "services/backend/src"),
        action,
        "--config",
        str(config),
    ]


def process_environment() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("EM_", "EMAILMONITOR_", "CELERY_", "PYTHON"))
        and key
        not in {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"}
    }


def report_cleanup(errors: list[str], primary: BaseException | None) -> None:
    if not errors:
        return
    message = "Installed operator cleanup failed: " + ",".join(errors)
    if primary is not None:
        BaseException.add_note(primary, message)
    else:
        raise RuntimeError(message) from None


def stop_process(
    running: subprocess.Popen[bytes],
    primary: BaseException | None,
    action: Literal["api", "worker"],
) -> None:
    errors: list[str] = []
    terminated = False
    status: int | None = None

    def attempt(category: str, work: Callable[[], object]) -> None:
        try:
            work()
        except BaseException:
            errors.append(category)

    try:
        status = running.poll()
        active = status is None
    except BaseException:
        errors.append("process-poll")
        active = True
    if active:
        try:
            running.terminate()
            terminated = True
        except BaseException:
            errors.append("process-terminate")
        try:
            status = running.wait(timeout=5)
        except subprocess.TimeoutExpired:
            # Always kill and reap this owned process, but a normal restart must
            # never count a forced shutdown as successful graceful lifecycle proof.
            errors.append(
                "worker-process-forced-kill" if action == "worker" else "api-process-forced-kill"
            )
            attempt("process-kill", running.kill)
            attempt("process-reap", lambda: running.wait(timeout=5))
        except BaseException:
            errors.append("process-wait")
            attempt("process-kill", running.kill)
            attempt("process-reap", lambda: running.wait(timeout=5))
    if status not in (None, 0):
        # Pinned Uvicorn 0.54.0 capture_signals explicitly re-raises its captured
        # signal after graceful shutdown. Only accept that API-specific result
        # following our own successful SIGTERM, never an already-exited process.
        # Celery's default warm SIGTERM shutdown must exit EX_OK (zero).
        replayed_api_signal = action == "api" and terminated and status == -signal.SIGTERM
        if not replayed_api_signal:
            errors.append("process-exit-status")
    report_cleanup(errors, primary)


@contextmanager
def process(
    installed: Path, action: Literal["api", "worker"], config: Path
) -> Iterator[subprocess.Popen[bytes]]:
    running = subprocess.Popen(
        command(installed, action, config),
        cwd=installed,
        env=process_environment(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    primary: BaseException | None = None
    try:
        yield running
    except BaseException as error:
        primary = error
        raise
    finally:
        stop_process(running, primary, action)


@contextmanager
def api_process_client(
    installed: Path, config: Path, context: ssl.SSLContext
) -> Iterator[tuple[subprocess.Popen[bytes], httpx.Client]]:
    # The readiness client owns persistent TLS connections. Close it before
    # SIGTERM so Uvicorn can finish its connection drain within the same bound.
    with (
        process(installed, "api", config) as running,
        httpx.Client(verify=context, trust_env=False, timeout=2) as client,
    ):
        yield running, client


def cleanup_resources(
    stop: threading.Event,
    publisher_thread: threading.Thread | None,
    app: Any,
    admin: Engine,
    org: UUID,
    principals: dict[str, UUID],
    names: dict[str, str],
    configs: dict[str, Path],
    primary: BaseException | None,
) -> None:
    """Attempt every exact owned cleanup even after an earlier cleanup failure."""
    errors: list[str] = []

    def attempt(category: str, action: Callable[[], object]) -> None:
        try:
            action()
        except BaseException:
            errors.append(category)

    def join_publisher() -> None:
        if publisher_thread is not None and publisher_thread.ident is not None:
            publisher_thread.join(timeout=25)
            if publisher_thread.is_alive():
                raise RuntimeError("Owned publisher did not stop")

    def execute(statement: str, parameters: dict[str, object]) -> None:
        # A failed statement rolls back only this step, not subsequent principals
        # or roles. All names/identifiers are the exact generated fixture resources.
        with admin.begin() as connection:
            connection.execute(text(statement), parameters)

    attempt("publisher-stop", stop.set)
    attempt("publisher-join", join_publisher)
    if app is not None:
        attempt("broker-owned-queues", lambda: close_owned(app, "em-fixture-" + org.hex))
        # close_owned can fail before closing its borrowed application.
        attempt("broker-application", app.close)
    for kind, principal in principals.items():
        for table in ("admission_requests", "source_resource_requests"):
            attempt(
                kind + "-" + table,
                partial(
                    execute,
                    f"DELETE FROM emailmonitor.{table} WHERE service_delegation IN "
                    "(SELECT id FROM emailmonitor.service_delegations WHERE principal_id=:id)",
                    {"id": principal},
                ),
            )
        for table in ("service_audit", "service_delegations"):
            attempt(
                kind + "-" + table,
                partial(
                    execute,
                    f"DELETE FROM emailmonitor.{table} WHERE principal_id=:id",
                    {"id": principal},
                ),
            )
        attempt(
            kind + "-principal",
            partial(
                execute,
                "DELETE FROM emailmonitor.service_principals WHERE id=:id",
                {"id": principal},
            ),
        )
    for kind, name in names.items():
        attempt(kind + "-role", partial(execute, f"DROP ROLE IF EXISTS {name}", {}))
    attempt("admin-dispose", admin.dispose)
    for kind, path in configs.items():
        attempt(kind + "-config", partial(path.unlink, missing_ok=True))
    report_cleanup(errors, primary)


def finite(installed: Path, action: str, config: Path) -> str:
    result = subprocess.run(
        command(installed, action, config),
        cwd=installed,
        env=process_environment(),
        capture_output=True,
        timeout=20,
        check=False,
    )
    if result.returncode != 0 or len(result.stdout) > 1024 or len(result.stderr) > 1024:
        raise RuntimeError("Installed finite service command failed")
    return result.stdout.decode().strip()


def installed_package(directory: Path) -> tuple[Path, dict[str, str], str]:
    # No dirty-tree evidence can be attributed to a clean commit's tree identifier.
    subprocess.run(
        ["git", "diff", "--exit-code", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        check=True,
        timeout=10,
    )
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        check=True,
        timeout=10,
    )
    if untracked.stdout:
        raise RuntimeError("Committed exact-tree installed acceptance required")
    tree = subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    ).stdout.strip()
    requirements = subprocess.run(
        [
            "uv",
            "export",
            "--project",
            "services/backend",
            "--locked",
            "--no-dev",
            "--no-emit-project",
            "--no-hashes",
            "--no-header",
            "--no-annotate",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    ).stdout
    files = collect_service(
        ROOT, tree, runtime_versions(requirements), tracked_service_sources(ROOT, tree)
    )
    receipt = files["manifest.json"]
    payload = archive(files)
    verified = verify_service_archive(payload, receipt)
    installed = directory / "installed-service"
    materialize(verified, installed)
    assets = asset_manifest(installed / "static-web")
    assert assets == asset_manifest(ROOT / "apps/web/dist")
    assert not any(name.endswith((".key", ".pem", ".env")) for name in verified)
    return installed, assets, hashlib.sha256(payload).hexdigest()


def test_required_installed_https_operator_journey(
    installed_scenario: Scenario,
    tmp_path: Path,
) -> None:
    stage = InstalledStage()
    primary: BaseException | None = None
    try:
        installed_journey(installed_scenario, tmp_path, stage)
    except BaseException as error:
        primary = error
        stage.fail()
        raise
    finally:
        if os.environ.get("EM_INSTALLED_STAGE_REPORT") == "true":
            try:
                report_stage(stage, Path(os.environ["GITHUB_OUTPUT"]))
            except Exception:
                if primary is None:
                    raise
                primary.add_note("Fixed installed stage reporting failed")


def test_required_installed_retained_reuse_journey(
    installed_scenario: Scenario, tmp_path: Path
) -> None:
    stage = InstalledStage()
    try:
        installed_journey(installed_scenario, tmp_path, stage, retained_reuse=True)
    except BaseException:
        stage.fail()
        raise


def installed_journey(
    case: Scenario, tmp_path: Path, stage: InstalledStage, *, retained_reuse: bool = False
) -> None:
    stage.enter("package")
    installed, assets, package_sha = installed_package(tmp_path)
    org, other = case.organizations
    admin = create_engine(case.admin_url, hide_parameters=True)
    principals = {kind: uuid4() for kind in ("worker", "publisher")}
    names = {kind: "em_installed_" + uuid4().hex for kind in principals}
    configs: dict[str, Path] = {}
    app: Any = None
    stop, release = threading.Event(), threading.Event()
    errors: list[str] = []
    expiry_observed = False
    publication_passes = 0
    downloads: list[bytes] = []
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
    origin = f"https://127.0.0.1:{port}"
    publisher_thread: threading.Thread | None = None
    primary: BaseException | None = None
    try:
        stage.enter("identity_and_roles")
        with synthetic_issuer(
            tmp_path, origin + "/auth/complete", str(case.identities["owner"])
        ) as identity:
            with admin.begin() as connection:
                connection.execute(
                    text("UPDATE emailmonitor.identities SET issuer=:issuer WHERE id=:id"),
                    {"issuer": identity.origin, "id": case.identities["owner"]},
                )
                connection.execute(
                    text(
                        "INSERT INTO emailmonitor.memberships VALUES(:org,:id,'viewer','active',1)"
                    ),
                    {"org": other, "id": case.identities["owner"]},
                )
                for kind, name in names.items():
                    connection.exec_driver_sql(
                        f"CREATE ROLE {name} LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD "
                        f"'authored-disposable-service-only'"
                    )
                    connection.exec_driver_sql(f"GRANT emailmonitor_{kind} TO {name}")
                    connection.execute(
                        text(
                            "INSERT INTO emailmonitor.service_principals "
                            "(id,organization_id,login_oid,login_name,kind,active) "
                            "SELECT :id,:org,oid,rolname,:kind,true FROM pg_roles WHERE "
                            "rolname=:name"
                        ),
                        {"id": principals[kind], "org": org, "kind": kind, "name": name},
                    )
            stage.enter("configuration")
            runtime_configs = {}
            for kind, name in names.items():
                runtime_configs[kind] = ServiceRuntimeConfig(
                    environment="test",
                    database_url=make_url(case.admin_url)
                    .set(username=name, password="authored-disposable-service-only")
                    .render_as_string(hide_password=False),
                    broker_url=os.environ["EM_TEST_BROKER_URL"],
                    organization=org,
                    queue="em-fixture-" + org.hex,
                    process=ServiceProcess(kind=kind, principal=principals[kind]),  # type: ignore[arg-type]
                    lease_seconds=30 if kind == "worker" else 5,
                )
                configs[kind] = config_file(tmp_path, runtime_configs[kind].model_dump_json())
            configuration = ReferenceAPI(
                environment="test",
                runtime_database_url=os.environ["EM_TEST_DATABASE_URL"],
                authentication_database_url=os.environ["EM_TEST_AUTH_DATABASE_URL"],
                bindings=ServiceBindings(
                    tenants=(
                        ServiceBinding(
                            organization=org,
                            worker=principals["worker"],
                            publisher=principals["publisher"],
                        ),
                    )
                ),
                identity=ReferenceIdentity(
                    issuer=identity.origin,
                    client_id="installed-operator-test",
                    authorization_endpoint=identity.origin + "/authorize",
                    token_endpoint=identity.origin + "/token",
                    redirect_uri=origin + "/auth/complete",
                    verification_keys={"ephemeral": identity.public_key},
                    certificate_authority=identity.ca,
                ),
                port=port,
                certificate=identity.ca,
                private_key=identity.key,
            )
            configs["api"] = config_file(tmp_path, configuration.model_dump_json())
            stage.enter("service_identity")
            for kind in ("worker", "publisher"):
                assert finite(installed, "check", configs[kind]) == "service_identity_ready"
            stage.enter("broker_setup")
            app = broker_application(runtime_configs["publisher"])
            declare_owned(app, runtime_configs["publisher"].queue)
            context = ssl.create_default_context(cafile=str(identity.ca))
            stage.enter("api_startup")
            with api_process_client(installed, configs["api"], context) as (api_process, client):

                def api_ready(running: subprocess.Popen[bytes]) -> bool:
                    assert running.poll() is None, "Installed API exited before readiness"
                    try:
                        response = client.get(origin + "/readyz")
                        return response.status_code == 200 and response.json() == {
                            "api_dependencies_ready": True
                        }
                    except httpx.TransportError:
                        return False

                def worker_ready(running: subprocess.Popen[bytes]) -> bool:
                    from emailmonitor.jobs.queues import owned_queues

                    assert running.poll() is None, "Installed worker exited before readiness"
                    with app.connection_for_read() as connection:
                        channel = connection.channel()
                        try:
                            return all(
                                channel.queue_declare(queue=name, passive=True).consumer_count == 1
                                for name in owned_queues(runtime_configs["worker"].queue)
                            )
                        finally:
                            channel.close()

                def scalar(statement: str) -> Any:
                    with admin.connect() as connection:
                        return connection.execute(
                            text(statement), {"org": org, "id": case.identities["owner"]}
                        ).scalar_one()

                def publish() -> None:
                    nonlocal publication_passes
                    while not stop.wait(0.2):
                        if not release.is_set():
                            continue
                        try:
                            output = finite(installed, "publish-once", configs["publisher"])
                            if not output.startswith("published=") or not output[10:].isdigit():
                                raise RuntimeError("Bounded installed publication receipt missing")
                            publication_passes += 1
                        except Exception as error:
                            errors.append(type(error).__name__)
                            stop.set()

                def control(action: str) -> None:
                    nonlocal expiry_observed
                    if errors:
                        raise RuntimeError("Independent installed publisher failed")
                    if action == "publish":
                        assert not release.is_set()
                        assert (
                            scalar(
                                "SELECT count(*) FROM emailmonitor.service_delegations WHERE "
                                "organization_id=:org"
                            )
                            == 2
                        )
                        with admin.begin() as connection:
                            changed = connection.execute(
                                text(
                                    "UPDATE emailmonitor.sessions SET "
                                    "expires_at=clock_timestamp()+interval '500 milliseconds' "
                                    "WHERE identity_id=:id AND revoked_at IS NULL AND "
                                    "expires_at>clock_timestamp() RETURNING token_hash"
                                ),
                                {"id": case.identities["owner"]},
                            ).all()
                            assert len(changed) == 1
                        wait_for(
                            lambda: (
                                scalar(
                                    "SELECT count(*) FROM emailmonitor.sessions WHERE "
                                    "identity_id=:id "
                                    "AND revoked_at IS NULL AND expires_at<=clock_timestamp()"
                                )
                                == 1
                            ),
                            seconds=3,
                        )
                        expiry_observed = True
                        release.set()
                    elif action == "wait_jobs":
                        assert (
                            scalar(
                                "SELECT count(*) FROM emailmonitor.jobs WHERE "
                                "organization_id=:org AND state='completed_partial'"
                            )
                            == 1
                        )
                    elif action == "wait_exports":
                        assert (
                            scalar(
                                "SELECT count(*) FROM emailmonitor.exports WHERE "
                                "organization_id=:org AND state='ready'"
                            )
                            == 2
                        )
                    else:
                        raise RuntimeError("Unexpected installed operator control")

                stage.enter("api_readiness")
                wait_for(lambda: api_ready(api_process), seconds=10)
                stage.enter("profile_and_session")
                profile = client.get(origin + "/api/v1/runtime-profile").json()
                assert profile["production_ready"] is False
                assert all(
                    profile[key] is False
                    for key in (
                        "xml_available",
                        "pdf_available",
                        "dynamic_browser_available",
                        "live_sources_available",
                    )
                )
                assert (
                    client.get(
                        origin + "/api/v1/auth/session",
                        headers={"X-EmailMonitor-UI": "session"},
                    ).status_code
                    == 401
                )
                # Deliberately an empty-process restart, not a crash/lease recovery claim.
                stage.enter("first_worker_readiness_and_stop")
                with process(installed, "worker", configs["worker"]) as first:
                    wait_for(lambda: worker_ready(first), seconds=10)
                stage.enter("restarted_worker_readiness")
                with process(installed, "worker", configs["worker"]) as running:
                    wait_for(lambda: worker_ready(running), seconds=10)
                    publisher_thread = threading.Thread(target=publish, daemon=True)
                    publisher_thread.start()
                    setup: dict[str, object] = {
                        "kind": "bootstrap",
                        "origin": "https://app.example.test",
                        "api": origin,
                        "issuer": identity.origin,
                        "assets": assets,
                        "asset_sizes": {
                            name: (installed / "static-web" / name).stat().st_size
                            for name in assets
                        },
                        "initial_organization": str(org),
                        "other_organization": str(other),
                    }
                    if retained_reuse:
                        setup["retained_reuse"] = True
                    stage.enter("browser_execution_and_owned_cleanup")
                    evidence = run_installed(
                        application(origin, identity.origin, identity.ca, assets, downloads),
                        setup,
                        control,
                        lambda _: False,
                    )
                    stage.enter("postconditions")
                    assert evidence["redirect_navigation"] == (
                        "observed_303_failed_target_explicit_navigation"
                    )
                    assert evidence["server_redirects"] == 4
                    assert evidence["explicit_redirect_navigations"] == 4
                    assert api_ready(api_process) and running.poll() is None and not errors
                    assert expiry_observed and publication_passes > 0
                    assert (
                        identity.authorizations == identity.exchanges == 2
                        and identity.refusals == 0
                    )
                    assert scalar(
                        "SELECT count(*) FROM emailmonitor.execution_effects WHERE "
                        "organization_id=:org"
                    ) == (6 if retained_reuse else 5)
                    assert (
                        scalar(
                            "SELECT count(*) FROM emailmonitor.association_reviews WHERE "
                            "organization_id=:org"
                        )
                        == 1
                    )
                    assert scalar(
                        "SELECT count(*) FROM emailmonitor.service_delegations WHERE "
                        "organization_id=:org AND revoked_at IS NULL"
                    ) == (10 if retained_reuse else 8)
                    assert (
                        scalar(
                            "SELECT count(*) FROM emailmonitor.sessions WHERE "
                            "identity_id=:id AND expires_at<=clock_timestamp() AND "
                            "revoked_at IS NULL"
                        )
                        == 1
                    )
                    assert (
                        scalar(
                            "SELECT count(*) FROM emailmonitor.jobs j "
                            "JOIN emailmonitor.execution_items i "
                            "ON i.organization_id=j.organization_id AND i.job_id=j.id "
                            "WHERE j.organization_id=:org AND j.state='completed' "
                            "AND j.request->'input'->>'type'='url' "
                            "AND j.request->'input'->>'url'="
                            "'https://synthetic.publisher.example/no-contact.html' "
                            "AND i.state='no_contact'"
                        )
                        == 1
                    )
                    assert len(downloads) == 2
                    if retained_reuse:
                        assert (
                            scalar(
                                "SELECT count(*) FROM emailmonitor.article_observations a "
                                "JOIN emailmonitor.jobs j ON j.organization_id=a.organization_id "
                                "AND j.id=a.job_id WHERE a.organization_id=:org "
                                "AND a.reused_from_job IS NOT NULL AND j.state='completed'"
                            )
                            == 1
                        )
                    with ZipFile(io.BytesIO(downloads[0])) as archive_file:
                        assert b"example.org" in archive_file.read("xl/worksheets/sheet1.xml")
                    assert b"example.org" in downloads[1] and not downloads[1].startswith(b"PK")
                    print(
                        json.dumps(
                            {
                                **evidence,
                                "package_sha256": package_sha,
                                "installed_api_ready": True,
                                "independent_installed_worker": True,
                                "independent_installed_publisher": True,
                                "empty_worker_restart": True,
                                "session_expiry": (
                                    "shortened_future_deadline_elapsed_without_revocation"
                                ),
                                "sse_transport": (
                                    "actual_https_frames_bounded_disconnect_buffered"
                                ),
                                "export_sha256": [
                                    hashlib.sha256(body).hexdigest() for body in downloads
                                ],
                                "production_ready": False,
                            },
                            sort_keys=True,
                        )
                    )
                    stage.enter("publisher_stop")
                    stop.set()
                    publisher_thread.join(timeout=25)
                    assert not publisher_thread.is_alive()
                    stage.enter("service_process_cleanup")
    except BaseException as error:
        primary = error
        stage.fail()
        raise
    finally:
        stage.enter("resource_cleanup")
        cleanup_resources(
            stop, publisher_thread, app, admin, org, principals, names, configs, primary
        )
    stage.enter("complete")
