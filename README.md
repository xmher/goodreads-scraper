# Goodreads Scraper with Automated Scheduling

A comprehensive web scraper for Goodreads that automatically collects book information, reviews, ratings, and metadata. Includes automated scheduling to capture new books as they're released.

## Features

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

   Edit the `DB_CONFIG` in the following files to match your PostgreSQL credentials:
   - `noapi.py`
   - `remaining_reviews.py`
   - `update_authors.py`

   ```python
   DB_CONFIG = {
       "host": "localhost",
       "database": "my_goodreads_db",
       "user": "your_username",
       "password": "your_password",
       "port": "5432"
   }
   ```

## Scripts Overview

### Main Scripts

1. **`noapi.py`** - Main scraper
   - Scrapes book details from URLs listed in `book_urls.txt`
   - Collects reviews, ratings, descriptions, and awards
   - Stores data in PostgreSQL database

2. **`remaining_reviews.py`** - Review enhancer
   - Automatically collects additional reviews for books that need more
   - Prioritizes popular books (based on star distribution)
   - Avoids duplicate reviews

3. **`scheduler.py`** - Automated scheduler (NEW!)
   - Runs scrapers on a scheduled basis
   - Configurable scheduling intervals
   - Comprehensive logging and error handling

4. **`update_authors.py`** - Database maintenance
   - Updates author information in the database

### Utility Scripts

- **`username.py`** - Finds Goodreads reviewers by review snippet

## Using the Scheduler

### Quick Start

1. **Configure the schedule** (optional)

   Edit `scheduler_config.json` to customize when scrapers run:

   ```json
   {
       "main_scraper": {
           "enabled": true,
           "schedule_time": "02:00",
           "schedule_type": "daily"
       },
       "review_enhancer": {
           "enabled": true,
           "schedule_time": "04:00",
           "schedule_type": "daily"
       }
   }
   ```

2. **Run the scheduler**
   ```bash
   python scheduler.py
   ```

   The scheduler will run continuously and execute your scrapers at the configured times.

3. **Run in background** (Linux/Mac)
   ```bash
   nohup python scheduler.py > scheduler_output.log 2>&1 &
   ```

4. **Stop the scheduler**
   - Press `Ctrl+C` if running in foreground
   - Or find and kill the process: `pkill -f scheduler.py`

### Configuration Options

#### Schedule Types

1. **Daily** - Run at a specific time each day
   ```json
   {
       "schedule_type": "daily",
       "schedule_time": "02:00"
   }
   ```

2. **Hourly** - Run every N hours
   ```json
   {
       "schedule_type": "hourly",
       "interval_hours": 6
   }
   ```

3. **Weekly** - Run on a specific day and time
   ```json
   {
       "schedule_type": "weekly",
       "schedule_time": "02:00",
       "day_of_week": "monday"
   }
   ```

#### Logging Configuration

```json
{
    "logging": {
        "level": "INFO",
        "log_file": "scheduler.log",
        "max_log_size_mb": 10
    }
}
```

## Manual Usage

### Running Individual Scripts

1. **Main Scraper**
   ```bash
   python noapi.py
   ```
   Requires: `book_urls.txt` file with Goodreads book URLs (one per line)

2. **Review Enhancer**
   ```bash
   python remaining_reviews.py
   ```
   Automatically identifies books needing more reviews

3. **Update Authors**
   ```bash
   python update_authors.py
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
   ExecStart=/usr/bin/python3 /path/to/goodreads-scraper/scheduler.py
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

Alternative to using `scheduler.py`, you can use cron:

```bash
# Edit crontab
crontab -e

# Run main scraper daily at 2 AM
0 2 * * * cd /path/to/goodreads-scraper && python3 noapi.py

# Run review enhancer daily at 4 AM
0 4 * * * cd /path/to/goodreads-scraper && python3 remaining_reviews.py
```

## Monitoring

### View Logs

```bash
# View scheduler logs
tail -f scheduler.log

# View recent log entries
tail -n 100 scheduler.log

# Search for errors
grep ERROR scheduler.log
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
├── noapi.py                    # Main scraper
├── remaining_reviews.py        # Review enhancer
├── scheduler.py                # Automated scheduler
├── scheduler_config.json       # Scheduler configuration
├── update_authors.py           # Author updater
├── update_clean.py             # SQL cleaning scripts
├── username.py                 # Reviewer finder
├── requirements.txt            # Python dependencies
├── README.md                   # This file
├── book_urls.txt              # List of book URLs to scrape
├── scheduler.log              # Scheduler logs (created on run)
└── debug/                     # Debug HTML files (created on run)
```

## Contributing

Feel free to submit issues, fork the repository, and create pull requests for any improvements.

## License

This project is for educational purposes. Please respect Goodreads' Terms of Service and robots.txt when scraping.

## Notes

- The scraper uses Selenium with headless Chrome for JavaScript rendering
- Database schema should be created before running the scrapers
- Review counts are automatically adjusted based on book popularity (star distribution)
- The scheduler will create default configuration if none exists

## Support

For issues or questions, please check:
1. The logs in `scheduler.log`
2. Database connection settings
3. Chrome/ChromeDriver installation
4. Python package versions in `requirements.txt`
