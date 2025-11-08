#!/usr/bin/env python3
import time
import random
import logging
import re
import json
import datetime
import unicodedata
import psycopg2
import os
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

# -------------------------------
# Logging Configuration
# -------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# -------------------------------
# Database Configuration & Helpers
# -------------------------------
DB_CONFIG = {
    "host": "localhost",
    "database": "my_goodreads_db",
    "user": "postgres",
    "password": "123",
    "port": "5432"
}

def get_db_connection():
    """Establish a connection to the PostgreSQL database."""
    return psycopg2.connect(**DB_CONFIG)

def book_already_scraped(conn, url):
    """Check if a book URL is already in the book_info table."""
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM book_info WHERE book_url = %s LIMIT 1;", (url,))
        return cur.fetchone() is not None

def get_book_links_from_file(filepath):
    """Read book URLs from the given file and return as a list."""
    with open(filepath, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]

# -------------------------------
# Selenium Setup & Helpers
# -------------------------------
def get_driver():
    """Set up and return a configured Chrome WebDriver."""
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")  # Use the newer headless mode
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-notifications")
    chrome_options.add_argument("--disable-popup-blocking")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-images")  # Speed up loading by not loading images
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36")
    
    # Additional performance settings
    chrome_options.page_load_strategy = 'eager'  # Load just the DOM, don't wait for resources
    
    # Initialize the WebDriver
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    
    # Set page load timeout
    driver.set_page_load_timeout(60)  # Increase timeout
    
    return driver

def respectful_delay(min_wait=2, max_wait=5):
    """Pause for a random delay between min_wait and max_wait seconds."""
    time.sleep(random.uniform(min_wait, max_wait))

def get_page_html(driver, url, wait_for_selector=None, wait_time=20, retries=2):
    """
    Navigate to a URL and return the page HTML after waiting for specified elements.
    Now with retry mechanism.
    """
    for attempt in range(retries + 1):
        try:
            logging.info(f"Navigating to: {url} (Attempt {attempt + 1}/{retries + 1})")
            driver.get(url)
            
            # Even if we can't find the specific selectors, wait for the page to generally load
            time.sleep(5)
            
            # Wait for specific element if specified
            if wait_for_selector:
                try:
                    wait = WebDriverWait(driver, wait_time)
                    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, wait_for_selector)))
                    logging.info(f"Found selector: {wait_for_selector}")
                except TimeoutException:
                    logging.warning(f"Timeout waiting for {wait_for_selector} on {url}")
                    # Continue anyway - we'll check if we got usable content
            
            # Get the page source
            html = driver.page_source
            
            # Check if we actually got meaningful content
            if "goodreads" in html.lower() and len(html) > 5000:
                logging.info(f"Successfully fetched page: {url} (content length: {len(html)})")
                return html
            else:
                logging.warning(f"Page content seems insufficient, length: {len(html)}")
                if attempt < retries:
                    time.sleep(5)  # Wait before retrying
                    continue
        
        except Exception as e:
            logging.error(f"Error fetching {url}: {e}")
            if attempt < retries:
                time.sleep(5)  # Wait before retrying
                continue
    
    # If we've reached here, log the page source for debugging
    try:
        html = driver.page_source
        logging.info(f"Page content length: {len(html)}")
        os.makedirs("debug", exist_ok=True)
        with open(f"debug/failed_page_{int(time.time())}.html", "w", encoding="utf-8") as f:
            f.write(html)
        
        # Try to determine if we have any useful content
        if "goodreads" in html.lower() and len(html) > 5000:
            logging.info("Page may contain useful content despite selectors not found. Proceeding with caution.")
            return html
    except Exception as e:
        logging.error(f"Error saving debug HTML: {e}")
    
    return None

