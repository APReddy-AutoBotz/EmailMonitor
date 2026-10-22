"""Fresh-process CLI import boundaries; no server, database or broker is started."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

SOURCE = Path(__file__).resolve().parents[1] / "src"

REFUSAL_PROBE = """
import builtins, pathlib, sys
sys.path.insert(0, sys.argv[1])
forbidden = {
    'celery', 'kombu', 'sqlalchemy', 'fastapi', 'uvicorn', 'cryptography', 'jwt', 'pypdf',
    'emailmonitor.runtime.worker', 'emailmonitor.runtime.service_publisher',
    'emailmonitor.runtime.assembly', 'emailmonitor.runtime.service_api',
    'emailmonitor.identity.oidc', 'emailmonitor.organizations.database',
}
attempts = []
original_import = builtins.__import__
def matches(name):
    return any(name == blocked or name.startswith(blocked + '.') for blocked in forbidden)
def guarded(name, *args, **kwargs):
    if matches(name):
        attempts.append(name)
        raise AssertionError('Execution dependency imported before refusal')
    return original_import(name, *args, **kwargs)
builtins.__import__ = guarded
from emailmonitor.runtime import entrypoint
sys.argv = ['service', 'api', '--config', sys.argv[2]]
result = entrypoint.main()
assert not attempts
assert not any(matches(name) for name in sys.modules)
assert result == 1
raise SystemExit(result)
"""


@pytest.mark.parametrize(
    "body",
    [
        b'{"environment":"production"}',
        b'{"environment":"production"}' + b" " * (65_536 - 28),
        b'{"environment":"test"}',
        b'{"environment":"invalid"}',
        b'{"environment":false}',
        b"{}",
        b"[]",
        b"null",
        b"{malformed",
        b"\xff",
    ],
)
def test_api_refusal_precedes_execution_imports_in_fresh_process(
    tmp_path: Path, body: bytes
) -> None:
    config = tmp_path / "synthetic-config.json"
    config.write_bytes(body)
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", REFUSAL_PROBE, str(SOURCE), str(config)],
        capture_output=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 1
    assert result.stdout == b""
    assert result.stderr == b"service_runtime_failed\n"


@pytest.mark.parametrize("kind", ["oversized", "symlink", "directory", "missing"])
def test_api_file_boundaries_still_refuse_before_execution_imports(
    tmp_path: Path, kind: str
) -> None:
    config = tmp_path / "synthetic-config.json"
    if kind == "oversized":
        config.write_bytes(b" " * 65_537)
    elif kind == "symlink":
        target = tmp_path / "target.json"
        target.write_bytes(b'{"environment":"production"}')
        config.symlink_to(target)
    elif kind == "directory":
        config.mkdir()
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", REFUSAL_PROBE, str(SOURCE), str(config)],
        capture_output=True,
        timeout=5,
        check=False,
    )
    assert (result.returncode, result.stdout, result.stderr) == (
        1,
        b"",
        b"service_runtime_failed\n",
    )


def test_valid_api_model_and_actual_route_registration_in_fresh_process(tmp_path: Path) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    body = {
        "environment": "test",
        "runtime_database_url": "postgresql+pg8000://runtime:synthetic@127.0.0.1:5432/disposable",
        "authentication_database_url": "postgresql+pg8000://auth:synthetic@127.0.0.1:5432/disposable",
        "bindings": {
            "tenants": [
                {
                    "organization": "00000000-0000-0000-0000-000000000011",
                    "worker": "00000000-0000-0000-0000-000000000012",
                    "publisher": "00000000-0000-0000-0000-000000000013",
                }
            ]
        },
        "identity": {
            "issuer": "https://127.0.0.1:4444",
            "client_id": "synthetic-client",
            "authorization_endpoint": "https://127.0.0.1:4444/authorize",
            "token_endpoint": "https://127.0.0.1:4444/token",
            "redirect_uri": "https://127.0.0.1:4443/auth/complete",
            "verification_keys": {"synthetic": public_key.decode()},
            "certificate_authority": str(tmp_path / "synthetic-ca.pem"),
        },
        "port": 4443,
        "certificate": str(tmp_path / "synthetic-server.pem"),
        "private_key": str(tmp_path / "synthetic-server-key.pem"),
    }
    config = tmp_path / "synthetic-config.json"
    config.write_text(json.dumps(body))
    web = tmp_path / "static-web"
    web.mkdir()
    (web / "index.html").write_text("synthetic web")
    source = """
import pathlib, socket, sys
from contextlib import contextmanager
sys.path.insert(0, sys.argv[1])
def forbidden(*args, **kwargs):
    raise AssertionError('No network allowed in route construction probe')
socket.create_connection = forbidden
socket.getaddrinfo = forbidden
socket.socket.connect = forbidden
import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from emailmonitor.runtime import api_entrypoint, entrypoint
from emailmonitor.runtime import service_api as assembly
root = pathlib.Path(sys.argv[3])
api_entrypoint.__file__ = str(root / 'services/backend/src/emailmonitor/runtime/api_entrypoint.py')
app = FastAPI()
events = []
@contextmanager
def assembled(config, provider):
    assert config.runtime.settings.environment == 'test'
    assert len(config.bindings.tenants) == 1
    assert isinstance(provider.exchange_adapter, api_entrypoint.ReferenceExchange)
    events.append('enter')
    try:
        yield app
    finally:
        events.append('exit')
assembly.service_api = assembled
def serve(application, **options):
    assert application is app
    complete = next(route for route in app.routes if route.path == '/auth/complete')
    assert complete.endpoint.__annotations__['return'] is FileResponse
    response = complete.endpoint()
    assert response.path == root / 'static-web/index.html'
    assert response.headers['cache-control'] == 'no-store'
    assert complete.include_in_schema is False
    operator = next(route for route in app.routes if route.name == 'operator')
    assert isinstance(operator.app, StaticFiles)
    app.openapi()
    assert options == {
        'host': '127.0.0.1', 'port': 4443,
        'ssl_certfile': str(root / 'synthetic-server.pem'),
        'ssl_keyfile': str(root / 'synthetic-server-key.pem'),
        'access_log': False, 'log_level': 'critical',
    }
    events.append('serve')
uvicorn.run = serve
config_path = pathlib.Path(sys.argv[2])
original_open = pathlib.Path.open
reads = []
def tracked_open(self, *args, **kwargs):
    if self == config_path:
        reads.append(args)
    return original_open(self, *args, **kwargs)
pathlib.Path.open = tracked_open
sys.argv = ['service', 'api', '--config', str(config_path)]
assert entrypoint.main() == 0
assert reads == [('rb',)]
assert events == ['enter', 'serve', 'exit']
"""
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", source, str(SOURCE), str(config), str(tmp_path)],
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == b"" and result.stderr == b""
