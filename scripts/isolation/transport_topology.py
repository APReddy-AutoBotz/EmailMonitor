"""Owned disposable Docker topology; inspect fail-closed before any guest I/O."""

import hashlib
import ipaddress
import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from initialize_ci_ipv6 import initialize, require_disposable_ci
from run_browser_acceptance import PAGE
from tls_fixture_server import certificate
from transport_manifest import ENDPOINTS, IPAM_GATEWAYS, V4_SUBNET, V6_SUBNET
from transport_rpc import OwnedProcess

SUBNETS = (ipaddress.ip_network(V4_SUBNET), ipaddress.ip_network(V6_SUBNET))


def check_host_ipv6_forwarding() -> None:
    """Refuse before creation if Docker could initialize host-wide forwarding."""
    for name in ("all", "default"):
        try:
            value = Path(f"/proc/sys/net/ipv6/conf/{name}/forwarding").read_text(encoding="ascii")
        except (OSError, UnicodeError) as error:
            raise RuntimeError("Existing host IPv6 forwarding cannot be verified") from error
        if value not in ("1", "1\n"):
            raise RuntimeError(
                "Unsupported runner: host IPv6 all/default forwarding must already be 1; "
                "no network creation or host configuration is permitted"
            )


def docker(
    *arguments: str, timeout: float = 120, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *arguments], capture_output=True, text=True, timeout=timeout, check=check
    )


OWNER_LABEL = "emailmonitor.acceptance-owner"


def resource(kind: str, name: str) -> dict[str, Any] | None:
    if kind not in ("container", "network", "image"):
        raise RuntimeError("Unknown owned resource type")
    result = docker(kind, "inspect", name, check=False)
    if result.returncode:
        error = result.stderr.lower()
        missing = (
            "no such object",
            "no such container",
            "no such image",
            "no such network",
            "network " + name.lower() + " not found",
        )
        if any(reason in error for reason in missing):
            return None
        raise RuntimeError("Owned resource absence cannot be established")
    values = json.loads(result.stdout)
    if type(values) is not list or len(values) != 1 or type(values[0]) is not dict:
        raise RuntimeError("Invalid owned resource inspection")
    return values[0]


def require_owner(kind: str, value: dict[str, Any], owner: str) -> None:
    labels = value.get("Labels") if kind == "network" else value.get("Config", {}).get("Labels")
    if type(labels) is not dict or labels.get(OWNER_LABEL) != owner:
        raise RuntimeError("Refusing to remove an unknown resource")


def remove_owned(kind: str, name: str, owner: str) -> None:
    value = resource(kind, name)
    if value is None:
        return
    require_owner(kind, value, owner)
    if kind == "container":
        docker("rm", "--force", name)
    else:
        docker(kind, "rm", name)
    if resource(kind, name) is not None:
        raise RuntimeError("Owned resource remains after cleanup")


def ip(*arguments: str) -> list[dict[str, Any]]:
    result = subprocess.run(
        ["ip", "-j", *arguments], capture_output=True, text=True, check=True, timeout=10
    )
    value = json.loads(result.stdout)
    if type(value) is not list:
        raise RuntimeError("Missing route inspection")
    return value


def overlaps(value: str) -> bool:
    candidate = ipaddress.ip_network(value, strict=False)
    return any(
        candidate.version == subnet.version and candidate.overlaps(subnet) for subnet in SUBNETS
    )


def host_baseline() -> dict[str, object]:
    addresses = ip("address", "show")
    routes = ip("-4", "route", "show", "table", "all") + ip("-6", "route", "show", "table", "all")
    rules = ip("-4", "rule", "show") + ip("-6", "rule", "show")
    for interface in addresses:
        for address in interface.get("addr_info", []):
            if overlaps(str(address["local"]) + "/" + str(address["prefixlen"])):
                raise RuntimeError("Synthetic IPAM conflicts with a host address")
    for route in routes:
        destination = route.get("dst", "default")
        if destination != "default" and overlaps(str(destination)):
            raise RuntimeError("Synthetic IPAM conflicts with a nondefault host route")
    return {"addresses": addresses, "routes": routes, "rules": rules}