def click_element(driver, selector, selector_type=By.CSS_SELECTOR, wait_time=5, max_attempts=3):
    """
    Attempt to click an element and wait for page changes.
    Now with JavaScript fallback for intercepted clicks.
    """
    attempts = 0
    while attempts < max_attempts:
        try:
            wait = WebDriverWait(driver, wait_time)
            element = wait.until(EC.element_to_be_clickable((selector_type, selector)))
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
            time.sleep(0.5)  # Small delay after scrolling
            
            try:
                # Try the regular click first
                element.click()
            except Exception as click_error:
                logging.warning(f"Regular click failed: {click_error}. Trying JavaScript click...")
                # If regular click fails, try using JavaScript
                driver.execute_script("arguments[0].click();", element)
            
            time.sleep(wait_time)  # Wait for any page changes to occur
            logging.info(f"Successfully clicked element: {selector}")
            return True
        except (TimeoutException, NoSuchElementException, StaleElementReferenceException) as e:
            attempts += 1
            logging.warning(f"Attempt {attempts}/{max_attempts} failed to click {selector}: {e}")
            
            # Check if there's an overlay and try to close it
            try:
                overlays = driver.find_elements(By.CSS_SELECTOR, "div.Overlay__content, div.Modal, div.Popup")
                if overlays:
                    logging.info("Found overlay that might be blocking. Attempting to close...")
                    for overlay in overlays:
                        close_buttons = driver.find_elements(By.CSS_SELECTOR, 
                            "button.Modal__close, button.Overlay__close, button.Popup__close, button[aria-label='Close'], button.closeButton")
                        for btn in close_buttons:
                            try:
                                driver.execute_script("arguments[0].click();", btn)
                                logging.info("Clicked close button on overlay")
                                time.sleep(1)  # Wait for overlay to close
                            except:
                                pass
            except:
                pass
                
            time.sleep(1)
            
    logging.error(f"Failed to click element after {max_attempts} attempts: {selector}")
    return False

def clean_review_text(text):
    """Clean and normalize review text."""
    if not text:
        return ""
    # Remove excessive whitespace and normalize unicode
    text = re.sub(r'\s+', ' ', text).strip()
    return unicodedata.normalize('NFKD', text)

# -------------------------------
# Extract Published Date
# -------------------------------
def extract_published_date(html):
    """
    Extract the published date from the HTML.
    Handles both published and expected publication dates.
    Returns a default date of January 1, 1800 if no date is found.
    """
    soup = BeautifulSoup(html, "html.parser")
    
    # First, check for expected publication
    expected_pub_selectors = [
        'p[data-testid="publicationInfo"]',
        'div.BookDetails p',
        'div.BookPageMetadataSection p'
    ]
    
    for selector in expected_pub_selectors:
        elements = soup.select(selector)
        for element in elements:
            text = element.get_text().strip()
            if "Expected publication" in text:
                expected_date = text.replace("Expected publication", "").strip()
                logging.info(f"Found expected publication date: {expected_date}")
                return expected_date
    
    # Then check for already published dates
    selectors = [
        'div.FeaturedDetails',
        'p[data-testid="publicationInfo"]',
        'div.BookDetails',
        'div.BookPageMetadataSection'
    ]
    
    for selector in selectors:
        element = soup.select_one(selector)
        if element:
            text = element.get_text(separator="\n").strip()
            for line in text.split("\n"):
                if "First published" in line:
                    return line.replace("First published", "").strip()
                if "Published" in line and "first" in line.lower():
                    return line.split("Published")[1].strip()
    
    page_text = soup.get_text()
    match = re.search(r"First published (\w+ \d+,? \d{4})", page_text)
    if match:
        return match.group(1)
    
    # Return default date if no publication date was found
    logging.info("No publication date found, using default date (January 1, 1800)")
    return "January 1, 1800"

