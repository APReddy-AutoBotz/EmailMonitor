"""Immutable synthetic IPAM; these literals must never be routed externally."""

V4_SUBNET = "8.8.8.0/29"
V6_SUBNET = "2001:4860:ffff:ee00::/64"
IPAM_GATEWAYS = ("8.8.8.1", "2001:4860:ffff:ee00::1")
ENDPOINTS = {
    "gateway": ("8.8.8.2", "2001:4860:ffff:ee00::2"),
    "fixture-a": ("8.8.8.3", "2001:4860:ffff:ee00::3"),
    "fixture-b": ("8.8.8.4", "2001:4860:ffff:ee00::4"),
}
HOST = "synthetic.publisher.example"
