"""Serve the daily flow on a schedule. Keep this process running.

    python -m src.flows.serve

06:00 Nairobi time = 03:00 UTC (Kenya has no daylight saving), so the cron below is in UTC.
"""
from src.flows.daily import daily_pipeline

if __name__ == "__main__":
    daily_pipeline.serve(
        name="kenya-jobs-daily",
        cron="0 3 * * *",
        tags=["kenya-jobs"],
        description="All sources -> transform -> warehouse. Idempotent; safe to re-run.",
        limit=1,  # one flow run at a time on this runner
    )