# -------------------------------
# JSON-LD & Awards Extraction
# -------------------------------
def extract_jsonld_data(html):
    """
    Extract and parse JSON-LD data from the HTML.
    
    Returns:
        dict: Parsed JSON-LD data for the book (or empty dict if not found)
    """
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
                        logging.info("Found Book JSON-LD data")
                        return item
            else:
                if data.get("@type") == "Book":
                    logging.info("Found Book JSON-LD data")
                    return data
        except Exception as e:
            logging.error(f"Error parsing JSON-LD: {e}")
    
    logging.warning("No Book JSON-LD data found")
    return {}

def extract_awards_from_jsonld(html):
    """Extract awards from the JSON-LD data in the page."""
    book_data = extract_jsonld_data(html)
    awards = []
    
    if "awards" in book_data:
        raw_awards = book_data["awards"]
        logging.info(f"Found awards in JSON-LD: {raw_awards}")
        if isinstance(raw_awards, list):
            awards.extend(raw_awards)
        elif isinstance(raw_awards, str):
            if "," in raw_awards:
                awards.extend([award.strip() for award in raw_awards.split(",")])
            else:
                awards.append(raw_awards)
    
    return awards

def extract_awards_from_details_page(html):
    """Extract awards from the details page after clicking the 'Book details' button."""
    soup = BeautifulSoup(html, "html.parser")
    awards = []
    
    award_selectors = [
        'span[data-testid="award"] a',
        'div.BookDetails span[data-testid="award"]',
        '.TruncatedContent__text--small span[data-testid="award"]',
        'div.BookDetails a[href*="/award/show/"]'
    ]
    
    for selector in award_selectors:
        award_elements = soup.select(selector)
        for elem in award_elements:
            award_text = elem.get_text(strip=True)
            if award_text and len(award_text) > 3:
                awards.append(award_text)
                logging.info(f"Found award: {award_text}")
    
    award_sections = soup.find_all('dt', string=lambda s: s and 'awards' in s.lower())
    for section in award_sections:
        dd = section.find_next('dd')
        if dd:
            award_links = dd.select('a[href*="/award/"]')
            for link in award_links:
                award_text = link.get_text(strip=True)
                if award_text:
                    awards.append(award_text)
                    logging.info(f"Found award in description list: {award_text}")
    
    return list(set(awards))

def extract_awards(html):
    """Extract awards from the book page using multiple strategies."""
    soup = BeautifulSoup(html, "html.parser")
    awards = []
    
    award_selectors = [
        'div.BookPageMetadataSection__awards',
        'div.uitext.items',
        'div.award',
        'div.awards',
        'section[aria-labelledby="awardsHeader"]',
        'section.awardsSection'
    ]
    
    for selector in award_selectors:
        awards_section = soup.select_one(selector)
        if awards_section:
            award_elements = awards_section.select('a, span.award')
            if award_elements:
                for award_elem in award_elements:
                    award_text = award_elem.get_text(strip=True)
                    if award_text and len(award_text) > 3:
                        awards.append(award_text)
    
    if not awards:
        award_keywords = ['award', 'prize', 'winner', 'nominee', 'finalist', 'honor']
        containers = soup.select('div.BookPageMetadataSection, div.uitext, section, div.featuredSection')
        for container in containers:
            text = container.get_text().lower()
            if any(keyword in text for keyword in award_keywords):
                lines = container.get_text(separator='\n').split('\n')
                for line in lines:
                    line = line.strip()
                    if line and any(keyword in line.lower() for keyword in award_keywords):
                        if 10 < len(line) < 200:
                            awards.append(line)
    
    award_containers = soup.select('[data-testid="awardsSection"]')
    for container in award_containers:
        award_items = container.select('[data-testid="awardItem"]')
        for item in award_items:
            award_text = item.get_text(strip=True)
            if award_text:
                awards.append(award_text)
    
    clean_awards = []
    seen = set()
    for award in awards:
        clean_award = re.sub(r'\s+', ' ', award).strip()
        if clean_award and clean_award not in seen and len(clean_award) > 3:
            seen.add(clean_award)
            clean_awards.append(clean_award)
    
    logging.info(f"Found {len(clean_awards)} awards: {clean_awards}")
    return clean_awards

