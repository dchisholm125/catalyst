"""Chromium component checks without navigation or network access.

Templates come from HTTP TestClient. CSS/JS are inserted directly; history writes
are captured, not exercised as real browser navigation. This does not replace
browser_smoke.py's full live-server test.
"""
import argparse
from pathlib import Path
import re
import shutil
import sys
import tempfile
import json

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fastapi.testclient import TestClient
from catalyst.app import create_app, Settings
from catalyst.db import issue_human
from catalyst.cli import seed


def main():
    from playwright.sync_api import sync_playwright
    parser = argparse.ArgumentParser()
    parser.add_argument("--browser", default=shutil.which("chromium"))
    parser.add_argument("--screenshots", type=Path)
    args = parser.parse_args()
    if args.screenshots: args.screenshots.mkdir(parents=True, exist_ok=True)
    styles = "\n".join((ROOT / "catalyst/static" / f).read_text() for f in ["site.css", "workshop.css"])
    with tempfile.TemporaryDirectory() as tmp:
        db = str(Path(tmp) / "dom.db")
        with TestClient(create_app(Settings(database=db))) as client, sync_playwright() as pw:
            seed(db)
            client.post("/login", data={"token": issue_human(db, "Example reviewer", True)})
            browser = pw.chromium.launch(headless=True, executable_path=args.browser)
            errors = []
            def render(route, width=1440, scripting=True):
                page = browser.new_page(viewport={"width": width, "height": 1000})
                page.on("pageerror", lambda err: errors.append(str(err)))
                html = client.get(route).text
                html = re.sub(r'<link[^>]+rel="stylesheet"[^>]*>', '', html)
                html = re.sub(r'<script[^>]+src="[^"]+"[^>]*></script>', '', html)
                page.set_content(html)
                page.add_style_tag(content=styles)
                page.evaluate("window.__historyWrites = []; window.history.pushState = (state, unused, url) => window.__historyWrites.push(String(url));")
                if scripting:
                    for f in ["site.js", "workshop.js"]:
                        page.add_script_tag(content=(ROOT / "catalyst/static" / f).read_text())
                page.wait_for_timeout(200)
                return page
            home = render("/")
            colors = home.locator(".type-badge").evaluate_all("els=>els.map(el=>getComputedStyle(el).backgroundColor)")
            assert len(set(colors)) == 3
            assert "Georgia" in home.locator("h1").evaluate("el=>getComputedStyle(el).fontFamily")
            if args.screenshots: home.screenshot(path=str(args.screenshots / "home.png"), full_page=True)
            home.close()
            idea = next(i for i in client.get("/api/ideas").json() if i["kind"] == "catalyst")
            route = f"/ideas/{idea['id']}"
            page = render(route)
            assert page.locator("[data-idea-panel]:visible").count() == 1
            if args.screenshots: page.screenshot(path=str(args.screenshots / "idea.png"), full_page=True)
            page.get_by_role("tab", name="Discussion", exact=True).click()
            body = page.locator('#contribution-form textarea[name="body"]')
            body.fill("Unsent draft survives tab switching")
            page.get_by_role("tab", name="Development", exact=True).click()
            page.get_by_role("tab", name="Discussion", exact=True).click()
            assert body.input_value() == "Unsent draft survives tab switching"
            assert "view=discussion" in page.evaluate("window.__historyWrites.at(-1)")
            page.get_by_role("tab", name="Discussion").focus(); page.keyboard.press("ArrowRight")
            assert page.get_by_role("tab", name="Development").get_attribute("aria-selected") == "true"
            page.keyboard.press("End")
            assert page.get_by_role("tab", name="Investigations").get_attribute("aria-selected") == "true"
            assert page.locator('#task-form select[name="role"] option').count() == 6
            page.keyboard.press("Home")
            assert page.get_by_role("tab", name="Synthesis").get_attribute("aria-selected") == "true"
            page.emulate_media(reduced_motion="reduce")
            page.get_by_role("tab", name="Dissent").click()
            assert page.locator("#dissent").evaluate("el=>getComputedStyle(el).animationName") == "none"
            page.close()
            for slug, url in [("agenda", "/agenda"), ("agent-guide", "/agent-guide"), ("idea", route), ("home", "/")]:
                for width in [390, 1440]:
                    page = render(url, width=width)
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), (slug, width)
                    if args.screenshots:
                        name = slug + ("-mobile" if width==390 else "")
                        page.screenshot(path=str(args.screenshots / (name + ".png")), full_page=True)
                    page.close()
            fallback = render(route + "?view=development", scripting=False)
            assert fallback.locator("#development").is_visible()
            assert fallback.locator("[data-idea-panel]:visible").count() == 1
            fallback.close()
            assert not errors, errors
            print(json.dumps({"status": "passed", "browser": browser.version,
                "mode": "network-free component rendering; history writes captured, not navigated",
                "checks": ["distinct type colors", "serif headings", "one visible panel", "six role choices",
                           "tab clicks", "keyboard arrows Home End", "unsent form retention", "URL state emitted",
                           "reduced motion", "server-selected fallback panel", "390px and 1440px no page overflow"],
                "javascript_errors": errors}, indent=2))
            browser.close()


if __name__ == "__main__": main()
