# Goodreads Scraper with Automated Scheduling

A comprehensive, all-in-one web scraper for Goodreads that automatically collects book information, reviews, ratings, and metadata. Includes automated scheduling to capture new books as they're released.

## Features

- **Unified Script**: Single `main.py` script handles all operations
- **Web Scraping**: Scrapes book details, reviews, ratings, star distributions, and awards from Goodreads
- **Database Storage**: Stores data in PostgreSQL database
- **Review Enhancement**: Automatically collects additional reviews for popular books
- **Automated Scheduling**: Runs scraper periodically to capture new books
- **Configurable**: Easy-to-use JSON configuration file
- **Comprehensive Logging**: Detailed logs for monitoring and debugging

## Prerequisites

- Python 3.7 or higher
- PostgreSQL database
- Chrome/Chromium browser (for Selenium)

## Installation

1. **Clone the repository**
   ```bash
   cd /path/to/goodreads-scraper
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up PostgreSQL database**

   Create a database named `my_goodreads_db` and set up the required tables:

   ```sql
   CREATE DATABASE my_goodreads_db;
   ```

   You'll need the following tables:
   - `book_info` - Stores book metadata
   - `book_reviews` - Stores reviews
   - `book_awards` - Stores award information

4. **Update database configuration**

   Edit `config.json` to match your PostgreSQL credentials:

   ```json
   {
       "database": {
           "host": "localhost",
           "database": "my_goodreads_db",
           "user": "your_username",
           "password": "your_password",
           "port": "5432"
       }
   }
   ```

## Quick Start

The scraper has three main modes of operation:

### 1. Run Main Scraper Once
Scrapes books from URLs listed in `book_urls.txt`:
```bash
python main.py scrape
```

### 2. Run Review Enhancer Once
Collects additional reviews for books that need more:
```bash
python main.py enhance
```

### 3. Run Automated Scheduler
Runs scrapers on a schedule continuously:
```bash
python main.py schedule
```

## Configuration

All settings are managed in `config.json`:

### Database Settings
```json
{
    "database": {
        "host": "localhost",
        "database": "my_goodreads_db",
        "user": "postgres",
        "password": "your_password",
        "port": "5432"
    }
}
```

### Scraping Settings
```json
{
    "scraping": {
        "book_urls_file": "book_urls.txt",
        "min_delay": 5,
        "max_delay": 10,
        "page_load_timeout": 60
    }
}
```

### Scheduling Settings

#### Daily Schedule (Default)
```json
{
    "scheduling": {
        "scraper": {
            "enabled": true,
            "schedule_type": "daily",
            "schedule_time": "02:00"
        },
        "enhancer": {
            "enabled": true,
            "schedule_type": "daily",
            "schedule_time": "04:00"
        }
    }
}
```

#### Hourly Schedule
```json
{
    "scheduling": {
        "scraper": {
            "enabled": true,
            "schedule_type": "hourly",
            "interval_hours": 6
        }
    }
}
```

#### Weekly Schedule
```json
{
    "scheduling": {
        "scraper": {
            "enabled": true,
            "schedule_type": "weekly",
            "schedule_time": "02:00",
            "day_of_week": "monday"
        }
    }
}
```

### Logging Settings
```json
{
    "logging": {
        "level": "INFO",
        "log_file": "scraper.log"
    }
}
```

## Usage Examples

### One-Time Scraping
```bash
# Scrape books from book_urls.txt
python main.py scrape

# Enhance reviews for existing books
python main.py enhance
```

### Scheduled Scraping
```bash
# Run scheduler in foreground
python main.py schedule

# Run scheduler in background (Linux/Mac)
nohup python main.py schedule > output.log 2>&1 &

# Run scheduler in background (using screen)
screen -dmS goodreads python main.py schedule
```

### Stop the Scheduler
```bash
# If running in foreground
Press Ctrl+C

# If running in background
pkill -f "python main.py schedule"
```

## Scheduling with System Tools

### Using systemd (Linux)

1. Create a service file `/etc/systemd/system/goodreads-scheduler.service`:

   ```ini
   [Unit]
   Description=Goodreads Scraper Scheduler
   After=network.target postgresql.service

   [Service]
   Type=simple
   User=your_username
   WorkingDirectory=/path/to/goodreads-scraper
   ExecStart=/usr/bin/python3 /path/to/goodreads-scraper/main.py schedule
   Restart=on-failure
   RestartSec=10

   [Install]
   WantedBy=multi-user.target
   ```

2. Enable and start the service:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable goodreads-scheduler
   sudo systemctl start goodreads-scheduler
   ```

3. Check status:
   ```bash
   sudo systemctl status goodreads-scheduler
   ```

### Using cron (Linux/Mac)

Alternative to using the built-in scheduler:

```bash
# Edit crontab
crontab -e

# Run main scraper daily at 2 AM
0 2 * * * cd /path/to/goodreads-scraper && python3 main.py scrape

# Run review enhancer daily at 4 AM
0 4 * * * cd /path/to/goodreads-scraper && python3 main.py enhance
```