# -------------------------------
# Scrape Book Details from Main Page
# -------------------------------
def scrape_book_details_from_html(html, book_url):
    """Extract main details from a book page."""
    soup = BeautifulSoup(html, "html.parser")
    data = {"book_url": book_url}
    
    # Title
    title_selectors = ["h1.Text__title1", "h1.BookPageTitleSection__title"]
    for selector in title_selectors:
        title_elem = soup.select_one(selector)
        if title_elem:
            data["title"] = title_elem.get_text(strip=True)
            break
    if "title" not in data:
        data["title"] = "No title found"
    
    # Author
    author_selectors = ["span.ContributorLink__name", "span.BookPageTitleSection__author"]
    for selector in author_selectors:
        author_elem = soup.select_one(selector)
        if author_elem:
            data["author"] = author_elem.get_text(strip=True)
            break
    if "author" not in data:
        data["author"] = "No author found"
    
    # Published Date
    data["published_date"] = extract_published_date(html)
    
    # Page Numbers
    pages_selectors = ['p[data-testid="pagesFormat"]', 'p.fcG']
    for selector in pages_selectors:
        pages_elem = soup.select_one(selector)
        if pages_elem:
            m = re.search(r"(\d+)", pages_elem.get_text(strip=True))
            if m:
                data["page_numbers"] = m.group(1)
                break
    if "page_numbers" not in data:
        data["page_numbers"] = None
    
    # Description
    desc_selectors = [
        "div.TruncatedContent__text.TruncatedContent__text--expanded",
        "div.TruncatedContent__text",
        "div.BookPageMetadataSection__description"
    ]
    for selector in desc_selectors:
        desc_elem = soup.select_one(selector)
        if desc_elem:
            data["description"] = desc_elem.get_text(strip=True)
            break
    if "description" not in data:
        data["description"] = "No description"
    
    # Average Rating
    rating_selectors = [
        "div.RatingStatistics__rating",
        "#ReviewsSection div.RatingStatistics__rating",
        "div.ReviewsSectionStatistics__ratingStatistics div.RatingStatistics__rating",
        "span[data-testid='averageRating']",
        "span.RatingStatistics__rating"
    ]
    for selector in rating_selectors:
        avg_elem = soup.select_one(selector)
        if avg_elem:
            rating_text = avg_elem.get_text(strip=True)
            data["average_rating"] = rating_text
            logging.info(f"Found rating using selector '{selector}': {rating_text}")
            break
    if "average_rating" not in data:
        data["average_rating"] = "No rating"
    
    # Star Distribution
    star_dist = {}
    for star in [5, 4, 3, 2, 1]:
        selectors = [
            f'div[data-testid="ratingBar-{star}"] div[data-testid="labelTotal-{star}"]',
            f'div.RatingDistributionStacked__bar--{star}'
        ]
        for selector in selectors:
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
    
    # If no average rating found, calculate it from star distribution
    if (not data.get("average_rating") or data.get("average_rating") == "No rating") and star_dist:
        total_ratings = 0
        weighted_sum = 0
        for star, count in star_dist.items():
            if count is not None:
                total_ratings += count
                weighted_sum += int(star) * count
        if total_ratings > 0:
            calculated_avg = weighted_sum / total_ratings
            data["average_rating"] = f"{calculated_avg:.2f}"
            logging.info(f"Calculated average rating: {data['average_rating']}")
    
    # Extract awards using JSON-LD first, then fallback to HTML
    data["awards_list"] = extract_awards_from_jsonld(html)
    if not data["awards_list"]:
        data["awards_list"] = extract_awards(html)
    
    return data

