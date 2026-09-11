from pathlib import Path
import pandas as pd
from sqlalchemy import create_engine

# Connexion Postgres (Docker)
engine = create_engine("postgresql+psycopg2://transport:transport@localhost:5432/transport_pulse")

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
