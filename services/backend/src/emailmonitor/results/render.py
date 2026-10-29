"""Text-only bounded export serialization; no formulas, macros or external relationships."""

import csv
import io
import unicodedata
from dataclasses import dataclass
from typing import Literal
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

from emailmonitor.results.models import ExportSnapshot

MAX_INPUT = 2 * 1024 * 1024
MAX_OUTPUT = 8 * 1024 * 1024
SHEET = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE = "http://schemas.openxmlformats.org/package/2006/relationships"
CONTENT = "http://schemas.openxmlformats.org/package/2006/content-types"


class RenderDenied(ValueError):
    def __init__(
        self, reason: Literal["unsafe_csv_cell", "render_limit", "unsupported_text"]
    ) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Artifact:
    body: bytes
    extension: Literal["csv", "zip", "xlsx"]
    content_type: Literal[
        "text/csv; charset=utf-8",
        "application/zip",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ]


def safe_csv(value: str) -> str:
    # Refusal preserves original data rather than changing an observed address. Quoting
    # alone is not a formula defense, and escaping may be lost after a spreadsheet resave.
    normalized = unicodedata.normalize("NFKC", value)
    if any(
        unicodedata.category(char) in {"Cc", "Cf", "Zl", "Zp"} for char in value
    ) or normalized.lstrip().startswith(("=", "+", "-", "@")):
        raise RenderDenied("unsafe_csv_cell")
    return value