# -------------------------------
# Helper Functions for Reviews
# -------------------------------
def parse_numeric_rating(rating_str):
    """
    Extract the numeric rating from a string like "Rating 5 out of 5".
    Returns an integer (e.g., 5) or None if not found.
    """
    if not rating_str:
        return None
    match = re.search(r'(\d+)', rating_str)
    if match:
        return int(match.group(1))
    return None

def parse_date_to_yyyy_mm_dd(date_str):
    """
    Attempt to parse the date string into YYYY-MM-DD format.
    If parsing fails, return the original string.
    """
    if not date_str:
        return ""
    for fmt in ["%B %d, %Y", "%d %B %Y", "%Y-%m-%d"]:
        try:
            parsed = datetime.datetime.strptime(date_str, fmt).date()
            return parsed.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return date_str

# -------------------------------
# Reviews Extraction with Selenium
# -------------------------------
def extract_reviews_from_html(html, batch_num=0):
    """Extract review data from HTML with detailed logging based on current Goodreads structure."""
    soup = BeautifulSoup(html, "html.parser")
    
    # Save the HTML for debugging - optional, can be commented out in production
    os.makedirs("debug", exist_ok=True)
    with open(f"debug/batch_{batch_num}.html", "w", encoding="utf-8") as f:
        f.write(html)
    
    # Find all review cards
    review_cards = soup.select("article.ReviewCard")
    logging.info(f"Batch {batch_num}: Found {len(review_cards)} review cards in the HTML")
    
    reviews = []
    for card in review_cards:
        try:
            # Get review ID
            id_elem = card.select_one('a[href*="/review/show/"]')
            review_id = id_elem.get('href').split('/')[-1] if id_elem and 'href' in id_elem.attrs else None
            
            # Get rating
            rating_elem = card.select_one('span[aria-label^="Rating "]')
            rating = None
            if rating_elem and 'aria-label' in rating_elem.attrs:
                rating_text = rating_elem['aria-label']
                if "Rating " in rating_text:
                    try:
                        rating = int(rating_text.split(" ")[1])
                    except (IndexError, ValueError):
                        pass
            
            # Try to extract rating from text content if not found above
            if not rating and card.select_one('div[data-testid="contentContainer"] span.Formatted'):
                text_content = card.select_one('div[data-testid="contentContainer"] span.Formatted').get_text()
                rating_match = re.search(r'(\d+(?:\.\d+)?)/5', text_content)
                if rating_match:
                    try:
                        rating = float(rating_match.group(1))
                    except ValueError:
                        pass
            
            # Get review text
            text_elem = card.select_one('div[data-testid="contentContainer"] span.Formatted')
            if not text_elem:
                text_elem = card.select_one("div.TruncatedContent__text")
            review_text = clean_review_text(text_elem.get_text()) if text_elem else ""
            
            # Get review date
            date_elem = card.select_one('time.CreationTime')
            if not date_elem:
                date_elem = card.select_one('span.Text.Text__body3 a')
            review_date = date_elem.get_text(strip=True) if date_elem else ""
            review_date = parse_date_to_yyyy_mm_dd(review_date)
            
            reviews.append({
                "review_id": review_id,
                "review_rating": rating,
                "review_text": review_text,
                "review_date": review_date
            })
        except Exception as e:
            logging.error(f"Error extracting review: {str(e)}")
    
    return reviews

def close_any_overlays(driver):
    """Try to close any overlays that might be blocking clicks"""
    try:
        overlays = driver.find_elements(By.CSS_SELECTOR, "div.Overlay__content, div.Modal, div.Popup")
        if overlays:
            logging.info(f"Found {len(overlays)} overlay(s) that might be blocking. Attempting to close...")
            close_buttons = driver.find_elements(By.CSS_SELECTOR, 
                "button.Modal__close, button.Overlay__close, button.Popup__close, button[aria-label='Close'], button.closeButton")
            
            for btn in close_buttons:
                try:
                    driver.execute_script("arguments[0].click();", btn)
                    logging.info("Clicked close button on overlay")
                    time.sleep(1)  # Wait for overlay to close
                except:
                    pass
            
            # If we found overlays but no close buttons worked, try clicking outside the overlay
            if overlays and not close_buttons:
                try:
                    # Try clicking at the very top left of the page, which is usually outside overlays
                    action = webdriver.ActionChains(driver)
                    action.move_by_offset(1, 1).click().perform()
                    logging.info("Clicked outside overlay to dismiss it")
                    time.sleep(1)
                except:
                    pass
                    
            return True
        return False
    except:
        return False

