#!/usr/bin/env python3
"""
Goodreads Scraper - Consolidated Script
----------------------------------------
All-in-one script for scraping Goodreads books with automated scheduling.

Usage:
    python main.py scrape              # Run main scraper once
    python main.py enhance             # Run review enhancer once
    python main.py schedule            # Run scheduler (continuous)
    python main.py scrape --schedule   # Schedule main scraper
    python main.py enhance --schedule  # Schedule review enhancer
"""

import os
import sys
import time
import random
import logging
import re
import json
import datetime
import unicodedata
import psycopg2
import argparse
from pathlib import Path
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode, urlsplit, urlunsplit
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException
from webdriver_manager.chrome import ChromeDriverManager

try:
    import schedule
    SCHEDULE_AVAILABLE = True
except ImportError:
    SCHEDULE_AVAILABLE = False
    print("Warning: 'schedule' module not installed. Scheduling features unavailable.")
    print("Install with: pip install schedule")

# ================================================================================================
# CONFIGURATION
# ================================================================================================

CONFIG_FILE = "config.json"

DEFAULT_CONFIG = {
    "database": {
        "host": "localhost",
        "database": "my_goodreads_db",
        "user": "postgres",
        "password": "123",
        "port": "5432"
    },
    "scraping": {
        "book_urls_file": "book_urls.txt",
        "min_delay": 5,
        "max_delay": 10,
        "page_load_timeout": 60
    },
    "scheduling": {
        "enabled": false,
        "scraper": {
            "enabled": true,
            "schedule_type": "daily",
            "schedule_time": "02:00",
            "interval_hours": null,
            "day_of_week": null
        },
        "enhancer": {
            "enabled": true,
            "schedule_type": "daily",
            "schedule_time": "04:00",
            "interval_hours": null,
            "day_of_week": null
        }
    },
    "logging": {
        "level": "INFO",
        "log_file": "scraper.log"
    }
}

# ================================================================================================
# CONFIGURATION MANAGEMENT
# ================================================================================================

