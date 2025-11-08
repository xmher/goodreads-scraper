# Goodreads Scraper - Quick Start Guide

## Installation (One-Time Setup)

```bash
# 1. Install Python dependencies
pip install -r requirements.txt

# 2. Create book_urls.txt with your Goodreads book URLs
echo "https://www.goodreads.com/book/show/123456" > book_urls.txt

# 3. Update database credentials in config.json
# Edit the file and change the database settings
```

## Usage

### Run Once
```bash
# Scrape books from book_urls.txt
python main.py scrape

# Enhance reviews for existing books
python main.py enhance
```

### Run on Schedule
```bash
# Run scheduler (runs continuously)
python main.py schedule

# Or run in background
nohup python main.py schedule > output.log 2>&1 &
```

## Configuration

Edit `config.json` to customize:
- Database connection
- Scraping delays
- Schedule times
- Log settings

### Quick Config Changes

**Change schedule time:**
```json
{
    "scheduling": {
        "scraper": {
            "schedule_time": "03:00"  // Run at 3 AM
        }
    }
}
```

**Run every 6 hours instead of daily:**
```json
{
    "scheduling": {
        "scraper": {
            "schedule_type": "hourly",
            "interval_hours": 6
        }
    }
}
```

## Monitoring

```bash
# View logs
tail -f scraper.log

# Check for errors
grep ERROR scraper.log
```

## Troubleshooting

**"No module named 'psycopg2'"**
```bash
pip install -r requirements.txt
```

**"Cannot connect to database"**
- Check PostgreSQL is running
- Verify credentials in config.json

**"WebDriver not found"**
- Install Chrome browser
- webdriver-manager will auto-install ChromeDriver

## Need Help?

See the full [README.md](README.md) for detailed documentation.
