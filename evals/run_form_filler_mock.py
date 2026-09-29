"""Offline experiment for count-driven repeatable form filling."""

from pathlib import Path

from playwright.sync_api import sync_playwright


FIXTURE = Path(__file__).parent / "fixtures" / "form_page.html"


def main() -> None:
    profile = {
        "education": [
            {"school": "Imperial College London · MSc Statistics"},
            {"school": "University of Liverpool · BSc Mathematics"},
            {"school": "Xi’an Jiaotong-Liverpool University · BSc Applied Mathematics"},
        ],
        "projects": [
            {"name": "GTFlow"},
            {"name": "Stable Self-Distillation Flow Matching"},
            {"name": "Session-Based Recommender System"},
        ],
    }
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        submitted = {"value": False}
        page.on("request", lambda request: submitted.__setitem__("value", True) if request.method == "POST" else None)
        page.goto(FIXTURE.as_uri())

        for section, entries, selector, field in (
            ("education", profile["education"], "#education-section [data-add='education']", "education_school[]"),
            ("projects", profile["projects"], "#project-section [data-add='project']", "project_name[]"),
        ):
            for _ in range(len(entries) - 1):
                page.locator(selector).click()
            fields = page.locator(f"[name='{field}']")
            assert fields.count() == len(entries), (section, fields.count(), len(entries))
            for index, entry in enumerate(entries):
                fields.nth(index).fill(entry.get("school") or entry.get("name") or "")

        assert page.locator("[name='education_school[]']").count() == 3
        assert page.locator("[name='project_name[]']").count() == 3
        assert not submitted["value"]
        print({"education_groups": 3, "project_groups": 3, "submitted": False})
        browser.close()


if __name__ == "__main__":
    main()