def load_config():
    """Load configuration from file or create default."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
            logging.info(f"Loaded configuration from {CONFIG_FILE}")
            return config
        except Exception as e:
            logging.error(f"Error loading config file: {e}")
            logging.info("Using default configuration")

    save_config(DEFAULT_CONFIG)
    logging.info(f"Created default configuration file: {CONFIG_FILE}")
    return DEFAULT_CONFIG

def save_config(config):
    """Save configuration to file."""
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=4)
    except Exception as e:
        logging.error(f"Error saving config file: {e}")

# ================================================================================================
# DATABASE
# ================================================================================================

def get_db_connection():
    """Establish a connection to the PostgreSQL database."""
    config = load_config()
    return psycopg2.connect(**config["database"])

def book_already_scraped(conn, url):
    """Check if a book URL is already in the book_info table."""
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM book_info WHERE book_url = %s LIMIT 1;", (url,))
        return cur.fetchone() is not None

def get_book_links_from_file(filepath):
    """Read book URLs from the given file and return as a list."""
    if not os.path.exists(filepath):
        logging.error(f"Book URLs file not found: {filepath}")
        return []
    with open(filepath, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]

def get_books_for_review_enhancement():
    """Get books from database that need more reviews based on star count."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                WITH book_counts AS (
                    SELECT
                        book_id,
                        MAX(title) as title,
                        MAX(author) as author,
                        MAX(book_url) as book_url,
                        COUNT(*) as review_count
                    FROM
                        public.book_reviews
                    GROUP BY
                        book_id
                )
                SELECT
                    bc.book_id,
                    bc.title,
                    bc.author,
                    bc.book_url,
                    bc.review_count,
                    bi.star_dist_5,
                    bi.star_dist_4,
                    bi.star_dist_3,
                    bi.star_dist_2,
                    bi.star_dist_1
                FROM
                    book_counts bc
                LEFT JOIN
                    public.book_info bi ON bc.book_id = bi.id
                ORDER BY
                    (COALESCE(bi.star_dist_5, 0) +
                    COALESCE(bi.star_dist_4, 0) +
                    COALESCE(bi.star_dist_3, 0) +
                    COALESCE(bi.star_dist_2, 0) +
                    COALESCE(bi.star_dist_1, 0)) DESC;
            """)
            books = cur.fetchall()

            books_to_process = []
            for book in books:
                book_id, title, author, book_url, current_count, star5, star4, star3, star2, star1 = book

                total_stars = sum(x for x in [star5, star4, star3, star2, star1] if x is not None)

                if total_stars >= 700000:
                    desired_count = 500
                elif total_stars >= 500000:
                    desired_count = 300
                elif total_stars >= 300000:
                    desired_count = 250
                else:
                    desired_count = 100

                if current_count < desired_count:
                    books_to_process.append({
                        'id': book_id,
                        'title': title,
                        'author': author,
                        'url': book_url,
                        'current_count': current_count,
                        'desired_count': desired_count,
                        'needed_count': desired_count - current_count,
                        'total_stars': total_stars
                    })

            books_to_process.sort(key=lambda x: x['needed_count'], reverse=True)
            return books_to_process
    finally:
        conn.close()

def get_existing_review_texts(book_id):
    """Get all existing review texts for a book from the database."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT review_text
                FROM public.book_reviews
                WHERE book_id = %s AND review_text IS NOT NULL;
            """, (book_id,))
            results = cur.fetchall()
            return set(row[0] for row in results if row[0])
    finally:
        conn.close()

# ================================================================================================
# SELENIUM SETUP
# ================================================================================================

def get_driver():
    """Set up and return a configured Chrome WebDriver."""
    config = load_config()
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-notifications")
    chrome_options.add_argument("--disable-popup-blocking")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-images")
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36")
    chrome_options.page_load_strategy = 'eager'

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.set_page_load_timeout(config["scraping"]["page_load_timeout"])

    return driver

def respectful_delay():
    """Pause for a random delay."""
    config = load_config()
    min_wait = config["scraping"]["min_delay"]
    max_wait = config["scraping"]["max_delay"]
    time.sleep(random.uniform(min_wait, max_wait))

def get_page_html(driver, url, wait_for_selector=None, wait_time=20, retries=2):
    """Navigate to a URL and return the page HTML after waiting for specified elements."""
    for attempt in range(retries + 1):
        try:
            logging.info(f"Navigating to: {url} (Attempt {attempt + 1}/{retries + 1})")
            driver.get(url)
            time.sleep(5)

            if wait_for_selector:
                try:
                    wait = WebDriverWait(driver, wait_time)
                    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, wait_for_selector)))
                    logging.info(f"Found selector: {wait_for_selector}")
                except TimeoutException:
                    logging.warning(f"Timeout waiting for {wait_for_selector} on {url}")

            html = driver.page_source

            if "goodreads" in html.lower() and len(html) > 5000:
                logging.info(f"Successfully fetched page: {url} (content length: {len(html)})")
                return html
            else:
                logging.warning(f"Page content seems insufficient, length: {len(html)}")
                if attempt < retries:
                    time.sleep(5)
                    continue

        except Exception as e:
            logging.error(f"Error fetching {url}: {e}")
            if attempt < retries:
                time.sleep(5)
                continue

    return None

def click_element(driver, selector, selector_type=By.CSS_SELECTOR, wait_time=5, max_attempts=3):
    """Attempt to click an element with JavaScript fallback."""
    attempts = 0
    while attempts < max_attempts:
        try:
            wait = WebDriverWait(driver, wait_time)
            element = wait.until(EC.element_to_be_clickable((selector_type, selector)))
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
            time.sleep(0.5)

            try:
                element.click()
            except Exception:
                driver.execute_script("arguments[0].click();", element)

            time.sleep(wait_time)
            logging.info(f"Successfully clicked element: {selector}")
            return True
        except Exception as e:
            attempts += 1
            logging.warning(f"Attempt {attempts}/{max_attempts} failed to click {selector}: {e}")
            time.sleep(1)

    logging.error(f"Failed to click element after {max_attempts} attempts: {selector}")
    return False

def close_any_overlays(driver):
    """Try to close any overlays that might be blocking clicks."""
    try:
        overlays = driver.find_elements(By.CSS_SELECTOR, "div.Overlay__content, div.Modal, div.Popup")
        if overlays:
            logging.info(f"Found {len(overlays)} overlay(s). Attempting to close...")
            close_buttons = driver.find_elements(By.CSS_SELECTOR,
                "button.Modal__close, button.Overlay__close, button.Popup__close, button[aria-label='Close'], button.closeButton")

            for btn in close_buttons:
                try:
                    driver.execute_script("arguments[0].click();", btn)
                    time.sleep(1)
                except:
                    pass
            return True
        return False
    except:
        return False

# ================================================================================================
# TEXT PROCESSING
# ================================================================================================

def clean_review_text(text):
    """Clean and normalize review text."""
    if not text:
        return ""
    text = re.sub(r'\s+', ' ', text).strip()
    return unicodedata.normalize('NFKD', text)

def parse_date_to_yyyy_mm_dd(date_str):
    """Attempt to parse the date string into YYYY-MM-DD format."""
    if not date_str:
        return ""
    for fmt in ["%B %d, %Y", "%d %B %Y", "%Y-%m-%d"]:
        try:
            parsed = datetime.datetime.strptime(date_str, fmt).date()
            return parsed.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return date_str

# ================================================================================================
# BOOK SCRAPING
# ================================================================================================

def extract_published_date(html):
    """Extract the published date from the HTML."""
    soup = BeautifulSoup(html, "html.parser")

    # Check for expected publication
    for selector in ['p[data-testid="publicationInfo"]', 'div.BookDetails p', 'div.BookPageMetadataSection p']:
        elements = soup.select(selector)
        for element in elements:
            text = element.get_text().strip()
            if "Expected publication" in text:
                return text.replace("Expected publication", "").strip()

    # Check for published dates
    for selector in ['div.FeaturedDetails', 'p[data-testid="publicationInfo"]', 'div.BookDetails', 'div.BookPageMetadataSection']:
        element = soup.select_one(selector)
        if element:
            text = element.get_text(separator="\n").strip()
            for line in text.split("\n"):
                if "First published" in line:
                    return line.replace("First published", "").strip()
                if "Published" in line and "first" in line.lower():
                    return line.split("Published")[1].strip()

    return "January 1, 1800"

def extract_jsonld_data(html):
    """Extract and parse JSON-LD data from the HTML."""
    soup = BeautifulSoup(html, "html.parser")
    jsonld_scripts = soup.find_all("script", {"type": "application/ld+json"})
    for script in jsonld_scripts:
        try:
            content = script.string
            if not content:
                continue
            data = json.loads(content)
            if isinstance(data, list):
                for item in data:
                    if item.get("@type") == "Book":
                        return item
            else:
                if data.get("@type") == "Book":
                    return data
        except Exception as e:
            logging.error(f"Error parsing JSON-LD: {e}")

    return {}

def extract_awards(html):
    """Extract awards from the book page."""
    # Try JSON-LD first
    book_data = extract_jsonld_data(html)
    awards = []

    if "awards" in book_data:
        raw_awards = book_data["awards"]
        if isinstance(raw_awards, list):
            awards.extend(raw_awards)
        elif isinstance(raw_awards, str):
            if "," in raw_awards:
                awards.extend([award.strip() for award in raw_awards.split(",")])
            else:
                awards.append(raw_awards)

    if awards:
        return awards

    # Fallback to HTML parsing
    soup = BeautifulSoup(html, "html.parser")
    for selector in ['div.BookPageMetadataSection__awards', 'div.awards', 'section[aria-labelledby="awardsHeader"]']:
        awards_section = soup.select_one(selector)
        if awards_section:
            award_elements = awards_section.select('a, span.award')
            for award_elem in award_elements:
                award_text = award_elem.get_text(strip=True)
                if award_text and len(award_text) > 3:
                    awards.append(award_text)

    return list(set(awards))

def scrape_book_details_from_html(html, book_url):
    """Extract main details from a book page."""
    soup = BeautifulSoup(html, "html.parser")
    data = {"book_url": book_url}

    # Title
    for selector in ["h1.Text__title1", "h1.BookPageTitleSection__title"]:
        title_elem = soup.select_one(selector)
        if title_elem:
            data["title"] = title_elem.get_text(strip=True)
            break
    if "title" not in data:
        data["title"] = "No title found"

    # Author
    for selector in ["span.ContributorLink__name", "span.BookPageTitleSection__author"]:
        author_elem = soup.select_one(selector)
        if author_elem:
            data["author"] = author_elem.get_text(strip=True)
            break
    if "author" not in data:
        data["author"] = "No author found"

    # Published Date
    data["published_date"] = extract_published_date(html)

    # Page Numbers
    for selector in ['p[data-testid="pagesFormat"]', 'p.fcG']:
        pages_elem = soup.select_one(selector)
        if pages_elem:
            m = re.search(r"(\d+)", pages_elem.get_text(strip=True))
            if m:
                data["page_numbers"] = m.group(1)
                break
    if "page_numbers" not in data:
        data["page_numbers"] = None

    # Description
    for selector in ["div.TruncatedContent__text.TruncatedContent__text--expanded", "div.TruncatedContent__text", "div.BookPageMetadataSection__description"]:
        desc_elem = soup.select_one(selector)
        if desc_elem:
            data["description"] = desc_elem.get_text(strip=True)
            break
    if "description" not in data:
        data["description"] = "No description"

    # Average Rating
    for selector in ["div.RatingStatistics__rating", "span[data-testid='averageRating']", "span.RatingStatistics__rating"]:
        avg_elem = soup.select_one(selector)
        if avg_elem:
            data["average_rating"] = avg_elem.get_text(strip=True)
            break
    if "average_rating" not in data:
        data["average_rating"] = "No rating"

    # Star Distribution
    star_dist = {}
    for star in [5, 4, 3, 2, 1]:
        for selector in [f'div[data-testid="ratingBar-{star}"] div[data-testid="labelTotal-{star}"]', f'div.RatingDistributionStacked__bar--{star}']:
            star_elem = soup.select_one(selector)
            if star_elem:
                try:
                    value_text = star_elem.get_text(strip=True).replace(",", "")
                    num_match = re.search(r'(\d+)', value_text)
                    if num_match:
                        star_dist[str(star)] = int(num_match.group(1))
                    else:
                        star_dist[str(star)] = None
                except:
                    star_dist[str(star)] = None
                break
        if str(star) not in star_dist:
            star_dist[str(star)] = None

    data["star_distribution"] = star_dist
    data["awards_list"] = extract_awards(html)

    return data

# ================================================================================================
# REVIEWS SCRAPING
# ================================================================================================

def extract_reviews_from_html(html, batch_num=0):
    """Extract review data from HTML."""
    soup = BeautifulSoup(html, "html.parser")
    review_cards = soup.select("article.ReviewCard")

    reviews = []
    for card in review_cards:
        try:
            rating = None
            rating_elem = card.select_one('span[aria-label^="Rating "]')
            if rating_elem and 'aria-label' in rating_elem.attrs:
                rating_text = rating_elem['aria-label']
                if "Rating " in rating_text:
                    try:
                        rating = int(rating_text.split(" ")[1])
                    except (IndexError, ValueError):
                        pass

            text_elem = card.select_one('div[data-testid="contentContainer"] span.Formatted')
            if not text_elem:
                text_elem = card.select_one("div.TruncatedContent__text")
            review_text = clean_review_text(text_elem.get_text()) if text_elem else ""

            date_elem = card.select_one('time.CreationTime')
            if not date_elem:
                date_elem = card.select_one('span.Text.Text__body3 a')
            review_date = date_elem.get_text(strip=True) if date_elem else ""
            review_date = parse_date_to_yyyy_mm_dd(review_date)

            reviews.append({
                "review_rating": rating,
                "review_text": review_text,
                "review_date": review_date
            })
        except Exception as e:
            logging.error(f"Error extracting review: {str(e)}")

    return reviews

def scrape_reviews_with_selenium(driver, book_url, desired_count=35, existing_texts=None):
    """Scrape reviews using Selenium with dynamic loading."""
    if existing_texts is None:
        existing_texts = set()

    new_reviews = []
    review_page_url = book_url.rstrip("/") + "/reviews"

    logging.info(f"Navigating to reviews page: {review_page_url}")
    driver.get(review_page_url)

    try:
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, "article.ReviewCard")))
    except TimeoutException:
        logging.error("Timeout waiting for initial reviews to load")
        return new_reviews

    initial_html = driver.page_source
    initial_reviews = extract_reviews_from_html(initial_html, 0)

    for review in initial_reviews:
        if review["review_text"] and review["review_text"] not in existing_texts:
            new_reviews.append(review)
            existing_texts.add(review["review_text"])

    logging.info(f"Initial batch: Added {len(new_reviews)} reviews")

    batch = 1
    consecutive_no_new = 0
    max_attempts = 50

    while len(new_reviews) < desired_count and batch <= max_attempts and consecutive_no_new < 2:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1)
        close_any_overlays(driver)

        try:
            load_more_button = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "span[data-testid='loadMore']"))
            )
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", load_more_button)
            time.sleep(0.5)

            try:
                load_more_button.click()
            except Exception:
                driver.execute_script("arguments[0].click();", load_more_button)

            time.sleep(3)

            batch_html = driver.page_source
            batch_reviews = extract_reviews_from_html(batch_html, batch)

            new_count = 0
            for review in batch_reviews:
                if review["review_text"] and review["review_text"] not in existing_texts:
                    new_reviews.append(review)
                    existing_texts.add(review["review_text"])
                    new_count += 1

            logging.info(f"Batch {batch}: Added {new_count} new reviews. Total: {len(new_reviews)}")

            if new_count == 0:
                consecutive_no_new += 1
            else:
                consecutive_no_new = 0

            batch += 1

        except TimeoutException:
            logging.warning("Could not find 'Show more reviews' button. Stopping.")
            break
        except Exception as e:
            logging.error(f"Error clicking 'Show more reviews' button: {e}")
            break

    logging.info(f"Finished collecting reviews. Total: {len(new_reviews)}")
    return new_reviews[:desired_count]

# ================================================================================================
# MAIN SCRAPING FUNCTIONS
# ================================================================================================

def process_book(driver, link):
    """Process a single book: scrape details and reviews, then insert data into database."""
    logging.info(f"Processing book: {link}")

    main_html = get_page_html(driver, link, wait_for_selector="h1, div.BookPageTitleSection, div.BookDetails", wait_time=20, retries=2)

    if not main_html:
        logging.error(f"Failed to fetch main page for {link}")
        return

    book_data = scrape_book_details_from_html(main_html, link)
    logging.info(f"Scraped book: {book_data['title']}")

    # Determine review count
    total_stars = sum(x for x in book_data["star_distribution"].values() if x is not None) or 0

    if total_stars >= 700000:
        desired_review_count = 120
    elif total_stars >= 500000:
        desired_review_count = 120
    elif total_stars >= 300000:
        desired_review_count = 120
    else:
        desired_review_count = 100

    reviews = scrape_reviews_with_selenium(driver, link, desired_count=desired_review_count)
    logging.info(f"Scraped {len(reviews)} reviews for: {book_data['title']}")

    # Insert into database
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO book_info
                (title, published_date, page_numbers, description, average_rating,
                 star_dist_5, star_dist_4, star_dist_3, star_dist_2, star_dist_1, book_url)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                RETURNING id;
                """,
                (
                    book_data["title"],
                    book_data["published_date"],
                    book_data.get("page_numbers"),
                    book_data["description"],
                    book_data["average_rating"],
                    book_data["star_distribution"].get("5"),
                    book_data["star_distribution"].get("4"),
                    book_data["star_distribution"].get("3"),
                    book_data["star_distribution"].get("2"),
                    book_data["star_distribution"].get("1"),
                    link
                )
            )
            result = cur.fetchone()
            if result is None:
                cur.execute("SELECT id FROM book_info WHERE book_url = %s;", (link,))
                result = cur.fetchone()
            book_id = result[0]
            conn.commit()
            logging.info(f"Inserted book with id {book_id}")

            # Insert awards
            if book_data.get("awards_list"):
                for award in book_data["awards_list"]:
                    cur.execute(
                        """
                        INSERT INTO book_awards
                        (book_id, title, author, award)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT DO NOTHING;
                        """,
                        (book_id, book_data["title"], book_data["author"], award)
                    )
                conn.commit()
                logging.info(f"Inserted {len(book_data['awards_list'])} awards")

            # Insert reviews
            if reviews:
                review_rows = []
                for r in reviews:
                    review_rows.append((
                        book_id,
                        book_data["title"],
                        book_data["author"],
                        r["review_rating"],
                        r["review_date"],
                        r["review_text"],
                        link,
                        link.rstrip("/") + "/reviews"
                    ))
                cur.executemany(
                    """
                    INSERT INTO book_reviews
                    (book_id, title, author, review_rating, review_date, review_text, book_url, review_url)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING;
                    """,
                    review_rows
                )
                conn.commit()
                logging.info(f"Inserted {len(review_rows)} reviews")
    except Exception as e:
        logging.error(f"Error processing book {link}: {e}", exc_info=True)
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