def scrape_reviews_with_selenium(driver, book_url, desired_count=35):
    """
    Scrape reviews using Selenium with dynamic loading.
    
    Args:
        driver: Selenium WebDriver instance
        book_url: URL of the book page
        desired_count: Target number of reviews to collect
    
    Returns:
        list: A list of review dictionaries
    """
    all_reviews = []
    unique_review_ids = set()
    review_page_url = book_url.rstrip("/") + "/reviews"
    
    logging.info(f"Navigating to reviews page: {review_page_url}")
    driver.get(review_page_url)
    
    # Wait for initial reviews to load
    try:
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, "article.ReviewCard")))
    except TimeoutException:
        logging.error("Timeout waiting for initial reviews to load")
        return all_reviews
    
    # Extract initial batch of reviews
    initial_html = driver.page_source
    initial_reviews = extract_reviews_from_html(initial_html, 0)
    
    for review in initial_reviews:
        if review["review_id"] and review["review_id"] not in unique_review_ids:
            all_reviews.append(review)
            unique_review_ids.add(review["review_id"])
    
    logging.info(f"Initial batch: Added {len(initial_reviews)} reviews. Total: {len(all_reviews)}")
    
    # Continuously click "Show more reviews" button until we have enough reviews
    batch = 1
    consecutive_no_new = 0
    max_attempts = 10  # Maximum number of times to click "Show more"
    
    while len(all_reviews) < desired_count and batch <= max_attempts and consecutive_no_new < 2:
        # Scroll to bottom to make sure the "Show more" button is visible
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1)
        
        # Close any overlays that might be blocking the click
        close_any_overlays(driver)
        
        # Try to find and click the "Show more reviews" button
        try:
            load_more_button = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "span[data-testid='loadMore']"))
            )
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", load_more_button)
            time.sleep(0.5)
            
            try:
                # Try regular click first
                load_more_button.click()
            except Exception as e:
                # If that fails, try JavaScript click
                logging.warning(f"Regular click failed: {e}. Trying JavaScript click...")
                driver.execute_script("arguments[0].click();", load_more_button)
            
            # Wait for new reviews to load
            time.sleep(3)
            
            # Get new batch of reviews
            batch_html = driver.page_source
            batch_reviews = extract_reviews_from_html(batch_html, batch)
            
            # Check for new reviews
            new_count = 0
            for review in batch_reviews:
                if review["review_id"] and review["review_id"] not in unique_review_ids:
                    all_reviews.append(review)
                    unique_review_ids.add(review["review_id"])
                    new_count += 1
            
            logging.info(f"Batch {batch}: Added {new_count} new reviews. Total: {len(all_reviews)}")
            
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
            
            # If we encounter an error, try one more time with a different approach
            try:
                logging.info("Trying alternative approach to load more reviews...")
                
                # Close any overlays one more time
                close_any_overlays(driver)
                
                # Try a more direct JavaScript approach
                driver.execute_script("""
                    // Try to find the load more button and trigger its click event
                    var loadMoreBtn = document.querySelector('span[data-testid="loadMore"]');
                    if (loadMoreBtn) {
                        // Create and dispatch a click event
                        var evt = new MouseEvent('click', {
                            bubbles: true,
                            cancelable: true,
                            view: window
                        });
                        loadMoreBtn.dispatchEvent(evt);
                    }
                """)
                time.sleep(3)
                
                # Check if we got new reviews
                batch_html = driver.page_source
                batch_reviews = extract_reviews_from_html(batch_html, batch)
                
                # Process the reviews
                new_count = 0
                for review in batch_reviews:
                    if review["review_id"] and review["review_id"] not in unique_review_ids:
                        all_reviews.append(review)
                        unique_review_ids.add(review["review_id"])
                        new_count += 1
                
                logging.info(f"Alternative approach - Batch {batch}: Added {new_count} new reviews. Total: {len(all_reviews)}")
                
                if new_count == 0:
                    break  # If still no new reviews, stop trying
                
                batch += 1
            except:
                break  # If alternative approach fails, stop trying
    
    logging.info(f"Finished collecting reviews. Total unique reviews: {len(all_reviews)}")
    return all_reviews[:desired_count]  # Return only up to the desired count