def baseline_diagnostic(before: dict[str, object], after: dict[str, object]) -> str:
    """Bounded read-only evidence; never normalizes or changes acceptance equality."""
    sections: dict[str, object] = {}
    for key in ("addresses", "routes", "rules"):
        original, current = before.get(key), after.get(key)
        if original == current:
            continue
        if type(original) is not list or type(current) is not list:
            sections[key] = {"unexpected_shape": True}
            continue
        left = Counter(json.dumps(row, sort_keys=True) for row in original)
        right = Counter(json.dumps(row, sort_keys=True) for row in current)
        removed, added = list((left - right).elements()), list((right - left).elements())
        sections[key] = {
            "before_count": len(original),
            "after_count": len(current),
            "removed_count": len(removed),
            "added_count": len(added),
            "removed": [row[:512] for row in removed[:4]],
            "added": [row[:512] for row in added[:4]],
            "order_only": not removed and not added,
        }
    return json.dumps({"host_baseline_difference": sections}, sort_keys=True)[:16384]


def check_daemon() -> str:
    version = json.loads(docker("version", "--format={{json .Server}}").stdout)
    number = str(version.get("Version", ""))
    if (
        not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.]+)?", number)
        or int(number.split(".")[0]) < 28
        or version.get("Os") != "linux"
        or version.get("Arch") != "amd64"
    ):
        raise RuntimeError("Existing Linux amd64 Docker Engine 28+ required")
    info = json.loads(docker("info", "--format={{json .}}").stdout)
    if (
        "name=seccomp,profile=builtin" not in info.get("SecurityOptions", [])
        or info.get("OSType") != "linux"
        or not info.get("MemoryLimit")
        or not info.get("SwapLimit")
        or not info.get("PidsLimit")
        or not info.get("CpuCfsPeriod")
        or not info.get("CpuCfsQuota")
    ):
        raise RuntimeError("Required default security/resource support unavailable")
    return number


def validate_network(value: dict[str, Any], name: str, bridge: str, identifiers: set[str]) -> None:
    expected_options = {
        "com.docker.network.bridge.name": bridge,
        "com.docker.network.bridge.gateway_mode_ipv4": "isolated",
        "com.docker.network.bridge.gateway_mode_ipv6": "isolated",
        "com.docker.network.bridge.enable_ip_masquerade": "false",
    }
    config = value.get("IPAM", {}).get("Config")
    expected_ipam = {(V4_SUBNET, IPAM_GATEWAYS[0]), (V6_SUBNET, IPAM_GATEWAYS[1])}
    if (
        type(config) is not list
        or len(config) != 2
        or any(
            type(record) is not dict
            or set(record) - {"Subnet", "Gateway", "IPRange", "AuxiliaryAddresses"}
            or record.get("IPRange")
            or record.get("AuxiliaryAddresses")
            for record in config
        )
    ):
        raise RuntimeError("Unexpected IPAM reservation")
    normalized_ipam = {(record.get("Subnet"), record.get("Gateway")) for record in config}
    if (
        value.get("Name") != name
        or value.get("Driver") != "bridge"
        or value.get("Scope") != "local"
        or not value.get("Internal")
        or not value.get("EnableIPv4")
        or not value.get("EnableIPv6")
        or value.get("Ingress")
        or value.get("ConfigOnly")
        or value.get("IPAM", {}).get("Driver") != "default"
        or value.get("IPAM", {}).get("Options") not in (None, {})
        or normalized_ipam != expected_ipam
        or value.get("Options") != expected_options
        or set(value.get("Containers", {})) != identifiers
    ):
        raise RuntimeError("Isolated network manifest mismatch")


