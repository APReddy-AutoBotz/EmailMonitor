"""XML keyboard steps inside the installed HTTPS login and asset-verified guest."""

import asyncio
import re
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from playwright.async_api import expect

if TYPE_CHECKING:
    from operator_ui_acceptance import activate, focus, select_index, type_text
else:
    from operator_ui_helpers import activate, focus, select_index, type_text


def evidence_destination(pdf: bool) -> str:
    """The fixed PDF fixture is accepted already; XML awaits explicit review."""
    return "Contacts" if pdf else "Review queue"


async def xml_journey(
    page: Any,
    channel: Any,
    setup: dict[str, Any],
    checkpoint: Callable[[str], None],
    login: Callable[[], Awaitable[None]],
    download_seen: asyncio.Event,
    export_checkpoint: Callable[[str, str | None], None],
) -> str:
    pdf = setup.get("journey") == "installed-authored-pdf"
    direct = setup.get("direct_article_url")
    if type(direct) is not bool:
        raise ValueError("Fixed installed XML input required")
    if pdf and direct is not True:
        raise ValueError("Authored PDF requires the fixed direct input")
    addresses = (
        ("alex.chen@example.org",)
        if pdf
        else ("Second@example.org",)
        if direct
        else ("Second@example.org", "beta@example.org")
    )
    checkpoint("source_review")
    await activate(page, page.get_by_role("button", name="Sources", exact=True))
    profile = page.get_by_role("combobox", name="Synthetic policy profile", exact=True)
    await expect(profile).to_have_value("html")
    await select_index(page, profile, 3 if pdf else 1)
    await expect(profile).to_have_value("pdf" if pdf else "xml")
    await activate(
        page,
        page.get_by_role("button", name="Request synthetic source review", exact=True),
    )
    await page.get_by_role("button", name="Approve synthetic policy", exact=True).wait_for()
    # Approval refers to the persisted proposal, not this now-changed selection.
    await select_index(page, profile, 0)
    await activate(page, page.get_by_role("button", name="Approve synthetic policy", exact=True))
    dialog = page.get_by_role("dialog")
    await expect(dialog).to_contain_text("parse_fixture_pdf" if pdf else "fetch_xml")
    await expect(dialog).to_contain_text('"raw_hours":0,"excerpt_days":30,"contact_days":90')
    await activate(
        page,
        page.get_by_role("button", name="Confirm approve synthetic policy", exact=True),
    )
    await dialog.wait_for(state="hidden")
    checkpoint("url_plan" if direct else "keyword_plan")
    await activate(page, page.get_by_role("button", name="New extraction", exact=True))
    if direct:
        await activate(page, page.get_by_role("button", name="URL", exact=True))
        await type_text(
            page,
            page.get_by_label("Search-results or article URL", exact=True),
            "https://synthetic.publisher.example/article-a.pdf"
            if pdf
            else "https://synthetic.publisher.example/provider-doi.xml",
        )
    else:
        await type_text(
            page,
            page.get_by_label("Keyword", exact=True),
            "Controlled provider journey",
        )
    if pdf:
        toggle = page.get_by_role(
            "checkbox", name="Allow authored local PDF fixtures (no downloads)", exact=True
        )
        await expect(toggle).not_to_be_checked()
        await focus(page, toggle)
        await page.keyboard.press("Space")
        await expect(toggle).to_be_checked()
    await activate(page, page.get_by_role("button", name="Create and validate plan", exact=True))
    await page.get_by_role("region", name="Server source plan").wait_for()
    await activate(page, page.get_by_role("button", name="Launch extraction", exact=True))
    job = (await page.get_by_role("heading", name=re.compile(r"^Job [0-9a-f-]{36}$")).inner_text())[
        4:
    ]
    checkpoint("url_worker" if direct else "keyword_worker")
    await channel.request({"kind": "control", "action": "publish"})
    await page.goto(setup["api"], wait_until="domcontentloaded")
    await page.get_by_role("link", name="Sign in with configured identity", exact=True).wait_for()
    await login()
    await activate(page, page.get_by_role("button", name="Jobs", exact=True))
    await activate(page, page.get_by_role("button", name="Open job " + job, exact=True))
    # XML includes real protected admissions spaced five seconds apart and isolated parsing.
    async with asyncio.timeout(75):
        await page.get_by_text("completed", exact=True).wait_for(state="visible", timeout=75000)
    await channel.request({"kind": "control", "action": "wait_jobs"})
    checkpoint("evidence_review")
    await activate(page, page.get_by_role("button", name=evidence_destination(pdf), exact=True))
    for address in addresses:
        row = page.get_by_role("row").filter(has_text=address)
        await expect(row).to_have_count(1)
        await activate(page, row.get_by_role("button", name="Evidence and review", exact=True))
        await page.get_by_role("heading", name="Actual retained citation", exact=True).wait_for()
        quality = page.get_by_role("region", name="Article observation quality", exact=True)
        await expect(quality).to_contain_text("Retained parser outcome:")
        await expect(quality).to_contain_text("does not resolve affiliation uncertainty")
        await expect(quality).not_to_contain_text("reasons are not recorded for this route")
        if pdf:
            await expect(page.get_by_role("dialog")).to_contain_text("PDF page 2")
            await expect(page.get_by_role("dialog")).to_contain_text("full_cropbox_not_glyph_bbox")
            await expect(page.get_by_role("dialog")).to_contain_text("pdf_text")
        await type_text(
            page,
            page.get_by_label("Reason", exact=True),
            "Installed authored PDF evidence review"
            if pdf
            else "Installed controlled XML evidence review",
        )
        await activate(page, page.get_by_role("button", name="Save review", exact=True))
        await page.get_by_role("dialog").wait_for(state="hidden")
    await activate(page, page.get_by_role("button", name="Contacts", exact=True))
    for address in addresses:
        await expect(page.get_by_role("row").filter(has_text=address)).to_have_count(1)
    if direct:
        await expect(page.get_by_role("row").filter(has_text="beta@example.org")).to_have_count(0)
    checkpoint("export_preview")
    export_checkpoint("navigate", None)
    await activate(page, page.get_by_role("button", name="Exports", exact=True))
    for index, format_name in enumerate(("xlsx", "csv")):
        export_checkpoint("format", format_name)
        await select_index(page, page.get_by_label(re.compile(r"^Format")), index)
        export_checkpoint("preview_activate", format_name)
        await activate(
            page,
            page.get_by_role("button", name="Preview eligible export counts", exact=True),
        )
        export_checkpoint("preview_wait", format_name)
        await page.get_by_role("region", name="Current export preview").wait_for()
        export_checkpoint("create", format_name)
        await activate(
            page,
            page.get_by_role("button", name="Create asynchronous export", exact=True),
        )
        row = page.get_by_role("row").filter(has_text=" · " + format_name)
        export_checkpoint("row_wait", format_name)
        await row.wait_for()
        export_checkpoint("ready_wait", format_name)
        async with asyncio.timeout(30):
            while not await row.get_by_role("button", name="Download", exact=True).is_enabled():
                await asyncio.sleep(0.4)
                export_checkpoint("refresh", format_name)
                await activate(
                    page,
                    page.get_by_role("button", name="Refresh current view", exact=True),
                )
                export_checkpoint("ready_wait", format_name)
        download_seen.clear()
        export_checkpoint("download_activate", format_name)
        await activate(page, row.get_by_role("button", name="Download", exact=True))
        export_checkpoint("download_wait", format_name)
        await asyncio.wait_for(download_seen.wait(), timeout=5)
    export_checkpoint("verify", None)
    await channel.request({"kind": "control", "action": "wait_exports"})
    if not isinstance(job, str):
        raise RuntimeError("Installed XML job identity missing")
    return job
