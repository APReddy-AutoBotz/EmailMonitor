"""Actual installed XML CLI, registered service SQL, HTTPS provider and isolated parser.

Only the existing reviewed disposable CI wrapper may start infrastructure. The
original installed HTML test remains separate; this module never injects a journey.
"""

import hashlib
import inspect
import io
import json
import os
import re
import socket
import ssl
import subprocess
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4
from zipfile import ZipFile

import httpx
import pytest
from emailmonitor.extraction.xml_retained import RetainedXml
from emailmonitor.runtime.api_entrypoint import ReferenceAPI, ReferenceIdentity
from emailmonitor.runtime.authority import ServiceProcess
from emailmonitor.runtime.controlled_launcher import launched_worker
from emailmonitor.runtime.delegation import ServiceBinding, ServiceBindings
from emailmonitor.runtime.worker import ServiceRuntimeConfig, broker_application
from emailmonitor.sources import provider_documents as catalog
from installed_operator_issuer import synthetic_issuer
from installed_operator_relay import application
from installed_xml_service_image import installed_service_image
from run_installed_operator import run_installed
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from test_installed_operator_acceptance import (
    api_process_client,
    cleanup_resources,
    config_file,
    finite,
    installed_package,
    require_installed_ci,
)
from test_real_broker_jobs import wait_for
from test_runtime_publisher_broker import declare_owned
from test_tenant_foundation import Scenario
from test_tenant_foundation import scenario as scenario
from test_transport_acceptance import configure, snapshot
from transport_topology import Topology, resource
from xml_image_evidence import require_packaged_image

ROOT = Path(__file__).resolve().parents[2]


def require_xml_context(environment: dict[str, str]) -> None:
    if (
        environment.get("EM_REQUIRE_XML_INTEGRATION") != "synthetic-test-only"
        or environment.get("EM_REQUIRE_CONTROLLED_NETWORK") != "true"
        or re.fullmatch(r"sha256:[a-f0-9]{64}", environment.get("EM_EXPECTED_XML_IMAGE_ID", ""))
        is None
        or re.fullmatch(r"[a-f0-9]{32}", environment.get("EM_EXPECTED_XML_IMAGE_OWNER", "")) is None
    ):
        raise RuntimeError("Curated installed XML CI identity required")


@pytest.fixture
def installed_xml_scenario(request: pytest.FixtureRequest) -> Scenario:
    require_installed_ci(dict(os.environ))
    require_xml_context(dict(os.environ))
    return request.getfixturevalue("scenario")  # type: ignore[no-any-return]


def verify_installed_launcher(installed: Path) -> None:
    # The supervisor runs in this trusted test process to borrow its verified
    # gateway. Prove every imported backend source equals the verified archive;
    # the worker itself uses only the verified, immutable service-image package.
    source = ROOT / "services/backend/src/emailmonitor"
    if inspect.getsourcefile(inspect.unwrap(launched_worker)) != str(
        source / "runtime/controlled_launcher.py"
    ):
        raise RuntimeError("Installed supervisor import origin mismatch")
    packaged = installed / "services/backend/src/emailmonitor"
    expected = {p.relative_to(packaged) for p in packaged.rglob("*.py")}
    actual = {p.relative_to(source) for p in source.rglob("*.py")}
    if actual != expected or not actual:
        raise RuntimeError("Installed supervisor source inventory mismatch")
    if any((source / name).read_bytes() != (packaged / name).read_bytes() for name in expected):
        raise RuntimeError("Installed supervisor source mismatch")


@pytest.fixture
def installed_bundle(
    installed_xml_scenario: Scenario, tmp_path: Path
) -> Iterator[tuple[Path, dict[str, str], str, str]]:
    installed, assets, package_sha = installed_package(tmp_path)
    verify_installed_launcher(installed)
    with installed_service_image(installed, tmp_path / "service-image") as service_image_id:
        yield installed, assets, package_sha, service_image_id


@contextmanager
def owned_topology() -> Iterator[Topology]:
    require_installed_ci(dict(os.environ))
    require_xml_context(dict(os.environ))
    value = Topology()
    try:
        value.start()
        configure(value)
        value.inspect()
        yield value
    finally:
        # close does not send more protocol commands to a poisoned borrowed pipe.
        # It removes only this topology's owned resources and checks host baseline.
        value.close()


@pytest.fixture
def installed_topology(installed_xml_scenario: Scenario) -> Iterator[Topology]:
    with owned_topology() as value:
        yield value
        value.inspect()