def validate_container(value: dict[str, Any], name: str, role: str, running: bool) -> None:
    host, config, network = value["HostConfig"], value["Config"], value["NetworkSettings"]
    attached = network["Networks"]
    if set(attached) != {name}:
        raise RuntimeError("Unexpected network attachment")
    endpoint = attached[name]
    environment = config.get("Env", [])
    fields = [value.partition("=") for value in environment]
    allowed = {
        "PATH",
        "LANG",
        "PYTHON_VERSION",
        "PYTHON_SHA256",
        "GPG_KEY",
        "PYTHONPATH",
        "PYTHONDONTWRITEBYTECODE",
        "EM_TRANSPORT_ROLE",
    }
    if (
        any(not separator or key not in allowed for key, separator, _ in fields)
        or len({key for key, _, _ in fields}) != len(fields)
        or dict((key, value) for key, _, value in fields).get("EM_TRANSPORT_ROLE") != role
    ):
        raise RuntimeError("Unexpected container environment")
    sysctls = {"net.ipv4.ip_unprivileged_port_start": "443"} if role.startswith("fixture-") else {}
    if (
        host["NetworkMode"] != name
        or host["Privileged"]
        or host["CapAdd"]
        or host["CapDrop"] != ["ALL"]
        or host["SecurityOpt"] != ["no-new-privileges"]
        or not host["ReadonlyRootfs"]
        or host["Binds"]
        or host.get("Devices")
        or host.get("DeviceRequests")
        or host.get("PortBindings")
        or host.get("ExtraHosts")
        or host.get("Links")
        or host["PidMode"] == "host"
        or host["IpcMode"] == "host"
        or (host.get("Sysctls") or {}) != sysctls
        or value["Mounts"]
        or config["User"] != "65532:65532"
        or host["Dns"] != ["127.0.0.1"]
        or host["DnsSearch"] != ["."]
        or host["Memory"] != 268435456
        or host["MemorySwap"] != 268435456
        or host["NanoCpus"] != 500000000
        or host["PidsLimit"] != 64
        or network.get("Ports")
    ):
        raise RuntimeError("Approved container manifest mismatch")
    if running:
        if (
            endpoint["IPAddress"] != ENDPOINTS[role][0]
            or endpoint["GlobalIPv6Address"] != ENDPOINTS[role][1]
            or endpoint["Gateway"]
            or endpoint["IPv6Gateway"]
        ):
            raise RuntimeError("Assigned literal network endpoint mismatch")
    elif endpoint.get("IPAMConfig") != {
        "IPv4Address": ENDPOINTS[role][0],
        "IPv6Address": ENDPOINTS[role][1],
    }:
        raise RuntimeError("Pending literal network assignment mismatch")


