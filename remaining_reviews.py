#!/usr/bin/env python3
import time
import random
import logging
import re
import datetime
import unicodedata
import psycopg2
import os
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver import ActionChains

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

def get_books_for_review_enhancement():
    """Get books from database that need more reviews based on star count."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # Query unique books along with their review counts
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
                
                # Calculate total stars
                total_stars = 0
                for star_count in [star5, star4, star3, star2, star1]:
                    if star_count is not None:
                        total_stars += star_count
                
                # Determine desired review count based on total stars
                if total_stars >= 700000:
                    desired_count = 500
                elif total_stars >= 500000:
                    desired_count = 300
                elif total_stars >= 300000:
                    desired_count = 250
                else:
                    desired_count = 100
                
                # If we need more reviews, add to the list
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
            
            # Sort by books with most reviews needed (highest priority first)
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
                    action = ActionChains(driver)
                    action.move_by_offset(1, 1).click().perform()
                    logging.info("Clicked outside overlay to dismiss it")
                    time.sleep(1)
                except:
                    pass
                    
            return True
        return False
    except:
        return False

def clean_review_text(text):
    """Clean and normalize review text."""
    if not text:
        return ""
    # Remove excessive whitespace and normalize unicode
    text = re.sub(r'\s+', ' ', text).strip()
    return unicodedata.normalize('NFKD', text)

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
# Reviews Extraction
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
                "review_rating": rating,
                "review_text": review_text,
                "review_date": review_date
            })
        except Exception as e:
            logging.error(f"Error extracting review: {str(e)}")
    
    return reviews

def scrape_additional_reviews(driver, book_url, book_id, needed_count):
    """
    Scrape additional reviews for a book, skipping ones already in the database.
    
    Args:
        driver: Selenium WebDriver instance
        book_url: URL of the book page
        book_id: Database ID of the book
        needed_count: Number of additional reviews needed
        
    Returns:
        list: New reviews that don't exist in the database yet
    """
    # Get existing review texts to avoid duplicates
    existing_review_texts = get_existing_review_texts(book_id)
    logging.info(f"Found {len(existing_review_texts)} existing reviews in database")
    
    new_reviews = []
    review_page_url = book_url.rstrip("/") + "/reviews"
    
    logging.info(f"Navigating to reviews page: {review_page_url}")
    driver.get(review_page_url)
    
    # Wait for initial reviews to load
    try:
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, "article.ReviewCard")))
    except TimeoutException:
        logging.error("Timeout waiting for initial reviews to load")
        return new_reviews
    
    # Extract initial batch of reviews
    initial_html = driver.page_source
    initial_reviews = extract_reviews_from_html(initial_html, 0)
    
    # Add new reviews (ones that aren't in existing_review_texts)
    for review in initial_reviews:
        # Skip empty reviews
        if not review["review_text"]:
            continue
            
        # Check if this review text already exists in the database
        if review["review_text"] not in existing_review_texts:
            new_reviews.append(review)
            existing_review_texts.add(review["review_text"])  # Add to set to avoid duplicates
    
    logging.info(f"Initial batch: Added {len(new_reviews)} new reviews")
    
    # Continuously click "Show more reviews" button until we have enough reviews
    batch = 1
    consecutive_no_new = 0
    max_attempts = 50  # Maximum number of times to click "Show more" - increased for more reviews
    
    while len(new_reviews) < needed_count and batch <= max_attempts and consecutive_no_new < 2:
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
            
            # Check for new reviews (ones that aren't in existing_review_texts)
            new_count = 0
            for review in batch_reviews:
                # Skip empty reviews
                if not review["review_text"]:
                    continue
                    
                if review["review_text"] not in existing_review_texts:
                    new_reviews.append(review)
                    existing_review_texts.add(review["review_text"])  # Add to set to avoid duplicates
                    new_count += 1
            
            logging.info(f"Batch {batch}: Added {new_count} new reviews. Total new: {len(new_reviews)}")
            
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
                    # Skip empty reviews
                    if not review["review_text"]:
                        continue
                        
                    if review["review_text"] not in existing_review_texts:
                        new_reviews.append(review)
                        existing_review_texts.add(review["review_text"])  # Add to set to avoid duplicates
                        new_count += 1
                
                logging.info(f"Alternative approach - Batch {batch}: Added {new_count} new reviews. Total new: {len(new_reviews)}")
                
                if new_count == 0:
                    break  # If still no new reviews, stop trying
                
                batch += 1
            except:
                break  # If alternative approach fails, stop trying
    
    logging.info(f"Finished collecting reviews. Total new reviews: {len(new_reviews)}")
    return new_reviews

def insert_new_reviews(book_id, book_title, book_author, book_url, new_reviews):
    """Insert new reviews into the database."""
    if not new_reviews:
        logging.info("No new reviews to insert")
        return 0
    
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            review_rows = []
            for r in new_reviews:
                review_rows.append((
                    book_id,  # Use the existing book ID
                    book_title,
                    book_author,
                    r["review_rating"],
                    r["review_date"],
                    r["review_text"],
                    book_url,
                    book_url.rstrip("/") + "/reviews"
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
            
            # Check how many were actually inserted
            cur.execute("SELECT COUNT(*) FROM public.book_reviews WHERE book_id = %s", (book_id,))
            total_after = cur.fetchone()[0]
            
            logging.info(f"Inserted {len(review_rows)} new reviews for book ID {book_id}")
            logging.info(f"Total reviews for this book now: {total_after}")
            
            return len(review_rows)
            
    except Exception as e:
        logging.error(f"Error inserting reviews: {e}", exc_info=True)
        if conn:
            conn.rollback()
        return 0
    finally:
        if conn:
            conn.close()

# -------------------------------
# Main Process
# -------------------------------
def process_book_for_more_reviews(driver, book):
    """Process a single book to get more reviews."""
    book_id = book['id']
    book_url = book['url']
    book_author = book['author']
    needed_count = book['needed_count']
    title = book['title']
    
    logging.info(f"Processing book: {title} (ID: {book_id})")
    logging.info(f"Current reviews: {book['current_count']}, Desired: {book['desired_count']}, Need: {needed_count}")
    
    # Scrape additional reviews
    new_reviews = scrape_additional_reviews(driver, book_url, book_id, needed_count)
    
    # Insert new reviews into database
    if new_reviews:
        inserted_count = insert_new_reviews(book_id, title, book_author, book_url, new_reviews)
        logging.info(f"Successfully added {inserted_count} new reviews for: {title}")
    else:
        logging.info(f"No new reviews found for: {title}")

def main():
    logging.info("Starting Goodreads review enhancer script...")
    
    # Get books that need more reviews
    books_to_process = get_books_for_review_enhancement()
    
    if not books_to_process:
        logging.info("No books need additional reviews.")
        return
    
    logging.info(f"Found {len(books_to_process)} books that need more reviews.")
    
    # Show top 10 books needing most reviews
    logging.info("Top 10 books needing most reviews:")
    for i, book in enumerate(books_to_process[:10]):
        logging.info(f"{i+1}. {book['title']} - Current: {book['current_count']}, Needed: {book['needed_count']}")
    
    # Initialize WebDriver
    driver = None
    try:
        driver = get_driver()
        logging.info("Successfully initialized Selenium WebDriver")
        
        # Process each book
        for book in books_to_process:
            try:
                process_book_for_more_reviews(driver, book)
                # Add a respectful delay between books
                respectful_delay(5, 10)
            except Exception as e:
                logging.error(f"Error processing book {book['title']}: {e}", exc_info=True)
                continue
    
    except Exception as e:
        logging.error(f"Error in main process: {e}", exc_info=True)
    finally:
        # Clean up driver
        if driver:
            logging.info("Closing WebDriver")
            driver.quit()
    
    logging.info("All done enhancing reviews!")

if __name__ == "__main__":
    main()