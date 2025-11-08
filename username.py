#!/usr/bin/env python3
"""
goodreads_find_reviewer.py
--------------------------
Find the user who wrote a particular Goodreads review.

• Works out-of-the-box with 'requests' + 'beautifulsoup4'  (pip install the two).
• Falls back to headless Chrome (Selenium) *only* if the plain-HTML grab
  hits an anti-bot wall or a JS shell.
• Prints the reviewer’s display name and the absolute profile URL.
"""

import re
import sys
import html
import time
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

import requests
from bs4 import BeautifulSoup

# ──────────────────────────────────────────────────────────────────────────────
# INPUTS ─-- tweak only these two:
REVIEWS_URL = (
    "https://www.goodreads.com/book/show/60714999/reviews?reviewFilters=eyJhZnRlciI6Ik5EWXhNekVzTVRZM09UazNOekUxTmpnMU1nIn0%3D"
    "?reviewFilters=eyJhZnRlciI6Ik5qY3hOeXd4TXprMU1URTVPVFl5TURBdyJ9"
)
SNIPPET = (
    "skilled and badass, but also inconveniently human inside and out."
).lower().strip()
# ──────────────────────────────────────────────────────────────────────────────


def _normalise(txt: str) -> str:
    """Collapse whitespace, unescape HTML, strip → lower-case."""
    return re.sub(r"\s+", " ", html.unescape(txt)).strip().lower()


def _iterate_pages(base_url: str, session: requests.Session, max_pages=80):
    """
    Yield (page_number, BeautifulSoup) for page 1, 2, 3… until 'max_pages'
    or until Goodreads starts returning the same HTML (rate-limit hint).
    """
    parsed = urlparse(base_url)
    base_qs = parse_qs(parsed.query, keep_blank_values=True)

    prev_body = None
    for page in range(1, max_pages + 1):
        qs = base_qs.copy()
        qs["page"] = [str(page)]
        url = urlunparse(parsed._replace(query=urlencode(qs, doseq=True)))
        r = session.get(url, timeout=20)
        r.raise_for_status()

        if prev_body and r.text == prev_body:       # simple dupe-guard
            break
        prev_body = r.text

        yield page, BeautifulSoup(r.text, "html.parser")

        # try not to look like a bot
        time.sleep(1.8 + page * 0.05)


def plain_html_path():
    """
    First attempt: keep it fast & lightweight with 'requests'.
    Return (name, profile_url) or (None, None).
    """
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        }
    )

    for pg_no, soup in _iterate_pages(REVIEWS_URL, session):
        for card in soup.select("article.ReviewCard"):
            body = (card.select_one('div[data-testid="contentContainer"] span.Formatted')
                    or card.select_one("div.TruncatedContent__text"))
            if not body:
                continue

            if SNIPPET in _normalise(body.get_text()):
                link = card.select_one('section.ReviewerProfile__info a[href*="/user/show/"]')
                if link:
                    name = link.get_text(strip=True)
                    href = link["href"]
                    href = href if href.startswith("http") else "https://www.goodreads.com" + href
                    return name, href
        # safety-net: Goodreads stops at ~70 pages for most titles
    return None, None


# ──────────────────────  Fallback: Selenium headless  ────────────────────────
def selenium_path():
    """
    Second attempt: use Selenium to click “Show more reviews”.
    Only invoked if the plain-HTML grab could not find the review.
    """
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from webdriver_manager.chrome import ChromeDriverManager
    except ImportError:
        return None, None   # Selenium not installed

    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--user-agent="
                      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/124.0.0.0 Safari/537.36")
    opts.page_load_strategy = "eager"

    drv = webdriver.Chrome(service=Service(ChromeDriverManager().install()),
                           options=opts)

    # hide “I am a WebDriver” from JS
    drv.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": "Object.defineProperty(navigator,'webdriver',{get:() => undefined})"}
    )

    wait = WebDriverWait(drv, 25)
    drv.get(REVIEWS_URL)

    # wait for the first batch of cards or for an overlay
    wait.until(lambda d: d.find_elements(By.CSS_SELECTOR, "article.ReviewCard") or
               d.find_elements(By.CSS_SELECTOR, "div.Overlay"))

    def extract_here():
        soup = BeautifulSoup(drv.page_source, "html.parser")
        for card in soup.select("article.ReviewCard"):
            body = (card.select_one('div[data-testid="contentContainer"] span.Formatted')
                    or card.select_one("div.TruncatedContent__text"))
            if not body:
                continue
            if SNIPPET in _normalise(body.get_text()):
                link = card.select_one('section.ReviewerProfile__info a[href*="/user/show/"]')
                if link:
                    name = link.get_text(strip=True)
                    href = link.get_attribute("href") if hasattr(link, "get_attribute") else link["href"]
                    href = href if href.startswith("http") else "https://www.goodreads.com" + href
                    return name, href
        return None, None

    try:
        seen = set()
        while True:
            hit = extract_here()
            if hit[0]:
                return hit

            # try to click “Show more reviews”; if not clickable, we’re done
            try:
                btn = drv.find_element(By.CSS_SELECTOR, 'span[data-testid="loadMore"]')
                drv.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
                if btn in seen:
                    break
                seen.add(btn)
                btn.click()
                time.sleep(2.2)
            except Exception:
                break
    finally:
        drv.quit()

    return None, None


# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n‣ Trying plain-HTML path …")
    reviewer, profile = plain_html_path()

    if not reviewer:
        print("   (HTML-only search failed – switching to Selenium)")
        reviewer, profile = selenium_path()

    if reviewer:
        print("\n✅  Found it!")
        print(f"Reviewer display name :  {reviewer}")
        print(f"Profile link          :  {profile}\n")
        sys.exit(0)
    else:
        print("\n❌  Could not locate the review after exhausting all pages.")
        sys.exit(1)