## Monitoring

### View Logs

```bash
# View logs in real-time
tail -f scraper.log

# View recent log entries
tail -n 100 scraper.log

# Search for errors
grep ERROR scraper.log
```

### Database Queries

Check scraping progress:

```sql
-- Total books
SELECT COUNT(*) FROM book_info;

-- Total reviews
SELECT COUNT(*) FROM book_reviews;

-- Books by scrape date (if you have a timestamp column)
SELECT DATE(created_at), COUNT(*)
FROM book_info
GROUP BY DATE(created_at)
ORDER BY DATE(created_at) DESC;

-- Average reviews per book
SELECT AVG(review_count)
FROM (
    SELECT book_id, COUNT(*) as review_count
    FROM book_reviews
    GROUP BY book_id
) as counts;
```

## Troubleshooting

### Common Issues

1. **"No module named 'schedule'"**
   ```bash
   pip install schedule
   ```

2. **"Cannot connect to database"**
   - Check PostgreSQL is running
   - Verify database credentials in `DB_CONFIG`
   - Ensure database exists

3. **"WebDriver not found"**
   - Install Chrome/Chromium browser
   - The webdriver-manager should handle ChromeDriver automatically

4. **"Permission denied" on Linux**
   ```bash
   chmod +x scheduler.py
   ```

### Debugging

Enable debug logging by editing `scheduler_config.json`:

```json
{
    "logging": {
        "level": "DEBUG"
    }
}
```

## Best Practices

1. **Respectful Scraping**
   - The scripts include delays to be respectful to Goodreads servers
   - Don't decrease delay times
   - Monitor your scraping frequency

2. **Database Backups**
   ```bash
   pg_dump my_goodreads_db > backup_$(date +%Y%m%d).sql
   ```

3. **Log Rotation**
   - Logs can grow large over time
   - Consider using logrotate or clearing old logs periodically

4. **Book URLs**
   - Keep `book_urls.txt` updated with new books you want to track
   - You can add URLs from Goodreads "New Releases" or other lists

## Project Structure

```
goodreads-scraper/
├── main.py                     # All-in-one script (scraper + enhancer + scheduler)
├── config.json                 # Configuration file
├── requirements.txt            # Python dependencies
├── README.md                   # This file
├── book_urls.txt              # List of book URLs to scrape (create this file)
├── scraper.log                # Logs (created on run)
├── debug/                     # Debug HTML files (created on run)
│
├── Legacy scripts (still functional but not needed with main.py):
├── noapi.py                   # Original main scraper
├── remaining_reviews.py       # Original review enhancer
├── scheduler.py               # Original standalone scheduler
├── scheduler_config.json      # Old scheduler config
├── update_authors.py          # Author updater utility
├── update_clean.py            # SQL cleaning scripts
└── username.py                # Reviewer finder utility
```

## Contributing

Feel free to submit issues, fork the repository, and create pull requests for any improvements.

## License

This project is for educational purposes. Please respect Goodreads' Terms of Service and robots.txt when scraping.

## How It Works

### Scraping Process
1. **Main Scraper**: Reads URLs from `book_urls.txt`, scrapes book details and reviews, stores in database
2. **Review Enhancer**: Queries database for books with insufficient reviews, scrapes additional reviews
3. **Scheduler**: Runs the above operations on a configurable schedule

### Smart Review Collection
- Reviews are automatically scaled based on book popularity (star distribution)
- Popular books (700k+ stars): 500 reviews
- Very popular (500k+ stars): 300 reviews
- Popular (300k+ stars): 250 reviews
- Standard books: 100 reviews

### Duplicate Prevention
- Books already in database are skipped
- Reviews are deduplicated by text content
- Database handles conflicts with ON CONFLICT DO NOTHING

## Notes

- The scraper uses Selenium with headless Chrome for JavaScript rendering
- Database schema should be created before running the scrapers
- Review counts are automatically adjusted based on book popularity (star distribution)
- All configuration is centralized in `config.json`
- Logs are written to `scraper.log` by default

## Migration from Old Scripts

If you were using the older separate scripts (`noapi.py`, `remaining_reviews.py`, `scheduler.py`), you can easily migrate:

1. Copy your database credentials from the old scripts to `config.json`
2. Use the new commands:
   - Old: `python noapi.py` → New: `python main.py scrape`
   - Old: `python remaining_reviews.py` → New: `python main.py enhance`
   - Old: `python scheduler.py` → New: `python main.py schedule`

The old scripts will continue to work, but `main.py` provides a cleaner, unified interface.

## Support

For issues or questions, please check:
1. The logs in `scraper.log`
2. Database connection settings in `config.json`
3. Chrome/ChromeDriver installation
4. Python package versions in `requirements.txt`
5. Book URLs file (`book_urls.txt`) exists and has valid URLs
