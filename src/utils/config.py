import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"

ADZUNA_APP_ID = os.getenv("ADZUNA_APP_ID")
ADZUNA_APP_KEY = os.getenv("ADZUNA_APP_KEY")
POSTGRES_URL = os.getenv("POSTGRES_URL")
CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "you@example.com")
CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "you@example.com")
