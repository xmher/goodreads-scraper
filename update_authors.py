import psycopg2
import logging

# Database Configuration
DB_CONFIG = {
    "host": "localhost",
    "database": "my_goodreads_db",
    "user": "postgres",
    "password": "123",
    "port": "5432"
}

def add_author_column():
    """Add 'author' column to book_info table if it doesn't exist."""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()

        # Check if 'author' column exists
        cur.execute("""
            SELECT column_name FROM information_schema.columns 
            WHERE table_name = 'book_info' AND column_name = 'author';
        """)
        column_exists = cur.fetchone()

        if not column_exists:
            # Add the 'author' column
            cur.execute("ALTER TABLE book_info ADD COLUMN author TEXT;")
            conn.commit()
            logging.info("Added 'author' column to book_info table.")
        else:
            logging.info("Column 'author' already exists in book_info table.")

        cur.close()
        conn.close()
    except Exception as e:
        logging.error(f"Error adding author column: {e}")

def update_authors():
    """Update the book_info table with authors from the book_reviews table."""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()

        logging.info("Fetching authors from book_reviews...")

        # Select first instance of author per book_id from book_reviews
        cur.execute("""
            SELECT DISTINCT ON (book_id) book_id, author
            FROM book_reviews
            WHERE author IS NOT NULL
            ORDER BY book_id, id ASC;
        """)
        authors = cur.fetchall()

        logging.info(f"Found {len(authors)} unique books with author data.")

        # Update book_info table with author names
        update_query = """
            UPDATE book_info
            SET author = %s
            WHERE id = %s;
        """

        updated_count = 0
        for book_id, author in authors:
            cur.execute(update_query, (author, book_id))
            updated_count += 1

        # Commit changes and close connection
        conn.commit()
        logging.info(f"Successfully updated {updated_count} books with authors.")

        cur.close()
        conn.close()
    except Exception as e:
        logging.error(f"Error updating authors: {e}")
        conn.rollback()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    add_author_column()  # Add the column first
    update_authors()  # Then populate it
