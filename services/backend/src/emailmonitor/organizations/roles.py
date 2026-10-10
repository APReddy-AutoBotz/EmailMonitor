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
    ACQUIRE_SOURCE = "source.acquire"
    MANAGE_SOURCE_POLICY = "source.policy.manage"
    MANAGE_LIFECYCLE = "organization.lifecycle"


ROLE_CAPABILITIES: dict[Role, frozenset[Capability]] = {
    role: frozenset({Capability.READ_ORGANIZATION}) for role in Role
}
ROLE_CAPABILITIES[Role.ADMIN] |= {Capability.MANAGE_MEMBERS}
ROLE_CAPABILITIES[Role.OWNER] |= {
    Capability.MANAGE_MEMBERS,
    Capability.TRANSFER_OWNER,
    Capability.MANAGE_LIFECYCLE,
    Capability.MANAGE_SOURCE_POLICY,
}

ROLE_CAPABILITIES[Role.DATA_STEWARD] |= {Capability.MANAGE_SOURCE_POLICY}

for permitted_role in (Role.OWNER, Role.ADMIN, Role.DATA_STEWARD, Role.OPERATOR):
    ROLE_CAPABILITIES[permitted_role] |= {Capability.ACQUIRE_SOURCE}

LIFECYCLE_TRANSITIONS: dict[str, frozenset[str]] = {
    "provisioning": frozenset({"active", "offboarding"}),
    "active": frozenset({"suspended", "offboarding"}),
    "suspended": frozenset({"active", "offboarding"}),
    "offboarding": frozenset({"deleted"}),
    "deleted": frozenset(),
}
