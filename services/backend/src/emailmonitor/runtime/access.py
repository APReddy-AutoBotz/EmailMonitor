"""Explicit human or service transaction providers for shared domain operations."""

from emailmonitor.organizations.database import Database, TenantContext
from emailmonitor.runtime.authority import ServiceWork
from emailmonitor.runtime.database import ServiceContext, ServiceDatabase

type WorkDatabase = Database | ServiceDatabase
type WorkAuthority = str | ServiceWork
type WorkContext = TenantContext | ServiceContext
