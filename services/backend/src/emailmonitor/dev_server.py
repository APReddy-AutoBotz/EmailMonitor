"""Interactive local development and demonstration server for EmailMonitor UI.

Provides authentic synthetic fixtures, session authentication, and mock
academic Open Access extraction datasets for local exploration.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from emailmonitor.discovery.mesh_search import match_mesh_terms
from emailmonitor.discovery.openaccess_orchestrator import OpenAccessOrchestrator

app = FastAPI(title="EmailMonitor Dev & Preview Server", version="0.1.0")

# Allow loopback CORS and cookie credentials
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ORG_ID = "00000000-0000-0000-0000-000000000001"
USER_ID = "11111111-1111-1111-1111-111111111111"
CSRF_TOKEN = "dev-operator-csrf-token-2026"
COOKIE = "__Host-emailmonitor_session"
CSRF_COOKIE = "__Host-emailmonitor_csrf"

SAMPLE_CONTACTS = [
    {
        "organization_id": ORG_ID,
        "job_id": "job-oa-001",
        "batch_id": "batch-oa-001",
        "association_id": "assoc-oa-001",
        "revision": 1,
        "author_id": "author-001",
        "author_name": "Dr. Sarah L. Chen",
        "raw_address": "sarah.chen@stanford.edu",
        "normalized_address": "sarah.chen@stanford.edu",
        "state": "accepted",
        "first_author": True,
        "corresponding_author": True,
        "affiliations": ["Department of Bioengineering, Stanford University, Stanford, CA, USA"],
        "title": "High-fidelity CRISPR-Cas9 genome editing in human hematopoietic stem cells",
        "evidence_ids": ["ev-oa-001"],
        "evidence_strength": "verified_jats_xml",
        "source_url": "https://europepmc.org/article/PMC/PMC7144853",
        "policy_version": 1,
        "observed_at": "2026-11-10T14:22:00Z",
        "identity_state": "resolved",
        "syntax_status": "valid",
        "technical_status": "verified_mx",
        "delivery_status": "deliverable",
        "outreach_eligibility": "eligible",
    },
    {
        "organization_id": ORG_ID,
        "job_id": "job-oa-001",
        "batch_id": "batch-oa-002",
        "association_id": "assoc-oa-002",
        "revision": 1,
        "author_id": "author-002",
        "author_name": "Prof. Marcus Vance",
        "raw_address": "m.vance@oxford.ac.uk",
        "normalized_address": "m.vance@oxford.ac.uk",
        "state": "accepted",
        "first_author": False,
        "corresponding_author": True,
        "affiliations": ["Nuffield Department of Medicine, University of Oxford, Oxford, UK"],
        "title": "Immunogenicity profiling of multi-epitope mRNA vaccine formulations",
        "evidence_ids": ["ev-oa-002"],
        "evidence_strength": "verified_jats_xml",
        "source_url": "https://europepmc.org/article/PMC/PMC8432119",
        "policy_version": 1,
        "observed_at": "2026-11-10T15:10:00Z",
        "identity_state": "resolved",
        "syntax_status": "valid",
        "technical_status": "verified_mx",
        "delivery_status": "deliverable",
        "outreach_eligibility": "eligible",
    },
    {
        "organization_id": ORG_ID,
        "job_id": "job-oa-002",
        "batch_id": "batch-oa-003",
        "association_id": "assoc-oa-003",
        "revision": 1,
        "author_id": "author-003",
        "author_name": "Elena Rostova",
        "raw_address": "e.rostova@biomed.ethz.ch",
        "normalized_address": "e.rostova@biomed.ethz.ch",
        "state": "needs_review",
        "first_author": True,
        "corresponding_author": False,
        "affiliations": ["Institute of Molecular Health Sciences, ETH Zürich, Zurich, Switzerland"],
        "title": "Synthetic biology circuits for autonomous cellular sensing",
        "evidence_ids": ["ev-oa-003"],
        "evidence_strength": "candidate_heuristic",
        "source_url": "https://doi.org/10.1016/j.biomaterials.2026.121450",
        "policy_version": 1,
        "observed_at": "2026-11-11T09:45:00Z",
        "identity_state": "unresolved",
        "syntax_status": "valid",
        "technical_status": "untested",
        "delivery_status": "unknown",
        "outreach_eligibility": "pending_review",
    },
]

SAMPLE_JOBS = [
    {
        "id": "job-oa-001",
        "kind": "extraction",
        "state": "completed",
        "row_version": 4,
        "generation": 1,
        "created_at": "2026-11-10T14:00:00Z",
        "discovery_complete": True,
        "request": {
            "query": "CRISPR-Cas9 gene therapy human trials",
            "sources": ["openalex", "europe_pmc"],
            "max_articles": 50,
        },
    },
    {
        "id": "job-oa-002",
        "kind": "extraction",
        "state": "active",
        "row_version": 2,
        "generation": 1,
        "created_at": "2026-11-11T09:30:00Z",
        "discovery_complete": False,
        "request": {
            "query": "mRNA lipid nanoparticles oncology",
            "sources": ["europe_pmc"],
            "max_articles": 25,
        },
    },
]


@app.get("/favicon.ico")
def favicon() -> Response:
    return Response(content=b"", media_type="image/x-icon")


@app.get("/healthz")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/capabilities")
def capabilities() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "implementation_stage": "tenant_foundation",
        "extraction_implemented": True,
        "live_sources_enabled": True,
        "outbound_email_enabled": False,
        "external_ai_enabled": False,
        "tenant_data_api_available": True,
    }


@app.get("/api/v1/auth/session")
def session(request: Request, response: Response) -> dict[str, Any]:
    # Set dev cookies
    response.set_cookie(COOKIE, "dev-session-token", httponly=True, samesite="strict")
    response.set_cookie(CSRF_COOKIE, CSRF_TOKEN, httponly=True, samesite="strict")
    return {
        "identity_id": USER_ID,
        "csrf_token": CSRF_TOKEN,
        "synthetic_only": True,
        "production_enabled": False,
        "memberships": [
            {
                "organization_id": ORG_ID,
                "role": "owner",
                "organization_status": "active",
                "capabilities": [
                    "organization.read",
                    "results.export",
                    "association.review",
                    "membership.manage",
                    "owner.transfer",
                    "source.acquire",
                    "source.policy.manage",
                    "organization.lifecycle",
                ],
            }
        ],
    }


@app.get("/api/v1/auth/start")
def auth_start() -> Response:
    # Auto-redirect back to frontend with state & code
    return JSONResponse(
        {"status": "ok", "message": "Development session already authenticated"}
    )


@app.post("/api/v1/auth/logout")
def auth_logout(response: Response) -> Response:
    response.delete_cookie(COOKIE)
    response.delete_cookie(CSRF_COOKIE)
    return Response(status_code=204)


@app.get("/api/v1/runtime-profile")
def runtime_profile() -> dict[str, Any]:
    return {
        "profile": "controlled-xml-service-reference",
        "production_ready": False,
        "xml_available": True,
        "pdf_available": False,
        "dynamic_browser_available": False,
        "live_sources_available": False,
    }


# Scoped organization endpoints
@app.get("/api/v1/organizations/{org_id}")
def organization_detail(org_id: str) -> dict[str, Any]:
    return {
        "id": org_id,
        "display_name": "Open Access Publications Group (Dev Workspace)",
        "status": "active",
        "region": "us-west-2",
        "timezone": "UTC",
        "row_version": 1,
    }


@app.get("/api/v1/organizations/{org_id}/configuration")
def organization_config(org_id: str) -> dict[str, Any]:
    return {
        "organization_id": org_id,
        "revision": 1,
        "entitlements": {
            "max_running_jobs": 5,
            "max_parallel_parse": 8,
            "max_parallel_export": 2,
            "max_parallel_browser": 1,
            "max_articles_per_job": 1000,
            "monthly_resolution_units": 50000,
            "max_export_bytes": 50000000,
            "browser_enabled": True,
            "exports_enabled": True,
        },
        "branding": {
            "label": "Open Access Academic Suite",
            "accent_color": "#d97706",
            "logo_reference": None,
        },
        "support_reference": "dev-support@emailmonitor.internal",
        "deployment_mode": "synthetic_offline",
        "billing_implemented": False,
        "exceptional_support_grants_available": False,
    }


@app.get("/api/v1/organizations/{org_id}/jobs")
def list_jobs(org_id: str) -> list[dict[str, Any]]:
    return SAMPLE_JOBS


@app.get("/api/v1/organizations/{org_id}/jobs/{job_id}")
def get_job(org_id: str, job_id: str) -> dict[str, Any]:
    for j in SAMPLE_JOBS:
        if j["id"] == job_id:
            return j
    return SAMPLE_JOBS[0]


@app.get("/api/v1/organizations/{org_id}/jobs/{job_id}/progress")
def get_job_progress(org_id: str, job_id: str) -> dict[str, Any]:
    return {
        "organization_id": org_id,
        "job_id": job_id,
        "state": "completed" if job_id == "job-oa-001" else "active",
        "revision": 3,
        "generation": 1,
        "discovery_pages": 4,
        "source_reported_total": 42,
        "unique_articles": 38,
        "duplicates": 4,
        "discovery_complete": True,
        "completeness": "complete",
        "discovery_stop_reason": "quota_fulfilled",
        "counts": {
            "discovered": 38,
            "pending": 0,
            "active": 0,
            "retry_wait": 0,
            "terminal": 38,
            "by_outcome": {"accepted": 35, "no_contact": 3},
        },
        "accepted_associations": 35,
        "review_needed_associations": 2,
        "progress_percent": 100 if job_id == "job-oa-001" else 65,
        "last_sequence": 42,
    }


@app.get("/api/v1/organizations/{org_id}/jobs/{job_id}/progress/items")
def get_job_items(org_id: str, job_id: str) -> list[dict[str, Any]]:
    return [
        {
            "id": "item-001",
            "state": "completed",
            "reason": "jats_xml_extracted",
            "work_kind": "jats_xml",
            "attempts": 1,
            "batch_id": "batch-oa-001",
        },
        {
            "id": "item-002",
            "state": "completed",
            "reason": "jats_xml_extracted",
            "work_kind": "jats_xml",
            "attempts": 1,
            "batch_id": "batch-oa-002",
        },
    ]


@app.get("/api/v1/organizations/{org_id}/jobs/{job_id}/discovery")
def get_job_discovery(org_id: str, job_id: str) -> dict[str, Any]:
    return {
        "job_id": job_id,
        "query": "CRISPR-Cas9 gene therapy human trials",
        "sources": ["Europe PMC", "OpenAlex"],
        "matched_works": 42,
    }


@app.get("/api/v1/organizations/{org_id}/contacts")
def list_contacts(org_id: str, state: str = "accepted") -> dict[str, Any]:
    items = [c for c in SAMPLE_CONTACTS if state == "all" or c["state"] == state]
    if not items:
        items = SAMPLE_CONTACTS
    return {"items": items, "next_cursor": None}


@app.get("/api/v1/organizations/{org_id}/contacts/{assoc_id}")
def get_contact_detail(org_id: str, assoc_id: str, batch_id: str = "") -> dict[str, Any]:
    for c in SAMPLE_CONTACTS:
        if c["association_id"] == assoc_id:
            return c
    return SAMPLE_CONTACTS[0]


@app.get("/api/v1/organizations/{org_id}/association-batches/{batch_id}")
def get_batch(org_id: str, batch_id: str) -> dict[str, Any]:
    return {
        "parser_version": "jats-expat-v1",
        "observation_route": "article_xml",
        "observation_status": "observed",
        "article_id": "PMC7144853",
        "candidates": [
            {
                "id": "cand-001",
                "address": {
                    "raw_address": "sarah.chen@stanford.edu",
                    "normalized_address": "sarah.chen@stanford.edu",
                    "syntax_status": "valid",
                },
                "normalization_collision": False,
            }
        ],
        "authors": [
            {
                "id": "auth-001",
                "display_name": "Dr. Sarah L. Chen",
                "position": 1,
                "first": True,
                "corresponding": True,
                "affiliations": ["Department of Bioengineering, Stanford University"],
            }
        ],
        "evidence": [
            {
                "id": "ev-oa-001",
                "locator": "/article/front/article-meta/author-notes/corresp[1]",
                "excerpt": "*Correspondence: sarah.chen@stanford.edu (S.L.C.)",
                "method": "xml_corresp_node",
                "page": None,
                "anchor": None,
                "region": None,
                "region_precision": None,
            }
        ],
        "associations": [
            {
                "id": "assoc-oa-001",
                "revision": 1,
                "author_id": "auth-001",
                "evidence_ids": ["ev-oa-001"],
                "state": "accepted",
            }
        ],
    }


@app.get("/api/v1/organizations/{org_id}/evidence/{ev_id}")
def get_evidence(org_id: str, ev_id: str, batch_id: str = "") -> dict[str, Any]:
    return {
        "organization_id": org_id,
        "batch_id": batch_id or "batch-oa-001",
        "source_url": "https://europepmc.org/article/PMC/PMC7144853",
        "content_digest": "sha256-e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "citation": {
            "id": ev_id,
            "locator": "/article/front/article-meta/author-notes/corresp[1]",
            "excerpt": "*Correspondence: Dr. Sarah L. Chen <sarah.chen@stanford.edu>",
            "method": "xml_corresp_node",
            "page": None,
            "anchor": None,
            "region": None,
            "region_precision": None,
        },
        "raw_document_available": False,
    }


@app.get("/api/v1/organizations/{org_id}/article-outcomes")
def list_outcomes(org_id: str) -> dict[str, Any]:
    return {
        "items": [
            {
                "organization_id": org_id,
                "completed_at": "2026-11-10T14:22:00Z",
                "inherited_job_id": None,
                "job_id": "job-oa-001",
                "item_id": "item-001",
                "source_url": "https://europepmc.org/article/PMC/PMC7144853",
                "state": "completed",
                "reason": "jats_xml_extracted",
                "batch_id": "batch-oa-001",
                "observation_status": "observed",
                "technical_status": "verified_mx",
                "outreach_eligibility": "eligible",
            }
        ],
        "next_cursor": None,
    }


@app.get("/api/v1/organizations/{org_id}/sources")
def list_sources(org_id: str) -> list[dict[str, Any]]:
    return [
        {
            "source_id": "synthetic-publisher",
            "display_name": "Synthetic Publisher Reference",
            "adapter": "synthetic_html",
            "platform_enabled": True,
        },
        {
            "source_id": "europe-pmc",
            "display_name": "Europe PMC (Open Access JATS XML)",
            "adapter": "europe_pmc_rest",
            "platform_enabled": True,
        },
        {
            "source_id": "openalex",
            "display_name": "OpenAlex Works API",
            "adapter": "openalex_rest",
            "platform_enabled": True,
        },
    ]


@app.get("/api/v1/organizations/{org_id}/sources/synthetic-publisher/policies")
def list_policies(org_id: str) -> list[dict[str, Any]]:
    return [
        {
            "version": 1,
            "row_version": 1,
            "state": "approved",
            "valid_until": "2027-12-31T23:59:59Z",
            "allowed_hosts": ["europepmc.org", "api.openalex.org", "synthetic.publisher.example"],
            "allowed_operations": ["jats_xml_fetch", "search_metadata", "pdf_direct"],
            "export_contacts_allowed": True,
        }
    ]


@app.get("/api/v1/organizations/{org_id}/exports")
def list_exports(org_id: str) -> list[dict[str, Any]]:
    return [
        {
            "id": "exp-oa-001",
            "requested_by": USER_ID,
            "format": "csv",
            "state": "completed",
            "reason": "instantly_ai_campaign",
            "revision": 1,
            "contacts": 35,
            "article_outcomes": 38,
            "download_available": True,
            "created_at": "2026-11-10T16:00:00Z",
            "expires_at": "2026-11-17T16:00:00Z",
        }
    ]


@app.post("/api/v1/organizations/{org_id}/exports/preview")
def preview_export(org_id: str, request: Request) -> dict[str, Any]:
    return {
        "contacts": 35,
        "article_outcomes": 38,
        "counts_may_change": True,
        "excluded_reasons": ["suppressed_by_rule", "unresolved_identity"],
        "optional_contact_fields": ["affiliations", "article_title"],
    }


@app.get("/api/v1/organizations/{org_id}/usage")
def get_usage(org_id: str) -> dict[str, Any]:
    return {
        "fixture_probe_initialized": True,
        "fixture_probe_maximum": 50000,
        "fixture_probe_reserved": 120,
        "fixture_probe_used": 1450,
        "retained_extraction_effects": 35,
        "cost": None,
    }


@app.get("/api/v1/organizations/{org_id}/resource-usage")
def get_resource_usage(org_id: str) -> dict[str, Any]:
    return {
        "organization_id": org_id,
        "period_start": "2026-11-01T00:00:00Z",
        "settled_resolution_units": 1450,
        "reserved_resolution_units": 120,
        "monthly_unit_limit": 50000,
        "waiting_units": {"parse": 0, "export": 0},
        "active_units": {"parse": 2},
        "source_resource_attempts": 42,
        "billing_implemented": False,
        "synthetic_only": True,
    }


@app.get("/api/v1/organizations/{org_id}/audit")
def get_audit(org_id: str) -> dict[str, Any]:
    return {
        "items": [
            {
                "id": "aud-001",
                "actor_id": USER_ID,
                "action": "export.create",
                "resource_id": "exp-oa-001",
                "occurred_at": "2026-11-10T16:00:00Z",
            },
            {
                "id": "aud-002",
                "actor_id": USER_ID,
                "action": "job.launch",
                "resource_id": "job-oa-001",
                "occurred_at": "2026-11-10T14:00:00Z",
            },
        ],
        "next_cursor": None,
    }


@app.get("/api/v1/organizations/{org_id}/members")
def get_members(org_id: str) -> list[dict[str, Any]]:
    return [
        {
            "identity_id": USER_ID,
            "role": "owner",
            "status": "active",
            "row_version": 1,
        }
    ]


@app.post("/api/v1/organizations/{org_id}/open-access/discover")
async def open_access_discover(org_id: str, request: Request) -> dict[str, Any]:
    body = await request.json()
    query = body.get("query", "CRISPR")
    source = body.get("source", "auto")
    max_results = int(body.get("max_results", 25))
    target_roles = body.get("target_roles", "both")

    orchestrator = OpenAccessOrchestrator()
    result = orchestrator.discover_and_extract(
        query=query,
        source=source,
        max_results=max_results,
        target_roles=target_roles,
    )
    return result.model_dump()


@app.post("/api/v1/organizations/{org_id}/open-access/export")
async def open_access_export(org_id: str, request: Request) -> Response:
    body = await request.json()
    query = body.get("query", "CRISPR")
    source = body.get("source", "auto")
    preset = body.get("preset", "instantly")

    orchestrator = OpenAccessOrchestrator()
    result = orchestrator.discover_and_extract(query=query, source=source)

    if preset == "smartlead":
        content = result.export_smartlead_csv()
        filename = "emailmonitor-smartlead-export.csv"
    else:
        content = result.export_instantly_csv()
        filename = "emailmonitor-instantly-export.csv"

    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/v1/organizations/{org_id}/open-access/mesh")
def get_mesh_suggestions(org_id: str, q: str = "") -> list[dict[str, Any]]:
    matches = match_mesh_terms(q)
    return [m.model_dump() for m in matches]
