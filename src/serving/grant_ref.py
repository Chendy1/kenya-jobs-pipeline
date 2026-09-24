import os
import sys

import psycopg
from dotenv import load_dotenv
from psycopg import sql

load_dotenv()
role = sql.Identifier(sys.argv[1])

with psycopg.connect(
    host=os.getenv("POSTGRES_HOST"),
    port=os.getenv("POSTGRES_PORT"),
    dbname=os.getenv("POSTGRES_DB"),
    user=os.getenv("POSTGRES_USER"),
    password=os.environ["POSTGRES_PASSWORD"],
    connect_timeout=5,
) as conn:
    conn.execute(sql.SQL("GRANT USAGE ON SCHEMA ref TO {}").format(role))
    conn.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA ref TO {}").format(role))
    conn.execute(
        sql.SQL("ALTER DEFAULT PRIVILEGES IN SCHEMA ref GRANT SELECT ON TABLES TO {}").format(role)
    )
print("granted")