def run_main_scraper():
    """Run the main scraper."""
    logging.info("="*80)
    logging.info("Starting main scraper")
    logging.info("="*80)

    config = load_config()
    book_links = get_book_links_from_file(config["scraping"]["book_urls_file"])

    if not book_links:
        logging.error(f"No book URLs found in {config['scraping']['book_urls_file']}")
        return

    logging.info(f"Found {len(book_links)} book URLs to process")

    driver = None
    try:
        driver = get_driver()
        logging.info("Successfully initialized WebDriver")

        for link in book_links:
            try:
                conn = get_db_connection()
                if book_already_scraped(conn, link):
                    logging.info(f"Book already in database, skipping: {link}")
                    conn.close()
                    continue
                conn.close()

                process_book(driver, link)
                respectful_delay()

            except Exception as e:
                logging.error(f"Error processing book {link}: {e}", exc_info=True)
                continue

    except Exception as e:
        logging.error(f"Error in main scraper: {e}", exc_info=True)
    finally:
        if driver:
            driver.quit()

    logging.info("="*80)
    logging.info("Main scraper completed")
    logging.info("="*80)

def run_review_enhancer():
    """Run the review enhancer."""
    logging.info("="*80)
    logging.info("Starting review enhancer")
    logging.info("="*80)

    books_to_process = get_books_for_review_enhancement()

    if not books_to_process:
        logging.info("No books need additional reviews")
        return

    logging.info(f"Found {len(books_to_process)} books that need more reviews")

    driver = None
    try:
        driver = get_driver()

        for book in books_to_process:
            try:
                logging.info(f"Processing {book['title']} - Need {book['needed_count']} more reviews")

                existing_texts = get_existing_review_texts(book['id'])
                new_reviews = scrape_reviews_with_selenium(
                    driver,
                    book['url'],
                    desired_count=book['needed_count'],
                    existing_texts=existing_texts
                )

                if new_reviews:
                    conn = get_db_connection()
                    try:
                        with conn.cursor() as cur:
                            review_rows = []
                            for r in new_reviews:
                                review_rows.append((
                                    book['id'],
                                    book['title'],
                                    book['author'],
                                    r["review_rating"],
                                    r["review_date"],
                                    r["review_text"],
                                    book['url'],
                                    book['url'].rstrip("/") + "/reviews"
                                ))

                            cur.executemany(
                                """
                                INSERT INTO public.book_reviews
                                (book_id, title, author, review_rating, review_date, review_text, book_url, review_url)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                                ON CONFLICT DO NOTHING;
                                """,
                                review_rows
                            )
                            conn.commit()
                            logging.info(f"Added {len(review_rows)} new reviews for {book['title']}")
                    finally:
                        conn.close()

                respectful_delay()

            except Exception as e:
                logging.error(f"Error processing book {book['title']}: {e}", exc_info=True)
                continue

    except Exception as e:
        logging.error(f"Error in review enhancer: {e}", exc_info=True)
    finally:
        if driver:
            driver.quit()

    logging.info("="*80)
    logging.info("Review enhancer completed")
    logging.info("="*80)

