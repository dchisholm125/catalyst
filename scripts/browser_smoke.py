"""Optional real-Chromium smoke test. Uses a temporary DB and synthetic credentials.

Install Playwright separately and its Chromium browser, or pass --browser to use
an installed Chromium. No inference provider, real account, or external site used.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import httpx
from catalyst.db import initialize, issue_agent, issue_human
from catalyst.cli import seed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--browser", default=shutil.which("chromium"))
    parser.add_argument("--screenshots", type=Path)
    args = parser.parse_args()
    try:
        from playwright.sync_api import sync_playwright, expect
    except ImportError:
        raise SystemExit("Install Playwright first: python -m pip install playwright")
    if args.screenshots:
        args.screenshots.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="catalyst-browser-") as tmp:
        db = str(Path(tmp) / "smoke.db")
        initialize(db); seed(db)
        invitation = issue_human(db, "Example reviewer", reviewer=True)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        env = {**os.environ, "CATALYST_DB": db, "CATALYST_CADENCE_SECONDS": "0", "PYTHONPATH": str(ROOT)}
        with open(Path(tmp) / "server.log", "w") as log:
            server = subprocess.Popen([sys.executable, "-m", "uvicorn", "catalyst.app:create_app", "--factory",
                "--host", "127.0.0.1", "--port", str(port)], cwd=ROOT, env=env, stdout=log, stderr=log)
            try:
                for _ in range(80):
                    try:
                        if httpx.get(base + "/healthz").status_code == 200: break
                    except httpx.HTTPError: pass
                    time.sleep(.1)
                else: raise RuntimeError("Temporary server did not start")
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(headless=True, executable_path=args.browser)
                    ctx = browser.new_context(viewport={"width": 1440, "height": 1000})
                    page = ctx.new_page(); errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.goto(base + "/login")
                    page.locator('input[name="token"]').fill(invitation)
                    page.get_by_role("button", name="Continue", exact=True).click()
                    page.wait_for_url(base + "/")
                    assert page.get_by_role("button", name="Sign out").is_visible()
                    assert page.locator(".idea-row").count() == 3
                    colors = page.locator(".type-badge").evaluate_all("els => els.map(el => getComputedStyle(el).backgroundColor)")
                    assert len(set(colors)) == 3
                    assert "Georgia" in page.locator("h1").evaluate("el => getComputedStyle(el).fontFamily")
                    if args.screenshots: page.screenshot(path=str(args.screenshots / "home.png"), full_page=True)
                    page.get_by_role("link", name="Claims", exact=True).click()
                    assert page.locator(".idea-row").count() == 1
                    assert page.locator(".type-badge").inner_text() == "Claim"
                    page.get_by_role("link", name="All ideas", exact=True).click()
                    page.get_by_role("link", name="Share neighborhood equipment without exhausting one volunteer", exact=True).click()
                    equipment_url = page.url
                    assert page.locator("[data-idea-panel]:visible").count() == 1
                    page.get_by_role("tab", name="Discussion", exact=True).click()
                    page.locator('#contribution-form textarea[name="body"]').fill("Unsent text survives panel changes.")
                    page.get_by_role("tab", name="Development", exact=True).click()
                    page.go_back()
                    assert page.get_by_role("tab", name="Discussion").get_attribute("aria-selected") == "true"
                    assert page.locator('#contribution-form textarea[name="body"]').input_value() == "Unsent text survives panel changes."
                    page.get_by_role("tab", name="Discussion").focus(); page.keyboard.press("ArrowRight")
                    assert page.get_by_role("tab", name="Development").get_attribute("aria-selected") == "true"
                    page.keyboard.press("Home")
                    assert page.get_by_role("tab", name="Synthesis").get_attribute("aria-selected") == "true"
                    if args.screenshots: page.screenshot(path=str(args.screenshots / "idea.png"), full_page=True)
                    page.emulate_media(reduced_motion="reduce")
                    page.get_by_role("tab", name="Dissent").click()
                    assert page.locator("#dissent").evaluate("el => getComputedStyle(el).animationName") == "none"
                    page.emulate_media(reduced_motion="no-preference")
                    nojs = browser.new_context(java_script_enabled=False)
                    fallback = nojs.new_page(); fallback.goto(equipment_url.split("?")[0] + "?view=dissent")
                    assert fallback.locator("[data-idea-panel]:visible").count() == 1
                    assert fallback.locator("#dissent").is_visible()
                    fallback.get_by_role("link", name="Development", exact=True).click()
                    assert fallback.locator("#development").is_visible(); nojs.close()
                    page.goto(base + "/agenda")
                    assert page.locator(".topic-grid .topic").count() == 20
                    if args.screenshots: page.screenshot(path=str(args.screenshots / "agenda.png"), full_page=True)
                    page.goto(base + "/agent-guide")
                    assert page.locator(".role-grid .panel").count() == 6
                    if args.screenshots: page.screenshot(path=str(args.screenshots / "agent-guide.png"), full_page=True)
                    page.set_viewport_size({"width": 390, "height": 844})
                    for route in ["/", "/agenda", "/agent-guide", equipment_url.removeprefix(base)]:
                        page.goto(base + route)
                        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), route
                    if args.screenshots: page.screenshot(path=str(args.screenshots / "idea-mobile.png"), full_page=True)
                    page.set_viewport_size({"width": 1440, "height": 1000})
                    page.goto(base + "/agenda?topic=time")
                    page.get_by_label("Your question", exact=True).fill("How might we reduce hidden coordination work?")
                    page.get_by_label("Why does it matter, and to whom?", exact=True).fill("Synthetic smoke-test question; not real community demand.")
                    page.get_by_role("button", name="Submit question", exact=True).click()
                    page.wait_for_url("**/agenda/*")
                    page.get_by_role("button", name="I want this explored", exact=True).click()
                    expect(page.get_by_role("button", name="Withdraw my exploration interest", exact=True)).to_be_visible()
                    page.locator("summary", has_text="Develop into a Living Idea").click()
                    page.get_by_label("Initial synthesis", exact=True).fill("Synthetic initial formulation for testing a human-directed work cycle.")
                    page.get_by_label("Why develop this question?", exact=True).fill("Verify a complete loop without calling an inference provider.")
                    page.get_by_role("button", name="Create linked idea", exact=True).click()
                    page.wait_for_url("**/ideas/*?view=investigations")
                    idea_url = page.url
                    page.get_by_label("What would help this idea most?", exact=True).fill("Which hidden obligation should we examine first?")
                    page.get_by_role("combobox", name="Agent role", exact=True).select_option("challenger")
                    page.get_by_role("button", name="Queue investigation", exact=True).click()
                    page.wait_for_load_state("networkidle")
                    expect(page.locator(".task")).to_have_count(1)
                    page.goto(base + "/contribute")
                    page.locator('#budget-form input[name="daily_jobs"]').fill("4")
                    page.locator('#budget-form input[name="share"]').focus(); page.keyboard.press("End")
                    page.locator('#budget-form input[name="enabled"]').check()
                    page.locator("#budget-form button").click(); page.wait_for_load_state("networkidle")
                    token = issue_agent(db, "Example reviewer", "Smoke-test challenger")
                    result = subprocess.run([sys.executable, "examples/mock_worker.py", "--server", base, "--role", "challenger"],
                        cwd=ROOT, env={**env, "CATALYST_AGENT_TOKEN": token}, capture_output=True, text=True, timeout=30)
                    assert result.returncode == 0, result.stderr
                    assert "Simulation contribution accepted" in result.stdout, result.stdout
                    page.goto(idea_url)
                    page.locator("summary", has_text="Review this result").click()
                    page.locator('.task-review-form select[name="verdict"]').select_option("revise")
                    page.locator('.task-review-form textarea[name="reason"]').fill("Connection verified. Simulation is not a substantive answer.")
                    page.locator(".task-review-form button").click(); page.wait_for_load_state("networkidle")
                    expect(page.locator(".review-note")).to_contain_text("Human review: revise")
                    page.goto(base + "/agents")
                    page.get_by_role("link", name="Smoke-test challenger", exact=True).click()
                    assert "Handler reviewed their own agent" in page.inner_text("main")
                    assert "SIMULATION ONLY" in page.inner_text("main")
                    assert errors == [], errors
                    report = {"status": "passed", "browser": browser.version, "javascript_errors": errors,
                        "checks": ["native invitation login", "distinct type colors and serif headings", "type filtering",
                                   "single visible panel", "tab keyboard navigation", "Back history and unsent form preservation",
                                   "reduced motion", "no-JavaScript deep links", "20 topics and six roles",
                                   "390px layout without page overflow", "human question and support", "reviewer development",
                                   "role-specific task creation", "budget controls", "mock worker round-trip", "review and agent history"]}
                    print(json.dumps(report, indent=2))
                    browser.close()
            finally:
                server.terminate()
                try: server.wait(timeout=5)
                except subprocess.TimeoutExpired: server.kill(); server.wait()


if __name__ == "__main__": main()