# -------------------------------
# Process a Single Book & Insert Data
# -------------------------------
def process_book(driver, link):
    """Process a single book: scrape details and reviews, then insert data into database."""
    logging.info(f"Processing book: {link}")
    
    # First Load: Get Basic Book Details with better error handling
    main_html = get_page_html(
        driver, 
        link, 
        wait_for_selector="h1, div.BookPageTitleSection, div.BookDetails", 
        wait_time=20,
        retries=2
    )
    
    if not main_html:
        logging.error(f"Failed to fetch main page for {link} after retries")
        return
    
    # Extract initial book details
    book_data = scrape_book_details_from_html(main_html, link)
    
    # If rating not found, try scrolling to the reviews section
    if not book_data.get("average_rating") or book_data.get("average_rating") == "No rating":
        logging.info("Rating not found in initial load, trying to scroll to reviews section...")
        try:
            # Try to find reviews section by ID or class
            reviews_section = None
            for selector in ["#ReviewsSection", "div.ReviewsSection", "div.BookPage__reviewsSection"]:
                try:
                    reviews_section = driver.find_element(By.CSS_SELECTOR, selector)
                    break
                except NoSuchElementException:
                    continue
                    
            if reviews_section:
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", reviews_section)
                time.sleep(2)
                
                # Look for rating element
                for rating_selector in ["div.RatingStatistics__rating", "span[data-testid='averageRating']", "span.RatingStatistics__rating"]:
                    try:
                        rating_elem = driver.find_element(By.CSS_SELECTOR, rating_selector)
                        book_data["average_rating"] = rating_elem.text.strip()
                        logging.info(f"Found rating: {book_data['average_rating']}")
                        break
                    except NoSuchElementException:
                        continue
        except Exception as e:
            logging.warning(f"Error finding rating in reviews section: {e}")
    
    # If no awards were found, try clicking "Book details & editions"
    if not book_data.get("awards_list"):
        logging.info("No awards found in initial load, trying to click 'Book details & editions' button...")
        
        # Try these specific selectors based on the HTML structure
        button_selectors = [
            "button[aria-label='Book details and editions']",
            "div.BookDetails div.Button__container button",
            "span.Button__labelItem:first-of-type",
            "div.BookDetails button",
            "div.CollapsableList button"
        ]
        
        clicked = False
        # Try each selector
        for selector in button_selectors:
            try:
                # First make sure the element exists
                element = driver.find_element(By.CSS_SELECTOR, selector)
                logging.info(f"Found details button with selector: {selector}")
                
                # If we found it, try to click it
                if click_element(driver, selector, wait_time=3):
                    clicked = True
                    logging.info(f"Successfully clicked details button with selector: {selector}")
                    break
            except NoSuchElementException:
                logging.debug(f"Selector not found: {selector}")
                continue
        
        if clicked:
            # Successfully clicked, get updated HTML
            time.sleep(2)  # Give time for content to load
            details_html = driver.page_source
            
            # Try to extract awards from the new content
            details_jsonld_awards = extract_awards_from_jsonld(details_html)
            if details_jsonld_awards:
                book_data["awards_list"] = details_jsonld_awards
                logging.info(f"Found {len(details_jsonld_awards)} awards from JSON-LD after clicking 'Book details'")
            else:
                html_awards = extract_awards_from_details_page(details_html)
                if html_awards:
                    book_data["awards_list"] = html_awards
                    logging.info(f"Found {len(html_awards)} awards from HTML after clicking 'Book details'")
    
    logging.info("Scraped Book Details:")
    logging.info(json.dumps(book_data, indent=2, default=str))
    
    # Determine desired review count based on star distribution
    total_stars = sum(x for x in book_data["star_distribution"].values() if x is not None) or 0
    
    if total_stars >= 700000:
        desired_review_count = 120
    elif total_stars >= 500000:
        desired_review_count = 120
    elif total_stars >= 300000:
        desired_review_count = 120
    else:
        desired_review_count = 100
    
    # Get reviews using Selenium
    logging.info(f"Attempting to scrape {desired_review_count} reviews for: {book_data['title']}")
    reviews = scrape_reviews_with_selenium(driver, link, desired_count=desired_review_count)
    logging.info(f"Successfully scraped {len(reviews)} reviews for: {book_data['title']}")
    
    # --- Insert Data into Database ---
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            # Insert into book_info table and get book_id.
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
            logging.info(f"Inserted book: {book_data['title']} with id {book_id}")
            
            # Insert into book_awards table (if awards exist)
            if book_data.get("awards_list") and book_data["awards_list"]:
                awards = book_data["awards_list"]
                # Insert each award as its own row
                for award in awards:
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
                logging.info(f"Inserted {len(awards)} awards for: {book_data['title']}")
            else:
                logging.info(f"No awards found for: {book_data['title']} - skipping awards table insertion")
            
            # Insert into book_reviews table.
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
                logging.info(f"Inserted {len(review_rows)} reviews for: {book_data['title']}")
    except Exception as e:
        logging.error(f"Error processing book {link}: {e}", exc_info=True)
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