# ================================================================================================
# SCHEDULING
# ================================================================================================

def job_wrapper(job_name, job_function):
    """Wrapper for scheduled jobs with error handling and logging."""
    logging.info("="*80)
    logging.info(f"Starting scheduled job: {job_name}")
    logging.info(f"Time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logging.info("="*80)

    start_time = time.time()

    try:
        job_function()
        elapsed = time.time() - start_time
        logging.info(f"Job completed: {job_name} (Elapsed: {elapsed/60:.2f} minutes)")
    except Exception as e:
        elapsed = time.time() - start_time
        logging.error(f"Job failed: {job_name} (Error: {str(e)})", exc_info=True)

def setup_scheduler(config):
    """Set up the schedule based on configuration."""
    if not SCHEDULE_AVAILABLE:
        logging.error("Schedule module not available. Cannot setup scheduler.")
        return False

    schedule.clear()

    # Setup main scraper schedule
    if config["scheduling"]["scraper"]["enabled"]:
        sched_config = config["scheduling"]["scraper"]
        schedule_type = sched_config["schedule_type"]

        if schedule_type == "daily":
            schedule.every().day.at(sched_config["schedule_time"]).do(
                lambda: job_wrapper("Main Scraper", run_main_scraper)
            )
            logging.info(f"Main scraper scheduled: Daily at {sched_config['schedule_time']}")

        elif schedule_type == "hourly":
            interval = sched_config.get("interval_hours", 1)
            schedule.every(interval).hours.do(
                lambda: job_wrapper("Main Scraper", run_main_scraper)
            )
            logging.info(f"Main scraper scheduled: Every {interval} hour(s)")

        elif schedule_type == "weekly":
            day = sched_config.get("day_of_week", "monday")
            getattr(schedule.every(), day).at(sched_config["schedule_time"]).do(
                lambda: job_wrapper("Main Scraper", run_main_scraper)
            )
            logging.info(f"Main scraper scheduled: Weekly on {day} at {sched_config['schedule_time']}")

    # Setup review enhancer schedule
    if config["scheduling"]["enhancer"]["enabled"]:
        sched_config = config["scheduling"]["enhancer"]
        schedule_type = sched_config["schedule_type"]

        if schedule_type == "daily":
            schedule.every().day.at(sched_config["schedule_time"]).do(
                lambda: job_wrapper("Review Enhancer", run_review_enhancer)
            )
            logging.info(f"Review enhancer scheduled: Daily at {sched_config['schedule_time']}")

        elif schedule_type == "hourly":
            interval = sched_config.get("interval_hours", 1)
            schedule.every(interval).hours.do(
                lambda: job_wrapper("Review Enhancer", run_review_enhancer)
            )
            logging.info(f"Review enhancer scheduled: Every {interval} hour(s)")

        elif schedule_type == "weekly":
            day = sched_config.get("day_of_week", "monday")
            getattr(schedule.every(), day).at(sched_config["schedule_time"]).do(
                lambda: job_wrapper("Review Enhancer", run_review_enhancer)
            )
            logging.info(f"Review enhancer scheduled: Weekly on {day} at {sched_config['schedule_time']}")

    return True

def run_scheduler():
    """Run the scheduler loop."""
    if not SCHEDULE_AVAILABLE:
        print("Error: 'schedule' module not installed. Install with: pip install schedule")
        sys.exit(1)

    config = load_config()

    if not setup_scheduler(config):
        sys.exit(1)

    logging.info("\nScheduled jobs:")
    for job in schedule.get_jobs():
        logging.info(f"  - {job}")

    logging.info("\nScheduler is running. Press Ctrl+C to stop.")

    try:
        while True:
            schedule.run_pending()
            time.sleep(60)
    except KeyboardInterrupt:
        logging.info("\nScheduler stopped by user")

# ================================================================================================
# MAIN
# ================================================================================================

def setup_logging(config):
    """Set up logging configuration."""
    log_level = getattr(logging, config["logging"]["level"].upper(), logging.INFO)
    log_file = config["logging"]["log_file"]

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)

    logger = logging.getLogger()
    logger.setLevel(log_level)
    logger.handlers = []
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Goodreads Scraper - All-in-one scraping tool with scheduling",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py scrape              # Run main scraper once
  python main.py enhance             # Run review enhancer once
  python main.py schedule            # Run scheduler (continuous)
        """
    )

    parser.add_argument(
        'command',
        choices=['scrape', 'enhance', 'schedule'],
        help='Command to run'
    )

    args = parser.parse_args()

    # Load config and setup logging
    config = load_config()
    setup_logging(config)

    print("="*80)
    print("Goodreads Scraper")
    print("="*80)

    if args.command == 'scrape':
        run_main_scraper()
    elif args.command == 'enhance':
        run_review_enhancer()
    elif args.command == 'schedule':
        run_scheduler()

if __name__ == "__main__":
    main()
