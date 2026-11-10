"""Optional Kernel browser inspection for a user-selected public product page.

This helper only reads page title, description, and a short visible-text sample.
It does not click, sign in, fill forms, or purchase anything.
"""

import ipaddress
import socket
from urllib.parse import urlsplit


class KernelInspectorError(RuntimeError):
    pass


def _validate_public_https_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise KernelInspectorError("Provide a public HTTPS product URL")
    host = parsed.hostname.lower().rstrip(".")
    if host in {"localhost", "localhost.localdomain"} or host.endswith((".localhost", ".local", ".internal")):
        raise KernelInspectorError("Local or internal URLs are not allowed")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)}
    except OSError as exc:
        raise KernelInspectorError("The product page host could not be resolved") from exc
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise KernelInspectorError("The product page must resolve to a public internet address")


async def inspect_product_page(url: str) -> dict[str, str]:
    _validate_public_https_url(url)
    try:
        from kernel import AsyncKernel
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise KernelInspectorError("Install the optional Kernel and Playwright packages first") from exc

    kernel = AsyncKernel()
    session = None
    browser = None
    try:
        async with async_playwright() as playwright:
            session = await kernel.browsers.create(headless=True, timeout_seconds=60)
            browser = await playwright.chromium.connect_over_cdp(session.cdp_ws_url)
            context = browser.contexts[0]
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            title = (await page.title())[:250]
            description = await page.locator('meta[name="description"]').get_attribute("content")
            if not description:
                description = await page.locator('meta[property="og:description"]').get_attribute("content")
            visible_text = ""
            try:
                visible_text = (await page.locator("body").inner_text(timeout=5000))[:2500]
            except Exception:
                pass
            return {
                "url": page.url,
                "title": title,
                "description": (description or "")[:700],
                "visible_text": visible_text,
                "note": "Page details are for review; confirm current price and availability before checkout.",
            }
    except KernelInspectorError:
        raise
    except Exception as exc:
        raise KernelInspectorError(f"Kernel could not inspect this page: {exc}") from exc
    finally:
        if browser is not None:
            try:
                await browser.close()
            except Exception:
                pass
        if session is not None:
            try:
                await kernel.browsers.delete_by_id(session.session_id)
            except Exception:
                pass
