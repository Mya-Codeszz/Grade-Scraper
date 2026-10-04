"""
StudentVUE (Edupoint Synergy) grade scraper: FastAPI + Playwright.

Base44 calls POST /grades with the student's own StudentVUE credentials.
Credentials are used for that one request only: never stored, never logged.
"""
import asyncio
import logging
import os
import re
import secrets

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel
from playwright.async_api import TimeoutError as PWTimeout
from playwright.async_api import async_playwright

from gpa import calculate_gpa

BASE = os.getenv("PORTAL_BASE", "https://az-eef.edupoint.com")
LOGIN_URL = f"{BASE}/PXP2_Login_Student.aspx?Logout=1&regenerateSessionId=true"
GRADEBOOK_URL = f"{BASE}/PXP2_Gradebook.aspx?AGU=0"

API_KEY = os.environ["SCRAPER_API_KEY"]
MAX_CONCURRENT = int(os.getenv("MAX_CONCURRENT", "2"))
sem = asyncio.Semaphore(MAX_CONCURRENT)

log = logging.getLogger("uvicorn.error")

app = FastAPI(title="Grade Scraper")


class Login(BaseModel):
    username: str
    password: str


def require_key(x_api_key: str = Header(default="")):
    if not secrets.compare_digest(x_api_key, API_KEY):
        raise HTTPException(status_code=401, detail="Unauthorized")


def to_number(s):
    m = re.search(r"\d+(\.\d+)?", s or "")
    return float(m.group()) if m else None


def semester_from_period(period: str | None):
    """Q1/Q2 (any suffix like Q2P1) -> Semester 1; Q3/Q4 -> Semester 2."""
    if not period:
        return None
    m = re.search(r"Q(\d)", period, re.I)
    if m:
        return 1 if int(m.group(1)) <= 2 else 2
    m = re.search(r"Semester\s*(\d)", period, re.I)
    return int(m.group(1)) if m else None


# Runs inside the browser; reads the course list from the Grade Book page.
EXTRACT_JS = """
() => {
  const courses = [];
  document.querySelectorAll('#gb-classes .gb-class-header').forEach(h => {
    const guid = h.dataset.guid;
    const title = (h.querySelector('.course-title')?.innerText || '').trim();
    const teacher = h.querySelector('span.teacher a')?.innerText.trim() || null;
    const room = (h.querySelector('.teacher-room')?.innerText || '').replace(/^Room:\\s*/i, '').trim() || null;
    const row = document.querySelector(`#gb-classes .gb-class-row[data-guid="${guid}"][data-mark-gu]`);
    courses.push({
      title,
      teacher,
      room,
      letter: row?.querySelector('.mark')?.innerText.trim() || null,
      score: row?.querySelector('.score')?.innerText.trim() || null,
      missing: row?.querySelector('.class-item-lessemphasis div')?.innerText.trim() || null,
    });
  });
  return {
    studentName: (document.querySelector('h1.hide-for-screen')?.innerText || '').trim() || null,
    period: document.querySelector('.term-selector .current.breadcrumb-term')?.innerText.trim() || null,
    courses,
  };
}
"""


async def scrape(username: str, password: str, state: dict) -> dict:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=["--no-sandbox"])
        context = await browser.new_context()
        page = await context.new_page()
        page.set_default_timeout(20_000)
        try:
            # ---- login ----
            state["step"] = "open-login-page"
            await page.goto(LOGIN_URL)
            state["url"] = page.url.split("?")[0]
            state["step"] = "fill-login-form"
            await page.fill("#ctl00_MainContent_username", username)
            await page.fill("#ctl00_MainContent_password", password)
            state["step"] = "submit-login"
            await page.click("#ctl00_MainContent_Submit1")
            try:
                await page.wait_for_url(lambda u: "PXP2_Login" not in u, timeout=15_000)
            except PWTimeout:
                # Still on the login page => bad credentials
                raise HTTPException(status_code=401, detail="Invalid StudentVUE username or password")

            # ---- grade book ----
            state["step"] = "open-gradebook"
            state["url"] = page.url.split("?")[0]
            await page.goto(GRADEBOOK_URL)
            state["url"] = page.url.split("?")[0]
            try:
                await page.wait_for_selector("#gb-classes .gb-class-header")
            except PWTimeout:
                link = await page.query_selector("a[href*='PXP2_Gradebook']")
                if not link:
                    raise HTTPException(status_code=502, detail="Could not find the Grade Book")
                await link.click()
                await page.wait_for_selector("#gb-classes .gb-class-header")

            state["step"] = "extract-courses"
            state["url"] = page.url.split("?")[0]
            raw = await page.evaluate(EXTRACT_JS)
        finally:
            await context.close()
            await browser.close()

    courses = []
    for c in raw["courses"]:
        m = re.match(r"^\s*(\d+)\s*:\s*(.+)$", c["title"])
        courses.append({
            "period": m.group(1) if m else None,
            "course": (m.group(2) if m else c["title"]).strip(),
            "teacher": c["teacher"],
            "room": c["room"],
            "letter": c["letter"],
            "percent": to_number(c["score"]),
            "missing": c["missing"],
        })

    gpa = calculate_gpa(courses)
    period = raw["period"]
    return {
        "student_name": raw["studentName"],
        "grading_period": period,
        "semester": semester_from_period(period),
        **gpa,
        "courses": courses,
    }


@app.get("/health")
async def health():
    return {"ok": True}


@app.post("/grades", dependencies=[Depends(require_key)])
async def grades(login: Login):
    async with sem:
        state = {"step": "start", "url": None}
        try:
            return await asyncio.wait_for(scrape(login.username, login.password, state), timeout=60)
        except asyncio.TimeoutError:
            log.error("scrape timed out at step=%s url=%s", state["step"], state["url"])
            raise HTTPException(status_code=504, detail="StudentVUE timed out")
        except HTTPException as e:
            log.error("scrape http error %s at step=%s url=%s", e.status_code, state["step"], state["url"])
            raise
        except Exception as e:
            # Redact credentials from anything we log
            msg = str(e)
            for secret in (login.password, login.username):
                if secret:
                    msg = msg.replace(secret, "***")
            log.error("scrape failed at step=%s url=%s: %s: %s",
                      state["step"], state["url"], type(e).__name__, msg[:400])
            raise HTTPException(status_code=502, detail="Scrape failed; portal layout may have changed")
