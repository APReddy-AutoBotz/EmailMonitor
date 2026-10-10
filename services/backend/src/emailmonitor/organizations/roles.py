from enum import StrEnum


class Role(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    DATA_STEWARD = "data_steward"
    OPERATOR = "operator"
    REVIEWER = "reviewer"
    VIEWER = "viewer"


class Capability(StrEnum):
    READ_ORGANIZATION = "organization.read"
    MANAGE_MEMBERS = "membership.manage"
    TRANSFER_OWNER = "owner.transfer"
    MANAGE_LIFECYCLE = "organization.lifecycle"


ROLE_CAPABILITIES: dict[Role, frozenset[Capability]] = {
    role: frozenset({Capability.READ_ORGANIZATION}) for role in Role
}
ROLE_CAPABILITIES[Role.ADMIN] |= {Capability.MANAGE_MEMBERS}
ROLE_CAPABILITIES[Role.OWNER] |= {
    Capability.MANAGE_MEMBERS,
    Capability.TRANSFER_OWNER,
    Capability.MANAGE_LIFECYCLE,
}

LIFECYCLE_TRANSITIONS: dict[str, frozenset[str]] = {
    "provisioning": frozenset({"active", "offboarding"}),
    "active": frozenset({"suspended", "offboarding"}),
    "suspended": frozenset({"active", "offboarding"}),
    "offboarding": frozenset({"deleted"}),
    "deleted": frozenset(),
}