@pytest.mark.parametrize("direct_url", [False, True], ids=["keyword", "direct-url"])
def test_installed_controlled_xml_operator(
    installed_xml_scenario: Scenario,
    tmp_path: Path,
    request: pytest.FixtureRequest,
    direct_url: bool,
    installed_bundle: tuple[Path, dict[str, str], str, str],
) -> None:
    case = installed_xml_scenario
    installed, assets, package_sha, service_image_id = installed_bundle
    require_xml_context(dict(os.environ))
    verify_installed_launcher(installed)
    topology: Topology = request.getfixturevalue("installed_topology")
    configure(topology)
    topology.inspect()
    image_id = os.environ["EM_EXPECTED_XML_IMAGE_ID"]
    image = resource("image", image_id)
    if image is None:
        raise RuntimeError("Curated parser image missing")
    require_packaged_image({"Image": image["Id"], "Config": image["Config"]})
    expected_articles = 1 if direct_url else 2
    expected_calls = 1 if direct_url else 3
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
                        {
                            "id": principals[kind],
                            "org": org,
                            "kind": kind,
                            "name": name,
                        },
                    )
            runtime_configs = {}
            for kind, name in names.items():
                runtime_configs[kind] = ServiceRuntimeConfig(
                    environment="test",
                    profile="controlled-xml-service-reference",
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
                    profile="controlled-xml-service-reference",
                    tenants=(
                        ServiceBinding(
                            organization=org,
                            worker=principals["worker"],
                            publisher=principals["publisher"],
                        ),
                    ),
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
            for kind in ("worker", "publisher"):
                assert finite(installed, "check", configs[kind]) == "service_identity_ready"
            app = broker_application(runtime_configs["publisher"])
            declare_owned(app, runtime_configs["publisher"].queue)
            context = ssl.create_default_context(cafile=str(identity.ca))
            with api_process_client(installed, configs["api"], context) as (
                api_process,
                client,
            ):

                def api_ready(running: subprocess.Popen[bytes]) -> bool:
                    assert running.poll() is None, "Installed API exited before readiness"
                    try:
                        response = client.get(origin + "/readyz")
                        return response.status_code == 200 and response.json() == {
                            "api_dependencies_ready": True
                        }
                    except httpx.TransportError:
                        return False

                def worker_ready(running: Any) -> bool:
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
                            text(statement),
                            {"org": org, "id": case.identities["owner"]},
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
                                "organization_id=:org AND state='completed'"
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

                wait_for(lambda: api_ready(api_process), seconds=10)
                profile = client.get(origin + "/api/v1/runtime-profile").json()
                assert profile["profile"] == "controlled-xml-service-reference"
                assert profile["production_ready"] is False
                assert profile["xml_available"] is True
                assert all(
                    profile[key] is False
                    for key in (
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
                with launched_worker(
                    configs["worker"],
                    topology.processes["gateway"],
                    image_id,
                    service_image_id=service_image_id,
                ) as running:
                    wait_for(lambda: worker_ready(running), seconds=10)
                    publisher_thread = threading.Thread(target=publish, daemon=True)
                    publisher_thread.start()
                    setup: dict[str, object] = {
                        "kind": "bootstrap",
                        "journey": "installed-controlled-xml",
                        "direct_article_url": direct_url,
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
                    evidence = run_installed(
                        application(origin, identity.origin, identity.ca, assets, downloads),
                        setup,
                        control,
                        lambda _: False,
                    )
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
                    assert (
                        scalar(
                            "SELECT count(*) FROM emailmonitor.execution_effects WHERE "
                            "organization_id=:org"
                        )
                        == expected_articles
                    )
                    assert (
                        scalar(
                            "SELECT count(*) FROM emailmonitor.association_reviews WHERE "
                            "organization_id=:org"
                        )
                        == expected_articles
                    )
                    assert (
                        scalar(
                            "SELECT count(*) FROM emailmonitor.service_delegations WHERE "
                            "organization_id=:org AND revoked_at IS NULL"
                        )
                        == 6
                    )
                    assert (
                        scalar(
                            "SELECT count(*) FROM emailmonitor.sessions WHERE "
                            "identity_id=:id AND expires_at<=clock_timestamp() AND "
                            "revoked_at IS NULL"
                        )
                        == 1
                    )
                    assert running.parser_calls == expected_articles
                    assert evidence["journey"] == "installed-controlled-xml"
                    assert evidence["direct_article_url"] is direct_url
                    assert (
                        scalar(
                            "SELECT count(*) FROM emailmonitor.article_observations WHERE "
                            "organization_id=:org"
                        )
                        == expected_articles
                    )
                    assert (
                        scalar(
                            "SELECT count(*) FROM emailmonitor.source_resource_requests WHERE "
                            "organization_id=:org AND state='finished'"
                        )
                        == expected_calls
                    )
                    assert (
                        scalar(
                            "SELECT count(*) FROM emailmonitor.source_resource_requests "
                            "WHERE organization_id=:org"
                        )
                        == expected_calls
                    )
                    with admin.connect() as connection:
                        observed: Any = (
                            connection.execute(
                                text(
                                    "SELECT observation FROM emailmonitor.article_observations "
                                    "WHERE organization_id=:org"
                                ),
                                {"org": org},
                            )
                            .scalars()
                            .all()
                        )
                        retained = [
                            RetainedXml.model_validate_json(json.dumps(row)) for row in observed
                        ]
                        assert {row.url for row in retained} == (
                            {catalog.DOI_URL} if direct_url else catalog.ARTICLE_URLS
                        )
                        assert {row.requested_identifier.kind for row in retained} == (
                            {"doi"} if direct_url else {"doi", "pii"}
                        )
                        assert all(
                            row.provider is not None and row.provider.requested_view == "FULL"
                            for row in retained
                        )
                        reviewed = connection.execute(
                            text(
                                "SELECT version,row_version,created_by,reviewed_by "
                                "FROM emailmonitor.source_policies WHERE organization_id=:org"
                            ),
                            {"org": org},
                        ).one()
                        assert (reviewed.version, reviewed.row_version) == (1, 2)
                        assert (
                            reviewed.created_by == reviewed.reviewed_by == case.identities["owner"]
                        )
                        rows: Any = (
                            connection.execute(
                                text(
                                    "SELECT request FROM emailmonitor.jobs "
                                    "WHERE organization_id=:org"
                                ),
                                {"org": org},
                            )
                            .scalars()
                            .all()
                        )
                        assert len(rows) == 1
                        assert rows[0]["input"] == (
                            {"type": "url", "url": catalog.DOI_URL}
                            if direct_url
                            else {
                                "type": "keyword",
                                "source_id": catalog.SOURCE,
                                "original_query": catalog.QUERY,
                            }
                        )
                        policy: Any = connection.execute(
                            text(
                                "SELECT policy FROM emailmonitor.source_policies WHERE "
                                "organization_id=:org AND state='approved'"
                            ),
                            {"org": org},
                        ).scalar_one()
                        assert "fetch_xml" in policy["allowed_operations"]
                        assert policy["execution_mode"] == "fixture"
                        assert policy["credential_reference"] is None
                    calls = snapshot(topology)["calls"]
                    assert len(calls) == expected_calls
                    if direct_url:
                        assert calls[0]["method"] == "GET"
                    else:
                        assert calls[0]["method"] == "PUT"
                        assert json.loads(calls[0]["body"])["qs"] == catalog.QUERY
                    articles = calls if direct_url else calls[1:]
                    assert all(
                        c["method"] == "GET" and c["path"].endswith("?view=FULL") for c in articles
                    )
                    assert len({c["path"] for c in articles}) == expected_articles
                    assert len(downloads) == 2 and downloads[0] != downloads[1]
                    for body in downloads:
                        with ZipFile(io.BytesIO(body)) as archive_file:
                            joined = b"\n".join(
                                archive_file.read(n) for n in archive_file.namelist()
                            )
                            assert b"Second@example.org" in joined
                            assert (b"beta@example.org" in joined) is not direct_url
                            assert catalog.DOI_URL.encode() in joined
                            assert b"not_checked" in joined and b"not_assessed" in joined
                    print(
                        json.dumps(
                            {
                                **evidence,
                                "package_sha256": package_sha,
                                "service_image_id": service_image_id,
                                "installed_api_ready": True,
                                "independent_installed_worker": True,
                                "independent_installed_publisher": True,
                                "proof": (
                                    "INSTALLED_CONTROLLED_XML_DIRECT_URL_REVIEW_EXPORT"
                                    if direct_url
                                    else "INSTALLED_CONTROLLED_XML_KEYWORD_REVIEW_EXPORT"
                                ),
                                "parser_image_id": image_id,
                                "launcher_matches_installed_archive": True,
                                "actual_provider_calls": expected_calls,
                                "retained_xml_observations": expected_articles,
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
                    stop.set()
                    publisher_thread.join(timeout=25)
                    assert not publisher_thread.is_alive()
    except BaseException as error:
        primary = error
        raise
    finally:
        cleanup_resources(
            stop, publisher_thread, app, admin, org, principals, names, configs, primary
        )


@contextmanager
def service_xml_case(
    case: Scenario, directory: Path
) -> Iterator[tuple[Any, Any, dict[str, Path], dict[str, str], Any, Any]]:
    """Synthetic job setup only; every execution uses the real installed worker."""
    from emailmonitor.organizations.roles import Capability
    from test_provider_journey_tenant import planned_provider

    progress, job = planned_provider(case, url=catalog.DOI_URL)
    org = case.organizations[0]
    progress.start(org, job, progress.snapshot(org, job).revision)
    admin = create_engine(case.admin_url, hide_parameters=True)
    principals = {kind: uuid4() for kind in ("worker", "publisher")}
    names = {kind: "em_installed_xml_" + uuid4().hex for kind in principals}
    configs: dict[str, Path] = {}
    app: Any = None
    primary: BaseException | None = None
    try:
        for kind, name in names.items():
            with admin.begin() as c:
                c.exec_driver_sql(
                    f"CREATE ROLE {name} LOGIN NOSUPERUSER NOBYPASSRLS "
                    "PASSWORD 'authored-disposable-service-only'"
                )
                c.exec_driver_sql(f"GRANT emailmonitor_{kind} TO {name}")
                c.execute(
                    text(
                        "INSERT INTO emailmonitor.service_principals "
                        "(id,organization_id,login_oid,login_name,kind,active) "
                        "SELECT :id,:org,oid,rolname,:kind,true FROM pg_roles WHERE rolname=:name"
                    ),
                    {"id": principals[kind], "org": org, "kind": kind, "name": name},
                )
            with progress.database.tenant(progress.token, org, Capability.ACQUIRE_SOURCE) as (c, _):
                c.execute(
                    text(
                        "SELECT emailmonitor.delegate_service_work("
                        ":org,:principal,:job,'extraction',21600)"
                    ),
                    {"org": org, "principal": principals[kind], "job": job},
                )
            configuration = ServiceRuntimeConfig(
                environment="test",
                profile="controlled-xml-service-reference",
                database_url=make_url(case.admin_url)
                .set(username=name, password="authored-disposable-service-only")
                .render_as_string(hide_password=False),
                broker_url=os.environ["EM_TEST_BROKER_URL"],
                organization=org,
                queue="em-fixture-" + org.hex,
                process=ServiceProcess(kind=kind, principal=principals[kind]),  # type: ignore[arg-type]
                lease_seconds=30 if kind == "worker" else 5,
            )
            configs[kind] = config_file(directory, configuration.model_dump_json())
        app = broker_application(configuration)
        declare_owned(app, configuration.queue)
        yield progress, job, configs, names, admin, app
    except BaseException as error:
        primary = error
        raise
    finally:
        cleanup_resources(
            threading.Event(), None, app, admin, org, principals, names, configs, primary
        )


def test_installed_controlled_xml_post_observation_crash_recovery(
    installed_xml_scenario: Scenario,
    tmp_path: Path,
    installed_bundle: tuple[Path, dict[str, str], str, str],
) -> None:
    """A real SIGKILL after XML commit; recovery must not reacquire or reparse."""
    case = installed_xml_scenario
    installed, _, package_sha, service_image_id = installed_bundle
    verify_installed_launcher(installed)
    image_id = os.environ["EM_EXPECTED_XML_IMAGE_ID"]
    image = resource("image", image_id)
    assert image is not None
    require_packaged_image({"Image": image["Id"], "Config": image["Config"]})
    org = case.organizations[0]
    with service_xml_case(case, tmp_path) as (progress, job, configs, names, admin, app):
        params = {"org": org, "job": job}

        def count(table: str) -> int:
            assert table in {"article_observations", "association_batches", "execution_effects"}
            with admin.connect() as c:
                return int(
                    c.execute(
                        text(
                            f"SELECT count(*) FROM emailmonitor.{table} "
                            "WHERE organization_id=:org AND job_id=:job"
                        ),
                        params,
                    ).scalar_one()
                )

        with owned_topology() as first:
            with admin.connect() as barrier:
                transaction = barrier.begin()
                try:
                    # Relation lock blocks derive's first batch SELECT, not XML's
                    # observation commit. Only this disposable CI database is used.
                    barrier.exec_driver_sql(
                        "LOCK TABLE emailmonitor.association_batches IN ACCESS EXCLUSIVE MODE"
                    )
                    with pytest.raises(RuntimeError, match="^Controlled worker capability failed$"):
                        with launched_worker(
                            configs["worker"],
                            first.processes["gateway"],
                            image_id,
                            service_image_id=service_image_id,
                        ) as worker:
                            # One queued direct-article event is sufficient. Avoid
                            # spawning publisher checks inside the two-second SQL
                            # lock observation window.
                            assert (
                                finite(installed, "publish-once", configs["publisher"])
                                == "published=1"
                            )

                            def committed_and_blocked() -> bool:
                                assert worker.poll() is None
                                if count("article_observations") != 1:
                                    return False
                                with admin.connect() as c:
                                    return bool(
                                        c.execute(
                                            text(
                                                "SELECT count(*)=1 FROM pg_stat_activity "
                                                "WHERE usename=:name AND wait_event_type='Lock' "
                                                "AND query LIKE "
                                                "'%emailmonitor.association_batches%'"
                                            ),
                                            {"name": names["worker"]},
                                        ).scalar_one()
                                    )

                            wait_for(committed_and_blocked, seconds=45)
                            assert len(snapshot(first)["calls"]) == 1
                            assert worker.parser_calls == 1
                            worker.kill()
                            assert worker.wait(timeout=5) == 137
                finally:
                    transaction.rollback()
            assert count("article_observations") == 1
            assert count("association_batches") == count("execution_effects") == 0
        # A failed capability is never reopened. Fresh owned topology, same
        # committed observation and broker delivery, fresh installed process.
        with owned_topology() as fresh:
            with launched_worker(
                configs["worker"],
                fresh.processes["gateway"],
                image_id,
                service_image_id=service_image_id,
            ) as recovered:

                def completed() -> bool:
                    assert recovered.poll() is None
                    finite(installed, "publish-once", configs["publisher"])
                    return bool(progress.snapshot(org, job).state == "completed")

                wait_for(completed, seconds=90)
                assert count("article_observations") == count("association_batches") == 1
                assert count("execution_effects") == 1
                assert snapshot(fresh)["calls"] == []
                assert recovered.parser_calls == 0
                with admin.connect() as c:
                    assert (
                        c.execute(
                            text(
                                "SELECT count(*) FROM emailmonitor.source_resource_requests "
                                "WHERE organization_id=:org AND job_id=:job"
                            ),
                            params,
                        ).scalar_one()
                        == 1
                    )
                fresh.inspect()
        print(
            json.dumps(
                {
                    "proof": "INSTALLED_CONTROLLED_XML_POST_OBSERVATION_CRASH_RECOVERY",
                    "package_sha256": package_sha,
                    "service_image_id": service_image_id,
                    "parser_image_id": image_id,
                    "actual_kill": "SIGKILL",
                    "retained_observations": 1,
                    "execution_effects": 1,
                    "recovery_provider_calls": 0,
                    "recovery_parser_calls": 0,
                    "production_ready": False,
                },
                sort_keys=True,
            ),
            flush=True,
        )


def test_installed_controlled_xml_delegation_revoked_before_response_release(
    installed_xml_scenario: Scenario,
    tmp_path: Path,
    installed_bundle: tuple[Path, dict[str, str], str, str],
) -> None:
    """Revoke real service authority while an actual HTTPS response is held."""
    import time

    case = installed_xml_scenario
    installed, _, package_sha, service_image_id = installed_bundle
    image_id = os.environ["EM_EXPECTED_XML_IMAGE_ID"]
    image = resource("image", image_id)
    assert image is not None
    require_packaged_image({"Image": image["Id"], "Config": image["Config"]})
    org, other = case.organizations
    with service_xml_case(case, tmp_path) as (_, job, configs, _, admin, app):
        configuration = ServiceRuntimeConfig.model_validate_json(configs["worker"].read_text())
        with owned_topology() as network:
            configure(network, "slow")
            # The existing fixture holds this response for at most 15 seconds.
            # No new wait mode, transport hook or deadline extension is introduced.
            released = False

            def release() -> None:
                nonlocal released
                if released:
                    return
                released = True  # Never retry an ambiguous control exchange.
                fixture = network.processes["fixture-a"]
                if fixture.poisoned:
                    raise RuntimeError("Held fixture control unavailable")
                deadline = time.monotonic() + 5
                try:
                    fixture.send({"kind": "release"}, deadline)
                    assert fixture.receive(deadline) == {"kind": "released"}
                except BaseException:
                    fixture.poisoned = True
                    raise

            with pytest.raises(RuntimeError, match="^Controlled worker capability failed$"):
                with launched_worker(
                    configs["worker"],
                    network.processes["gateway"],
                    image_id,
                    service_image_id=service_image_id,
                ) as worker:
                    try:
                        assert (
                            finite(installed, "publish-once", configs["publisher"]) == "published=1"
                        )
                        calls: list[dict[str, Any]] = []
                        deadline = time.monotonic() + 10
                        # Fixed 50 observations preserve the existing fixture's
                        # 128-frame lifetime ceiling and original ten-second wait.
                        for _index in range(50):
                            assert worker.poll() is None
                            calls = snapshot(network)["calls"]
                            if calls:
                                break
                            if time.monotonic() >= deadline:
                                break
                            time.sleep(0.2)
                        assert len(calls) == 1
                        assert calls[0]["method"] == "GET"
                        assert calls[0]["path"] == (
                            "/content/article/doi/10.9999/synthetic.1?view=FULL"
                        )
                        # Refuse a late observation, rather than claiming a race
                        # after the fixture's automatic release could have fired.
                        assert time.monotonic() - calls[0]["received_monotonic"] < 10
                        assert worker.parser_calls == 0
                        with admin.begin() as c:
                            ticket = c.execute(
                                text(
                                    "SELECT id,state,lease_until,service_delegation "
                                    "FROM emailmonitor.source_resource_requests "
                                    "WHERE organization_id=:org AND job_id=:job"
                                ),
                                {"org": org, "job": job},
                            ).one()
                            assert ticket.state == "active" and ticket.lease_until is not None
                            revoked = (
                                c.execute(
                                    text(
                                        "UPDATE emailmonitor.service_delegations "
                                        "SET revoked_at=clock_timestamp() "
                                        "WHERE id=:grant AND organization_id=:org "
                                        "AND principal_id=:principal "
                                        "AND revoked_at IS NULL RETURNING id"
                                    ),
                                    {
                                        "grant": ticket.service_delegation,
                                        "org": org,
                                        "principal": configuration.process.principal,
                                    },
                                )
                                .scalars()
                                .all()
                            )
                            assert revoked == [ticket.service_delegation]
                        assert time.monotonic() - calls[0]["received_monotonic"] < 15
                    finally:
                        release()
                    wait_for(lambda: worker.poll() is not None, seconds=25)
                    assert worker.parser_calls == 0
            calls = snapshot(network)["calls"]
            assert len(calls) == 1  # No retry, alternate identity or fallback.
            with admin.connect() as c:
                for table in ("article_observations", "association_batches", "execution_effects"):
                    assert (
                        c.execute(
                            text(
                                f"SELECT count(*) FROM emailmonitor.{table} "
                                "WHERE organization_id IN (:org,:other)"
                            ),
                            {"org": org, "other": other},
                        ).scalar_one()
                        == 0
                    )
                revoked = c.execute(
                    text(
                        "SELECT revoked_at IS NOT NULL FROM emailmonitor.service_delegations "
                        "WHERE id=:grant AND principal_id=:principal"
                    ),
                    {
                        "grant": ticket.service_delegation,
                        "principal": configuration.process.principal,
                    },
                ).scalar_one()
                assert revoked is True
                # Revocation can deny SQL cleanup too. Such a ticket is allowed
                # only its original finite lease; never claim it was released.
                resource_state = c.execute(
                    text(
                        "SELECT state,lease_until IS NOT NULL AND "
                        "lease_until<=clock_timestamp()+interval '20 seconds' AS bounded "
                        "FROM emailmonitor.source_resource_requests "
                        "WHERE organization_id=:org AND id=:ticket"
                    ),
                    {"org": org, "ticket": ticket.id},
                ).one()
                assert resource_state.state == "finished" or (
                    resource_state.state == "active" and resource_state.bounded is True
                )
            print(
                json.dumps(
                    {
                        "proof": "INSTALLED_CONTROLLED_XML_DELEGATION_REVOKED_DURING_RESPONSE",
                        "revocation_point": "actual_https_request_held_before_byte_parser_release",
                        "package_sha256": package_sha,
                        "service_image_id": service_image_id,
                        "parser_image_id": image_id,
                        "provider_calls": 1,
                        "parser_calls": 0,
                        "both_tenant_observations_batches_effects": 0,
                        "source_resource_state": resource_state.state,
                        "active_resource_lease_bounded": resource_state.state == "active",
                        "production_ready": False,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
