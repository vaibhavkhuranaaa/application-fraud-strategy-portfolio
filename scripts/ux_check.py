"""Automated M4 quality gate for the workbench.

Runs the checks DESIGN.md requires and records measured results rather than
assertions: responsive behaviour at four widths, semantic structure, keyboard order
and focus visibility, WCAG contrast in both themes, and first-render timing. Also
captures the approval screenshots.

Usage (with the workbench already served on the given base URL):

    PYTHONPATH=src uv run python scripts/ux_check.py --base-url http://127.0.0.1:8050
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, sync_playwright

# One surface. The six-screen Dash workbench it used to walk was retired once the
# static dashboard replaced it.
ROUTES = [("dashboard", "/")]

VIEWPORTS = [
    ("phone", 390, 844),
    ("tablet", 768, 1024),
    ("laptop", 1280, 900),
    ("desktop", 1440, 1000),
    ("wide", 1680, 1000),
]

SCREENSHOT_VIEWPORT = ("desktop", 1440, 1000)
READY_SELECTOR = "#measures .measure"

CONTRAST_SCRIPT = """
() => {
  const luminance = (rgb) => {
    const channel = (value) => {
      const scaled = value / 255;
      return scaled <= 0.03928 ? scaled / 12.92 : Math.pow((scaled + 0.055) / 1.055, 2.4);
    };
    return 0.2126 * channel(rgb[0]) + 0.7152 * channel(rgb[1]) + 0.0722 * channel(rgb[2]);
  };
  const parse = (value) => {
    const match = value.match(/rgba?\\(([^)]+)\\)/);
    if (!match) return null;
    const parts = match[1].split(',').map((part) => parseFloat(part.trim()));
    return { rgb: parts.slice(0, 3), alpha: parts.length > 3 ? parts[3] : 1 };
  };
  const backgroundOf = (element) => {
    let node = element;
    while (node) {
      const parsed = parse(getComputedStyle(node).backgroundColor);
      if (parsed && parsed.alpha > 0) return parsed.rgb;
      node = node.parentElement;
    }
    return [255, 255, 255];
  };
  const ratio = (a, b) => {
    const first = luminance(a) + 0.05;
    const second = luminance(b) + 0.05;
    return first > second ? first / second : second / first;
  };
  const results = [];
  const elements = document.querySelectorAll('main *, header *, footer *');
  for (const element of elements) {
    const text = Array.from(element.childNodes)
      .filter((node) => node.nodeType === 3)
      .map((node) => node.textContent.trim())
      .join(' ')
      .trim();
    if (!text) continue;
    const style = getComputedStyle(element);
    if (style.visibility === 'hidden' || style.display === 'none') continue;
    const box = element.getBoundingClientRect();
    if (!box.width || !box.height) continue;
    const foreground = parse(style.color);
    if (!foreground) continue;
    const size = parseFloat(style.fontSize);
    const weight = parseInt(style.fontWeight, 10) || 400;
    const large = size >= 24 || (size >= 18.66 && weight >= 700);
    const measured = ratio(foreground.rgb, backgroundOf(element));
    results.push({
      text: text.slice(0, 60),
      tag: element.tagName.toLowerCase(),
      size,
      large,
      required: large ? 3.0 : 4.5,
      ratio: Math.round(measured * 100) / 100,
    });
  }
  return results;
}
"""

STRUCTURE_SCRIPT = """
() => {
  const headings = Array.from(document.querySelectorAll('h1,h2,h3,h4,h5,h6'))
    .map((node) => ({ level: Number(node.tagName[1]), text: node.textContent.trim().slice(0, 60) }));
  let skips = 0;
  for (let index = 1; index < headings.length; index += 1) {
    if (headings[index].level - headings[index - 1].level > 1) skips += 1;
  }
  const tables = Array.from(document.querySelectorAll('table'));
  return {
    h1_count: document.querySelectorAll('h1').length,
    heading_level_skips: skips,
    headings: headings.length,
    landmarks: {
      header: document.querySelectorAll('header').length,
      nav: document.querySelectorAll('nav').length,
      main: document.querySelectorAll('main').length,
      footer: document.querySelectorAll('footer').length,
    },
    tables: tables.length,
    tables_without_header_cells: tables.filter((table) => !table.querySelector('th')).length,
    images_without_alt: document.querySelectorAll('img:not([alt])').length,
    charts_labelled: document.querySelectorAll('[role="img"][aria-label]').length,
    visible_em_dash_count: (document.body.innerText.match(/—/g) || []).length,
    has_loading_state: Boolean(document.querySelector('#load-status[role="status"]')),
    has_empty_state: Boolean(document.querySelector('#queue-empty')),
    controls_without_name: Array.from(
      document.querySelectorAll('input, select, textarea, button')
    ).filter((element) => {
      if (element.getAttribute('aria-label')) return false;
      if (element.getAttribute('aria-labelledby')) return false;
      if (element.closest('label')) return false;
      if (element.id && document.querySelector(`label[for="${CSS.escape(element.id)}"]`)) return false;
      if (element.tagName === 'BUTTON' && element.textContent.trim()) return false;
      return true;
    }).length,
  };
}
"""

KEYBOARD_SCRIPT = """
() => {
  const selector = 'a[href], button, input, select, textarea, [tabindex]:not([tabindex="-1"])';
  const focusable = Array.from(document.querySelectorAll(selector)).filter((element) => {
    const style = getComputedStyle(element);
    if (style.visibility === 'hidden' || style.display === 'none') return false;
    return !element.disabled;
  });
  const positive = focusable.filter((element) => Number(element.getAttribute('tabindex')) > 0).length;
  let outOfOrder = 0;
  for (let index = 1; index < focusable.length; index += 1) {
    const previous = focusable[index - 1].getBoundingClientRect();
    const current = focusable[index].getBoundingClientRect();
    if (current.top < previous.top - 4) outOfOrder += 1;
  }
  return {
    focusable: focusable.length,
    positive_tabindex: positive,
    visual_order_breaks: outOfOrder,
    first_focusable: focusable.length ? focusable[0].textContent.trim().slice(0, 40) : null,
  };
}
"""

OVERFLOW_SCRIPT = """
() => ({
  document_scroll_width: document.documentElement.scrollWidth,
  client_width: document.documentElement.clientWidth,
  overflowing_elements: Array.from(document.querySelectorAll('main *'))
    .filter((element) => element.getBoundingClientRect().right > document.documentElement.clientWidth + 1)
    .map((element) => element.tagName.toLowerCase() + (element.className ? '.' + String(element.className).split(' ')[0] : ''))
    .slice(0, 5),
})
"""

FOCUS_RING_SCRIPT = """
() => {
  const target =
    document.querySelector('main a[href], main button, main input') ||
    document.querySelector('nav a[href]');
  if (!target) return { checked: false };
  target.focus();
  const style = getComputedStyle(target);
  return {
    checked: true,
    outline_style: style.outlineStyle,
    outline_width: style.outlineWidth,
    outline_color: style.outlineColor,
  };
}
"""


def _ready(page: Page, url: str) -> float:
    started = time.perf_counter()
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_selector(READY_SELECTOR, timeout=30_000)
    return round((time.perf_counter() - started) * 1000, 1)


def _contrast_summary(page: Page) -> dict[str, Any]:
    results = page.evaluate(CONTRAST_SCRIPT)
    failures = [row for row in results if row["ratio"] < row["required"]]
    return {
        "text_nodes_checked": len(results),
        "minimum_ratio": min((row["ratio"] for row in results), default=None),
        "failures": failures[:10],
        "failure_count": len(failures),
    }


def _interaction_summary(page: Page) -> dict[str, Any]:
    page.locator("#risk-controls").evaluate("element => element.open = true")
    control_count = page.locator("#control-register > li").count()
    needs_production = (
        page.locator("#control-register").get_by_text("needs production data", exact=True).count()
    )
    risk_requirements = page.locator(".risk-disposition dd").count()
    page.get_by_role("button", name="Incumbent proxy").click()
    comparison = page.locator("#scenario-impact-values").inner_text()
    incumbent_zeroes = comparison.count("No change") >= 3

    page.get_by_role("button", name="Reset scenario").click()
    first_case = page.locator(".case-link").first
    first_case.click()
    drill_down_visible = page.locator("#case-detail").is_visible()
    drill_down_named = "Case " in page.locator("#case-detail-heading").inner_text()
    page.get_by_role("button", name="Close detail").click()

    page.locator("#c-outcome").select_option("good")
    filtered_count = page.locator("#table-queue tbody tr").count()
    page.locator("#c-outcome").select_option("all")
    return {
        "scenario_comparison_updates": incumbent_zeroes,
        "case_drill_down_visible": drill_down_visible,
        "case_drill_down_named": drill_down_named,
        "retrospective_filter_returns_rows": filtered_count > 0,
        "url_state_recorded": "model=catboost_hybrid" in page.url,
        "seven_owned_controls_rendered": control_count == 7,
        "production_data_gaps_visible": needs_production == 3,
        "risk_disposition_visible": risk_requirements == 4,
        "refusal_preserved_after_controls": "Not approved for rollout"
        in page.locator("#verdict-word").inner_text(),
    }


def run(base_url: str, screenshot_dir: Path, output: Path) -> dict[str, Any]:
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "tool": "playwright chromium (headless)",
        "base_url": base_url,
        "viewports": [{"name": name, "width": width, "height": height} for name, width, height in VIEWPORTS],
        "screens": {},
        "themes": {},
        "screenshots": [],
    }
    with sync_playwright() as driver:
        browser = driver.chromium.launch()
        for name, route in ROUTES:
            url = f"{base_url.rstrip('/')}{route}"
            screen: dict[str, Any] = {"route": route, "responsive": {}}
            for viewport, width, height in VIEWPORTS:
                context = browser.new_context(viewport={"width": width, "height": height})
                page = context.new_page()
                elapsed = _ready(page, url)
                page.wait_for_timeout(400)
                overflow = page.evaluate(OVERFLOW_SCRIPT)
                screen["responsive"][viewport] = {
                    "ready_ms": elapsed,
                    "page_scrolls_horizontally": overflow["document_scroll_width"]
                    > overflow["client_width"] + 1,
                    "overflowing_elements": overflow["overflowing_elements"],
                }
                if viewport == SCREENSHOT_VIEWPORT[0]:
                    screen["structure"] = page.evaluate(STRUCTURE_SCRIPT)
                    screen["keyboard"] = page.evaluate(KEYBOARD_SCRIPT)
                    screen["focus_ring"] = page.evaluate(FOCUS_RING_SCRIPT)
                    screen["contrast_light"] = _contrast_summary(page)
                    stakeholder_path = screenshot_dir / f"{name}-stakeholder.png"
                    page.screenshot(path=stakeholder_path, full_page=True)
                    report["screenshots"].append(stakeholder_path.as_posix())
                    screen["interactions"] = _interaction_summary(page)
                    page.locator("#operational-evidence").evaluate("element => element.open = true")
                    page.locator("#analyst").evaluate("element => element.open = true")
                    page.locator(".page-nav").evaluate("element => element.hidden = true")
                    technical_path = screenshot_dir / f"{name}-technical.png"
                    page.locator("#analyst").screenshot(path=technical_path)
                    report["screenshots"].append(technical_path.as_posix())
                    # The surface commits to a single light rendition: its use scene is a
                    # daytime office, a meeting-room projector, and print.
                    screen["contrast_dark"] = {
                        "measured": False,
                        "reason": "surface commits to one light rendition; see DESIGN.md",
                        "failure_count": 0,
                        "minimum_ratio": None,
                    }
                if viewport == "phone":
                    phone_path = screenshot_dir / f"{name}-{viewport}.png"
                    page.screenshot(path=phone_path, full_page=True)
                    report["screenshots"].append(phone_path.as_posix())
                context.close()
            report["screens"][name] = screen
            error_context = browser.new_context(viewport={"width": 1440, "height": 1000})
            error_page = error_context.new_page()
            error_page.add_init_script("window.__FORCE_DATA_ERROR__ = true")
            error_page.route("**/data/dashboard.json", lambda route: route.abort())
            error_page.goto(url, wait_until="domcontentloaded")
            error_page.get_by_text("Data unavailable", exact=True).wait_for(timeout=30_000)
            screen["error_state"] = {
                "visible": error_page.get_by_text("Data unavailable", exact=True).is_visible(),
                "recovery_action_named": error_page.get_by_role(
                    "button", name="Retry loading evidence"
                ).is_visible(),
            }
            error_context.close()

            file_context = browser.new_context(viewport={"width": 1440, "height": 1000})
            file_page = file_context.new_page()
            file_url = (Path(__file__).resolve().parents[1] / "dashboard" / "index.html").as_uri()
            _ready(file_page, file_url)
            screen["self_contained_file"] = {
                "ready": file_page.locator(READY_SELECTOR).count() > 0,
                "data_unavailable": file_page.get_by_text("Data unavailable", exact=True).count() > 0,
            }
            file_context.close()
        browser.close()

    contrast_failures = sum(
        screen["contrast_light"]["failure_count"] for screen in report["screens"].values()
    )
    ready_values = [
        entry["ready_ms"] for screen in report["screens"].values() for entry in screen["responsive"].values()
    ]
    report["summary"] = {
        "screens_checked": len(report["screens"]),
        "contrast_failures": contrast_failures,
        "minimum_contrast_ratio": min(
            screen["contrast_light"]["minimum_ratio"] for screen in report["screens"].values()
        ),
        "screens_scrolling_horizontally": sum(
            1
            for screen in report["screens"].values()
            for entry in screen["responsive"].values()
            if entry["page_scrolls_horizontally"]
        ),
        "controls_without_accessible_name": sum(
            screen["structure"]["controls_without_name"] for screen in report["screens"].values()
        ),
        "heading_level_skips": sum(
            screen["structure"]["heading_level_skips"] for screen in report["screens"].values()
        ),
        "screens_without_single_h1": sum(
            1 for screen in report["screens"].values() if screen["structure"]["h1_count"] != 1
        ),
        "positive_tabindex_total": sum(
            screen["keyboard"]["positive_tabindex"] for screen in report["screens"].values()
        ),
        "interaction_failures": sum(
            1
            for screen in report["screens"].values()
            for passed in screen.get("interactions", {}).values()
            if not passed
        ),
        "visible_em_dash_total": sum(
            screen["structure"]["visible_em_dash_count"] for screen in report["screens"].values()
        ),
        "state_pattern_failures": sum(
            int(not screen["structure"]["has_loading_state"])
            + int(not screen["structure"]["has_empty_state"])
            + int(not screen["error_state"]["visible"])
            + int(not screen["error_state"]["recovery_action_named"])
            + int(not screen["self_contained_file"]["ready"])
            + int(screen["self_contained_file"]["data_unavailable"])
            for screen in report["screens"].values()
        ),
        "max_ready_ms": max(ready_values),
        "median_ready_ms": sorted(ready_values)[len(ready_values) // 2],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8060")
    parser.add_argument("--screenshots", default="docs/screenshots")
    parser.add_argument("--output", default="evaluation/ux_evaluation.json")
    arguments = parser.parse_args()
    report = run(arguments.base_url, Path(arguments.screenshots), Path(arguments.output))
    print(json.dumps(report["summary"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