# -------------------------------
# Main Program
# -------------------------------
def main():
    logging.info("Starting Goodreads scraper with Selenium and improved awards & ratings extraction...")
    
    file_path = r"C:\Users\dell\Desktop\Projects\goodreads\book_urls.txt"
    try:
        book_links = get_book_links_from_file(file_path)
        logging.info(f"Found {len(book_links)} book URLs to process.")
        for link in book_links:
            logging.info(link)
    except Exception as e:
        logging.error(f"Error reading book links from file: {e}", exc_info=True)
        return
    
    if not book_links:
        logging.error("No book URLs found in book_urls.txt.")
        return
    
    # Initialize WebDriver
    driver = None
    try:
        driver = get_driver()
        logging.info("Successfully initialized Selenium WebDriver")
        
        # Process each book - now with better error handling per book
        for link in book_links:
            try:
                # Check if already scraped
                conn = get_db_connection()
                if book_already_scraped(conn, link):
                    logging.info(f"Book already in database, skipping: {link}")
                    conn.close()
                    continue
                conn.close()
                
                # Process the book - individual book errors won't crash entire script
                try:
                    process_book(driver, link)
                except Exception as book_error:
                    logging.error(f"Error processing book {link}: {book_error}", exc_info=True)
                    
                # Add a respectful delay between books
                respectful_delay(5, 10)
                
            except Exception as e:
                logging.error(f"Error checking if book is already scraped: {e}", exc_info=True)
                continue
    
    except Exception as e:
        logging.error(f"Error in main process: {e}", exc_info=True)
    finally:
        # Clean up driver
        if driver:
            logging.info("Closing WebDriver")
            driver.quit()
    
    logging.info("All done scraping & inserting data!")

if __name__ == "__main__":
    main()