def csv_bytes(rows: list[list[str]]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    for row in rows:
        writer.writerow([safe_csv(value) for value in row])
        if buffer.tell() > MAX_OUTPUT:
            raise RenderDenied("render_limit")
    result = buffer.getvalue().encode("utf-8")
    if len(result) > MAX_OUTPUT:
        raise RenderDenied("render_limit")
    return result


def contact_rows(snapshot: ExportSnapshot) -> list[list[str]]:
    include_reuse = any(contact.observation_origin == "reused" for contact in snapshot.contacts)
    rows = [
        [
            "Association ID",
            "Batch ID",
            "Job ID",
            "Author",
            "First author",
            "Corresponding author",
            "Affiliations",
            "Observed address",
            "Normalized address",
            "Association state",
            "Identity state",
            "Evidence strength",
            "Association reason",
            "Source URL",
            "Policy version",
            "Observed at",
            "Article title",
            "Technical status",
            "Delivery status",
            "Outreach eligibility",
        ]
    ]
    for contact in snapshot.contacts:
        if contact.state not in snapshot.filters.states or contact.state == "rejected":
            raise RenderDenied("unsupported_text")
        rows.append(
            [
                str(contact.association_id),
                str(contact.batch_id),
                str(contact.job_id),
                contact.author_name or "",
                "" if contact.first_author is None else str(contact.first_author),
                "" if contact.corresponding_author is None else str(contact.corresponding_author),
                "; ".join(contact.affiliations),
                contact.raw_address,
                contact.normalized_address or "",
                contact.state,
                contact.identity_state,
                contact.evidence_strength,
                contact.association_reason,
                contact.source_url,
                str(contact.policy_version),
                contact.observed_at.isoformat(),
                contact.title or "",
                contact.technical_status,
                contact.delivery_status,
                contact.outreach_eligibility,
            ]
        )
    if include_reuse:
        rows[0].extend(["Observation origin", "Observation age at snapshot (seconds)"])
        for row, contact in zip(rows[1:], snapshot.contacts, strict=True):
            age = (snapshot.created_at - contact.observed_at).total_seconds()
            row.extend(
                [
                    "Reused" if contact.observation_origin == "reused" else "Not recorded",
                    str(int(age)) if contact.observation_origin == "reused" and age >= 0 else "",
                ]
            )
    excluded = set()
    if "affiliations" not in snapshot.optional_contact_fields:
        excluded.add(6)
    if "article_title" not in snapshot.optional_contact_fields:
        excluded.add(16)
    return [[value for index, value in enumerate(row) if index not in excluded] for row in rows]


def outcome_rows(snapshot: ExportSnapshot) -> list[list[str]]:
    include_reuse = any(item.observation_origin == "reused" for item in snapshot.article_outcomes)
    rows = [
        [
            "Job ID",
            "Item ID",
            "Source URL",
            "Processing state",
            "Reason",
            "Batch ID",
            "Completed at",
            "Inherited job",
            "Observation status",
            "Technical status",
            "Outreach eligibility",
        ]
    ]
    rows.extend(
        [
            str(item.job_id),
            str(item.item_id),
            item.source_url,
            item.state,
            item.reason,
            str(item.batch_id) if item.batch_id else "",
            item.completed_at.isoformat() if item.completed_at else "",
            str(item.inherited_job_id) if item.inherited_job_id else "",
            item.observation_status or "",
            item.technical_status,
            item.outreach_eligibility,
        ]
        for item in snapshot.article_outcomes
    )
    if include_reuse:
        rows[0].extend(
            [
                "Observation origin",
                "Original observation time",
                "Observation age at snapshot (seconds)",
            ]
        )
        for row, item in zip(rows[1:], snapshot.article_outcomes, strict=True):
            age = (
                (snapshot.created_at - item.observed_at).total_seconds()
                if item.observed_at is not None
                else -1
            )
            row.extend(
                [
                    "Reused" if item.observation_origin == "reused" else "Not recorded",
                    item.observed_at.isoformat() if item.observed_at is not None else "",
                    str(int(age)) if item.observation_origin == "reused" and age >= 0 else "",
                ]
            )
    return rows


def readme_rows(snapshot: ExportSnapshot) -> list[list[str]]:
    return [
        ["EmailMonitor", "Synthetic/offline export snapshot"],
        ["Organization", str(snapshot.organization_id)],
        ["Export", str(snapshot.export_id)],
        ["Requested by", str(snapshot.requested_by)],
        ["Purpose", snapshot.purpose],
        ["Created at", snapshot.created_at.isoformat()],
        ["Expires at", snapshot.expires_at.isoformat()],
        ["Filters", snapshot.filters.model_dump_json()],
        ["Contacts", str(len(snapshot.contacts))],
        ["Article outcomes", str(len(snapshot.article_outcomes))],
        ["Use state", "Observed research records; no mailbox validation or outreach approval"],
        ["Identity", "Article-local unresolved identity; no global person registry"],
        [
            "Download",
            "Current source, membership, retention and data revision must still authorize release",
        ],
        [
            "CSV",
            "Formula/control-leading cells refuse; XLSX stores literal text without formula nodes",
        ],
    ]


def xml_bytes(element: ET.Element) -> bytes:
    result = ET.tostring(element, encoding="utf-8", xml_declaration=True)
    assert isinstance(result, bytes)
    return result


def column(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def worksheet(rows: list[list[str]]) -> bytes:
    root = ET.Element("worksheet", {"xmlns": SHEET})
    data = ET.SubElement(root, "sheetData")
    text_bytes = 0
    for ordinal, values in enumerate(rows, 1):
        row = ET.SubElement(data, "row", {"r": str(ordinal)})
        for index, value in enumerate(values, 1):
            if len(value) > 32767 or any(
                not (
                    char in "\t\n\r"
                    or 0x20 <= ord(char) <= 0xD7FF
                    or 0xE000 <= ord(char) <= 0xFFFD
                    or 0x10000 <= ord(char) <= 0x10FFFF
                )
                for char in value
            ):
                raise RenderDenied("unsupported_text")
            text_bytes += len(value.encode("utf-8")) + 128
            if text_bytes > MAX_OUTPUT:
                raise RenderDenied("render_limit")
            cell = ET.SubElement(row, "c", {"r": f"{column(index)}{ordinal}", "t": "inlineStr"})
            inline = ET.SubElement(cell, "is")
            ET.SubElement(inline, "t", {"xml:space": "preserve"}).text = value
    result = xml_bytes(root)
    if len(result) > MAX_OUTPUT:
        raise RenderDenied("render_limit")
    return result


def package(parts: dict[str, bytes]) -> bytes:
    if sum(map(len, parts.values())) > MAX_OUTPUT:
        raise RenderDenied("render_limit")
    buffer = io.BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        for name, body in parts.items():
            archive.writestr(name, body)
    result = buffer.getvalue()
    if len(result) > MAX_OUTPUT:
        raise RenderDenied("render_limit")
    return result


def xlsx_bytes(tables: list[tuple[str, list[list[str]]]]) -> bytes:
    types = ET.Element("Types", {"xmlns": CONTENT})
    ET.SubElement(
        types,
        "Default",
        {
            "Extension": "rels",
            "ContentType": "application/vnd.openxmlformats-package.relationships+xml",
        },
    )
    ET.SubElement(types, "Default", {"Extension": "xml", "ContentType": "application/xml"})
    ET.SubElement(
        types,
        "Override",
        {
            "PartName": "/xl/workbook.xml",
            "ContentType": (
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
            ),
        },
    )
    relationships = ET.Element("Relationships", {"xmlns": PACKAGE})
    ET.SubElement(
        relationships,
        "Relationship",
        {"Id": "rId1", "Type": f"{REL}/officeDocument", "Target": "xl/workbook.xml"},
    )
    workbook = ET.Element("workbook", {"xmlns": SHEET, "xmlns:r": REL})
    sheets = ET.SubElement(workbook, "sheets")
    links = ET.Element("Relationships", {"xmlns": PACKAGE})
    parts: dict[str, bytes] = {}
    for ordinal, (name, rows) in enumerate(tables, 1):
        ET.SubElement(
            sheets,
            "sheet",
            {"name": name, "sheetId": str(ordinal), "r:id": f"rId{ordinal}"},
        )
        path = f"xl/worksheets/sheet{ordinal}.xml"
        ET.SubElement(
            links,
            "Relationship",
            {
                "Id": f"rId{ordinal}",
                "Type": f"{REL}/worksheet",
                "Target": f"worksheets/sheet{ordinal}.xml",
            },
        )
        ET.SubElement(
            types,
            "Override",
            {
                "PartName": "/" + path,
                "ContentType": (
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"
                ),
            },
        )
        parts[path] = worksheet(rows)
    parts.update(
        {
            "[Content_Types].xml": xml_bytes(types),
            "_rels/.rels": xml_bytes(relationships),
            "xl/workbook.xml": xml_bytes(workbook),
            "xl/_rels/workbook.xml.rels": xml_bytes(links),
        }
    )
    return package(parts)


def render(snapshot: ExportSnapshot) -> Artifact:
    if len(snapshot.model_dump_json().encode()) > MAX_INPUT:
        raise RenderDenied("render_limit")
    contacts = contact_rows(snapshot)
    outcomes = outcome_rows(snapshot)
    readme = readme_rows(snapshot)
    if snapshot.format == "xlsx":
        tables = [("Contacts", contacts)]
        if snapshot.include_article_outcomes:
            tables.append(("Article outcomes", outcomes))
        tables.append(("Readme", readme))
        return Artifact(
            xlsx_bytes(tables),
            "xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    body = csv_bytes(contacts)
    if not snapshot.include_article_outcomes:
        return Artifact(body, "csv", "text/csv; charset=utf-8")
    parts = {
        "contacts.csv": body,
        "article-outcomes.csv": csv_bytes(outcomes),
        "readme.txt": "\n".join(f"{key}: {value}" for key, value in readme).encode(),
    }
    return Artifact(package(parts), "zip", "application/zip")
