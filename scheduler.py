#!/usr/bin/env python3
"""
Goodreads Scraper Scheduler
----------------------------
Automatically runs the Goodreads scraper on a scheduled basis to capture new books.

Features:
- Configurable scheduling intervals
- Runs both main scraper and review enhancer
- Comprehensive logging
- Error handling and recovery
"""

import os
import sys
import time
import logging
import schedule
import json
from datetime import datetime
from pathlib import Path

# Import the main scraper functions
try:
    from noapi import main as run_main_scraper
except ImportError:
    run_main_scraper = None
    logging.warning("Could not import main scraper (noapi.py)")

try:
    from remaining_reviews import main as run_review_enhancer
except ImportError:
    run_review_enhancer = None
    logging.warning("Could not import review enhancer (remaining_reviews.py)")

# -------------------------------
# Configuration
# -------------------------------
CONFIG_FILE = "scheduler_config.json"

DEFAULT_CONFIG = {
    "main_scraper": {
        "enabled": True,
        "schedule_time": "02:00",  # Run at 2 AM daily
        "schedule_type": "daily",  # Options: daily, hourly, weekly
        "interval_hours": None,  # Used for hourly schedule
        "day_of_week": None  # Used for weekly schedule (monday, tuesday, etc.)
    },
    "review_enhancer": {
        "enabled": True,
        "schedule_time": "04:00",  # Run at 4 AM daily
        "schedule_type": "daily",
        "interval_hours": None,
        "day_of_week": None
    },
    "logging": {
        "level": "INFO",
        "log_file": "scheduler.log",
        "max_log_size_mb": 10
    }
}

# -------------------------------
# Logging Configuration
# -------------------------------
def setup_logging(config):
    """Set up logging with rotation."""
    log_level = getattr(logging, config["logging"]["level"].upper(), logging.INFO)
    log_file = config["logging"]["log_file"]

    # Create formatter
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # File handler
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)

    # Configure root logger
    logger = logging.getLogger()
    logger.setLevel(log_level)
    logger.handlers = []  # Clear existing handlers
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger

# -------------------------------
# Configuration Management
# -------------------------------
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

    # Create default config file
    save_config(DEFAULT_CONFIG)
    logging.info(f"Created default configuration file: {CONFIG_FILE}")
    return DEFAULT_CONFIG

def save_config(config):
    """Save configuration to file."""
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=4)
        logging.info(f"Saved configuration to {CONFIG_FILE}")
    except Exception as e:
        logging.error(f"Error saving config file: {e}")

# -------------------------------
# Scheduled Job Wrappers
# -------------------------------
def job_wrapper(job_name, job_function):
    """Wrapper for scheduled jobs with error handling and logging."""
    if job_function is None:
        logging.error(f"Cannot run {job_name}: function not available")
        return

    logging.info("=" * 80)
    logging.info(f"Starting scheduled job: {job_name}")
    logging.info(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logging.info("=" * 80)

    start_time = time.time()

    try:
        job_function()
        elapsed_time = time.time() - start_time
        logging.info("=" * 80)
        logging.info(f"Job completed successfully: {job_name}")
        logging.info(f"Elapsed time: {elapsed_time:.2f} seconds ({elapsed_time/60:.2f} minutes)")
        logging.info("=" * 80)
    except Exception as e:
        elapsed_time = time.time() - start_time
        logging.error("=" * 80)
        logging.error(f"Job failed: {job_name}")
        logging.error(f"Error: {str(e)}", exc_info=True)
        logging.error(f"Elapsed time before error: {elapsed_time:.2f} seconds")
        logging.error("=" * 80)

def run_main_scraper_job():
    """Run the main scraper."""
    job_wrapper("Main Scraper (noapi.py)", run_main_scraper)

def run_review_enhancer_job():
    """Run the review enhancer."""
    job_wrapper("Review Enhancer (remaining_reviews.py)", run_review_enhancer)

# -------------------------------
# Schedule Setup
# -------------------------------
def setup_schedule(config):
    """Set up the schedule based on configuration."""
    schedule.clear()  # Clear any existing schedules

    # Setup main scraper schedule
    if config["main_scraper"]["enabled"]:
        schedule_type = config["main_scraper"]["schedule_type"]

        if schedule_type == "daily":
            schedule_time = config["main_scraper"]["schedule_time"]
            schedule.every().day.at(schedule_time).do(run_main_scraper_job)
            logging.info(f"Main scraper scheduled: Daily at {schedule_time}")

        elif schedule_type == "hourly":
            interval = config["main_scraper"].get("interval_hours", 1)
            schedule.every(interval).hours.do(run_main_scraper_job)
            logging.info(f"Main scraper scheduled: Every {interval} hour(s)")

        elif schedule_type == "weekly":
            schedule_time = config["main_scraper"]["schedule_time"]
            day = config["main_scraper"].get("day_of_week", "monday")
            getattr(schedule.every(), day).at(schedule_time).do(run_main_scraper_job)
            logging.info(f"Main scraper scheduled: Weekly on {day} at {schedule_time}")

    # Setup review enhancer schedule
    if config["review_enhancer"]["enabled"]:
        schedule_type = config["review_enhancer"]["schedule_type"]

        if schedule_type == "daily":
            schedule_time = config["review_enhancer"]["schedule_time"]
            schedule.every().day.at(schedule_time).do(run_review_enhancer_job)
            logging.info(f"Review enhancer scheduled: Daily at {schedule_time}")

        elif schedule_type == "hourly":
            interval = config["review_enhancer"].get("interval_hours", 1)
            schedule.every(interval).hours.do(run_review_enhancer_job)
            logging.info(f"Review enhancer scheduled: Every {interval} hour(s)")

        elif schedule_type == "weekly":
            schedule_time = config["review_enhancer"]["schedule_time"]
            day = config["review_enhancer"].get("day_of_week", "monday")
            getattr(schedule.every(), day).at(schedule_time).do(run_review_enhancer_job)
            logging.info(f"Review enhancer scheduled: Weekly on {day} at {schedule_time}")

# -------------------------------
# Main Scheduler Loop
# -------------------------------
def main():
    """Main scheduler loop."""
    print("=" * 80)
    print("Goodreads Scraper Scheduler")
    print("=" * 80)

    # Load configuration
    config = load_config()

    # Setup logging
    setup_logging(config)

    logging.info("Scheduler starting up...")

    # Setup schedule
    setup_schedule(config)

    # Display next run times
    logging.info("\nScheduled jobs:")
    for job in schedule.get_jobs():
        logging.info(f"  - {job}")

    logging.info("\nScheduler is running. Press Ctrl+C to stop.")
    logging.info("=" * 80)

    # Main loop
    try:
        while True:
            schedule.run_pending()
            time.sleep(60)  # Check every minute
    except KeyboardInterrupt:
        logging.info("\n" + "=" * 80)
        logging.info("Scheduler stopped by user")
        logging.info("=" * 80)
    except Exception as e:
        logging.error(f"Scheduler error: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
