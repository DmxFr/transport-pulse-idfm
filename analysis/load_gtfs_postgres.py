"""Charge le référentiel GTFS statique IDFM (agency, routes, stops, calendar, trips, stop_times) dans PostgreSQL."""
import os
from pathlib import Path
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine

load_dotenv()

DB_URL = (
    f"postgresql+psycopg2://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
    f"@{os.getenv('POSTGRES_HOST', 'localhost')}:{os.getenv('POSTGRES_PORT', 5432)}"
    f"/{os.getenv('POSTGRES_DB')}"
)
engine = create_engine(DB_URL)

GTFS = Path("data/gtfs")

# Tables de référence : petites, on les charge entières
for name in ["agency", "routes", "stops", "calendar", "calendar_dates"]:
    df = pd.read_csv(GTFS / f"{name}.txt", dtype=str)
    df.to_sql(name, engine, if_exists="replace", index=False)
    print(f"{name}: {len(df)} lignes")

# trips.txt (45 Mo) — OK en mémoire
trips = pd.read_csv(GTFS / "trips.txt", dtype=str)
trips.to_sql("trips", engine, if_exists="replace", index=False)
print(f"trips: {len(trips)} lignes")

# stop_times.txt (737 Mo) — lecture par chunks + insertion progressive
total = 0
for i, ch in enumerate(pd.read_csv(GTFS / "stop_times.txt", dtype=str, chunksize=500_000), 1):
    # if_exists="append" après le premier chunk
    ch.to_sql("stop_times", engine, if_exists="replace" if i == 1 else "append", index=False)
    total += len(ch)
    print(f"chunk {i} — cumul : {total:,}", end="\r")
print(f"\nstop_times: {total:,} lignes ✅")