class Topology:
    def __init__(self) -> None:
        if os.environ.get("GITHUB_ACTIONS") != "true":
            raise RuntimeError("Reviewed disposable CI environment required")
        require_disposable_ci()
        self.version = check_daemon()
        self.preparation_baseline = host_baseline()
        self.baseline: dict[str, object] | None = None
        suffix = secrets.token_hex(5)
        self.name, self.bridge = "em-fetch-" + suffix, "em" + suffix
        self.identifiers: dict[str, str] = {}
        self.processes: dict[str, OwnedProcess] = {}
        self.images: list[str] = []
        self.image_provenance: dict[str, dict[str, str]] = {}
        self.container_names: dict[str, str] = {}
        self.owner = secrets.token_hex(16)
        self.network_created = False
        self.browser_identifier: str | None = None
        self.directory = tempfile.TemporaryDirectory(prefix="em-fetch-context-")
        self.root = Path(__file__).resolve().parents[2]
        networks = [
            json.loads(line)
            for line in docker("network", "ls", "--format=json").stdout.splitlines()
        ]
        for network in networks:
            metadata = json.loads(docker("network", "inspect", network["ID"]).stdout)[0]
            if metadata["Name"] == self.name:
                raise RuntimeError("Owned network name collision")
            for config in metadata["IPAM"].get("Config") or []:
                if config.get("Subnet") and overlaps(config["Subnet"]):
                    raise RuntimeError("Synthetic IPAM conflicts with an existing network")
        if (Path("/sys/class/net") / self.bridge).exists():
            raise RuntimeError("Owned bridge name collision")
        self.suffix = suffix

    def _build(self, root: Path, directory: Path, suffix: str) -> None:
        cert, key = certificate(directory)
        untrusted_directory = directory / "untrusted"
        untrusted_directory.mkdir()
        untrusted_cert, _ = certificate(untrusted_directory)
        fixture = directory / "fixture"
        gateway = directory / "gateway"
        fixture.mkdir()
        gateway.mkdir()
        for context in (fixture, gateway):
            shutil.copy(cert, context / "fixture-cert.pem")
            for name in ("transport_manifest.py", "transport_routes.py"):
                shutil.copy(root / "scripts/isolation" / name, context / name)
        issuer = x509.load_pem_x509_certificate(cert.read_bytes())
        issuer_key = serialization.load_pem_private_key(key.read_bytes(), password=None)
        if not isinstance(issuer_key, rsa.RSAPrivateKey):
            raise RuntimeError("Synthetic RSA issuer required")
        leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        leaf = (
            x509.CertificateBuilder()
            .subject_name(
                x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "denied.fixture.example")])
            )
            .issuer_name(issuer.subject)
            .public_key(leaf_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.now(UTC) - timedelta(minutes=1))
            .not_valid_after(datetime.now(UTC) + timedelta(hours=1))
            .add_extension(
                x509.SubjectAlternativeName([x509.DNSName("denied.fixture.example")]),
                critical=False,
            )
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(issuer_key, hashes.SHA256())
        )
        (fixture / "wrong-name-cert.pem").write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
        (fixture / "wrong-name-key.pem").write_bytes(
            leaf_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        (fixture / "wrong-name-key.pem").chmod(0o600)
        shutil.copy(untrusted_cert, gateway / "untrusted-cert.pem")
        shutil.copy(key, fixture / "fixture-key.pem")
        shutil.copy(
            root / "scripts/isolation/transport_fixture.py", fixture / "transport_fixture.py"
        )
        (fixture / "synthetic-page.html").write_bytes(PAGE)
        shutil.copy(root / "scripts/isolation/Dockerfile.transport-fixture", fixture / "Dockerfile")
        shutil.copytree(
            root / "services/backend/src",
            gateway / "src",
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        shutil.copy(root / "services/backend/pyproject.toml", gateway / "pyproject.toml")
        shutil.copy(root / "services/backend/uv.lock", gateway / "uv.lock")
        shutil.copy(
            root / "scripts/isolation/transport_gateway.py", gateway / "transport_gateway.py"
        )
        shutil.copy(root / "scripts/isolation/Dockerfile.transport-gateway", gateway / "Dockerfile")
        for role, context in (("fixture", fixture), ("gateway", gateway)):
            image = "emailmonitor-" + role + ":" + suffix
            self._build_image(image, context)
        self._build_image(
            "emailmonitor-controlled-browser:" + suffix,
            root,
            root / "scripts/isolation/Dockerfile.browser",
        )

    def _build_image(self, image: str, context: Path, dockerfile: Path | None = None) -> None:
        self._register_image(image)
        args = [
            "build",
            "--platform=linux/amd64",
            "--label=" + OWNER_LABEL + "=" + self.owner,
            "--tag",
            image,
        ]
        if dockerfile is not None:
            args += ["--file", str(dockerfile)]
        docker(*args, str(context), timeout=600)
        metadata = resource("image", image)
        if metadata is None:
            raise RuntimeError("Missing owned image")
        require_owner("image", metadata, self.owner)
        identifier = metadata.get("Id", "")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", identifier):
            raise RuntimeError("Missing immutable owned image identity")
        recipe = (dockerfile or context / "Dockerfile").read_bytes()
        self.image_provenance[image] = {
            "image_id": identifier,
            "dockerfile_sha256": hashlib.sha256(recipe).hexdigest(),
            "pinned_base": next(
                line for line in recipe.decode().splitlines() if line.startswith("FROM ")
            ),
        }

    def _prepared_image(self, image: str) -> str:
        expected = self.image_provenance.get(image)
        metadata = resource("image", image)
        if expected is None or metadata is None or metadata.get("Id") != expected["image_id"]:
            raise RuntimeError("Prepared owned image changed or is missing")
        require_owner("image", metadata, self.owner)
        return expected["image_id"]

    def _capture_baseline(self) -> None:
        if self.baseline is not None or self.network_created:
            raise RuntimeError("Protected baseline cannot be recaptured")
        check_host_ipv6_forwarding()
        self.baseline = host_baseline()
        print(
            json.dumps(
                {
                    "protected_baseline_digest": hashlib.sha256(
                        json.dumps(self.baseline, sort_keys=True).encode()
                    ).hexdigest()
                }
            ),
            flush=True,
        )

    def _register_image(self, image: str) -> None:
        if resource("image", image) is not None:
            raise RuntimeError("Owned image name collision")
        self.images.append(image)

    def _register_container(self, role: str) -> str:
        name = self.name + "-" + role
        if role in self.container_names or resource("container", name) is not None:
            raise RuntimeError("Owned container name collision")
        self.container_names[role] = name
        return name

    def _container_id(self, name: str, result: str) -> str:
        metadata = resource("container", name)
        if (
            metadata is None
            or metadata.get("Id") != result
            or not re.fullmatch(r"[0-9a-f]{64}", result)
        ):
            raise RuntimeError("Owned container identity mismatch")
        require_owner("container", metadata, self.owner)
        return result

    def start(self) -> None:
        require_disposable_ci()
        if self.baseline is not None or self.network_created:
            raise RuntimeError("Protected phase already started")
        self._build(self.root, Path(self.directory.name), self.suffix)
        prepared = host_baseline()
        print(
            json.dumps(
                {"host_state_checkpoint": "trusted_image_preparation_before_initialization"}
            ),
            flush=True,
        )
        print(baseline_diagnostic(self.preparation_baseline, prepared), flush=True)
        for image in self.images:
            self._prepared_image(image)
        if len(self.images) != 3 or len(self.image_provenance) != 3:
            raise RuntimeError("Incomplete prepared image manifest")
        print(
            json.dumps({"owned_prepared_images": self.image_provenance}, sort_keys=True), flush=True
        )
        initialize()
        self._capture_baseline()
        self.network_created = True
        docker(
            "network",
            "create",
            "--label=" + OWNER_LABEL + "=" + self.owner,
            "--driver=bridge",
            "--internal",
            "--ipv6",
            "--subnet=" + V4_SUBNET,
            "--gateway=" + IPAM_GATEWAYS[0],
            "--subnet=" + V6_SUBNET,
            "--gateway=" + IPAM_GATEWAYS[1],
            "--opt=com.docker.network.bridge.name=" + self.bridge,
            "--opt=com.docker.network.bridge.gateway_mode_ipv4=isolated",
            "--opt=com.docker.network.bridge.gateway_mode_ipv6=isolated",
            "--opt=com.docker.network.bridge.enable_ip_masquerade=false",
            self.name,
        )
        for role in ENDPOINTS:
            name = self._register_container(role)
            args = [
                "create",
                "--name=" + name,
                "--label=" + OWNER_LABEL + "=" + self.owner,
                "--interactive",
                "--network=" + self.name,
                "--ip=" + ENDPOINTS[role][0],
                "--ip6=" + ENDPOINTS[role][1],
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--read-only",
                "--user=65532:65532",
                "--memory=256m",
                "--memory-swap=256m",
                "--cpus=0.5",
                "--pids-limit=64",
                "--ulimit=nofile=128:128",
                "--ulimit=core=0:0",
                "--tmpfs=/tmp:rw,noexec,nosuid,size=32m",
                "--dns=127.0.0.1",
                "--dns-search=.",
                "--env=EM_TRANSPORT_ROLE=" + role,
            ]
            if role.startswith("fixture-"):
                args += ["--sysctl=net.ipv4.ip_unprivileged_port_start=443"]
            args += [self._prepared_image(self.images[1 if role == "gateway" else 0])]
            identifier = self._container_id(name, docker(*args).stdout.strip())
            self.identifiers[role] = identifier
        self.inspect(running=False)
        for role in ("fixture-a", "fixture-b", "gateway"):
            process = OwnedProcess(self.identifiers[role])
            self.processes[role] = process
            import time

            ready = process.receive(time.monotonic() + 10)
            if (
                set(ready) != {"kind", "evidence"}
                or ready["kind"] != "ready"
                or ready["evidence"].get("role") != role
            ):
                raise RuntimeError("Missing actual route/security evidence")
            print(json.dumps(ready), flush=True)
        self.inspect()

    def browser(self) -> str:
        from emailmonitor.fetching.browser_fixture import validate_applied_profile

        profile = self.root / "scripts/isolation/seccomp-browser.json"
        image = "emailmonitor-controlled-browser:" + self.suffix
        image_id = self._prepared_image(image)
        name = self._register_container("browser")
        identifier = docker(
            "create",
            "--name=" + name,
            "--label=" + OWNER_LABEL + "=" + self.owner,
            "--interactive",
            "--network=none",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--security-opt=seccomp=" + str(profile),
            "--read-only",
            "--user=1000:1000",
            "--memory=512m",
            "--memory-swap=512m",
            "--cpus=1.0",
            "--pids-limit=128",
            "--ulimit=nofile=256:256",
            "--ulimit=core=0:0",
            "--shm-size=128m",
            "--tmpfs=/tmp:rw,noexec,nosuid,size=256m",
            "--env=EM_ISOLATION_DIAGNOSTIC=synthetic-browser-only",
            "--env=HOME=/tmp/browser-home",
            "--env=XDG_CONFIG_HOME=/tmp/browser-config",
            "--env=CHROME_CONFIG_HOME=/tmp/browser-config",
            "--env=XDG_CACHE_HOME=/tmp/browser-cache",
            image_id,
            "python",
            "/app/browser_acceptance.py",
        ).stdout.strip()
        self.browser_identifier = self._container_id(name, identifier)
        browser_metadata = json.loads(docker("inspect", identifier).stdout)[0]
        if browser_metadata.get("Image") != image_id:
            raise RuntimeError("Browser image differs from prepared identity")
        host = browser_metadata["HostConfig"]
        if (
            host["NetworkMode"] != "none"
            or host["Privileged"]
            or host["CapAdd"]
            or host["CapDrop"] != ["ALL"]
            or not host["ReadonlyRootfs"]
            or host["Binds"]
            or host["IpcMode"] == "host"
            or host["PidMode"] == "host"
            or host["Memory"] != 536870912
            or host["MemorySwap"] != 536870912
            or host["PidsLimit"] != 128
            or host["ShmSize"] != 134217728
            or host["NanoCpus"] != 1000000000
        ):
            raise RuntimeError("Approved browser restrictions not present")
        validate_applied_profile(host["SecurityOpt"], json.loads(profile.read_text()))
        return identifier

    def inspect(self, running: bool = True) -> None:
        if self.baseline is None:
            raise RuntimeError("Protected baseline missing")
        network = json.loads(docker("network", "inspect", self.name).stdout)[0]
        require_owner("network", network, self.owner)
        validate_network(
            network, self.name, self.bridge, set(self.identifiers.values()) if running else set()
        )
        bridge = ip("address", "show", "dev", self.bridge)
        if len(bridge) != 1 or bridge[0].get("addr_info"):
            raise RuntimeError("Isolated bridge has a host address")
        current = host_baseline()
        if (
            current["rules"] != self.baseline["rules"]
            or current["routes"] != self.baseline["routes"]
        ):
            print(baseline_diagnostic(self.baseline, current), flush=True)
            raise RuntimeError("Isolated topology changed host routes/rules")
        for role, identifier in self.identifiers.items():
            metadata = json.loads(docker("inspect", identifier).stdout)[0]
            require_owner("container", metadata, self.owner)
            expected_image = self.images[1 if role == "gateway" else 0]
            if metadata.get("Image") != self.image_provenance[expected_image]["image_id"]:
                raise RuntimeError("Runtime image differs from prepared identity")
            validate_container(metadata, self.name, role, running)
            if running:
                endpoint = metadata["NetworkSettings"]["Networks"][self.name]
                if (
                    endpoint["NetworkID"] != network["Id"]
                    or not re.fullmatch(r"[0-9a-f]{64}", endpoint["EndpointID"])
                    or endpoint["IPPrefixLen"] != 29
                    or endpoint["GlobalIPv6PrefixLen"] != 64
                ):
                    raise RuntimeError("Operational network identity/prefix mismatch")

    def close(self) -> None:
        failures: list[str] = []
        for process in self.processes.values():
            try:
                process.close()
            except Exception:
                failures.append("process_cleanup")
        for name in self.container_names.values():
            try:
                remove_owned("container", name, self.owner)
            except Exception:
                failures.append("container_cleanup")
        if self.network_created:
            try:
                remove_owned("network", self.name, self.owner)
            except Exception:
                failures.append("network_cleanup")
        for image in self.images:
            try:
                remove_owned("image", image, self.owner)
                provenance = self.image_provenance.get(image)
                if provenance is not None and resource("image", provenance["image_id"]) is not None:
                    raise RuntimeError("Prepared owned image identity remains after cleanup")
            except Exception:
                failures.append("image_cleanup")
        self.directory.cleanup()
        current = host_baseline()
        if self.baseline is not None:
            if current != self.baseline:
                print(baseline_diagnostic(self.baseline, current), flush=True)
                failures.append("baseline_cleanup")
        elif self.network_created:
            failures.append("missing_baseline_cleanup")
        else:
            print(json.dumps({"preparation_cleanup_without_protected_phase": True}), flush=True)
        if failures:
            raise RuntimeError("Owned cleanup failed: " + ",".join(failures))
