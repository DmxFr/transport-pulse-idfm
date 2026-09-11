import glob
import pandas as pd

LINE = "C01100"        # ligne 64
TOLERANCE_S = 1800     # max 30 min entre horaire théorique et estimé

# ---- 1. GTFS : les trips de la ligne 64
trips = pd.read_csv("data/gtfs/trips.txt", usecols=["route_id", "trip_id"], dtype=str)
trip_ids = set(trips.loc[trips.route_id == f"IDFM:{LINE}", "trip_id"])
print(f"Trips ligne 64 : {len(trip_ids)}")

# ---- 2. GTFS : horaires théoriques (lecture par chunks car 737 Mo !)
parts = []
for ch in pd.read_csv("data/gtfs/stop_times.txt",
                      usecols=["trip_id", "arrival_time", "stop_id"],
                      dtype=str, chunksize=2_000_000):
    m = ch[ch.trip_id.isin(trip_ids)]
    if len(m):
        parts.append(m)
st = pd.concat(parts, ignore_index=True)
st["secs_theo"] = pd.to_timedelta(st.arrival_time).dt.total_seconds()
theo = st[["stop_id", "secs_theo"]].copy()
theo["secs"] = theo["secs_theo"]   # colonne de jointure (consommée par merge_asof)
theo = theo.sort_values("secs")
print(f"Horaires théoriques ligne 64 : {len(theo)}")

# ---- 3. Temps réel : passages capturés de la ligne 64
f = sorted(glob.glob("data/raw/passages_*.parquet"))[-1]
tr = pd.read_parquet(f)
tr = tr[tr.line_id == f"STIF:Line::{LINE}:"].copy()
tr = tr.dropna(subset=["expected_departure"])
tr["stop_id"] = "IDFM:" + tr["stop_id"].str.split(":").str[-2]
# ⚠️ Piège timezone : le flux est en UTC, le GTFS en heure locale Paris !
ts = pd.to_datetime(tr["expected_departure"], utc=True, format="ISO8601").dt.tz_convert("Europe/Paris")
tr["secs"] = ts.dt.hour * 3600 + ts.dt.minute * 60 + ts.dt.second
print(f"Passages TR ligne 64 : {len(tr)}")

# ---- 4. Harmonisation stricte des dtypes (Parquet vs CSV)
tr["stop_id"] = tr["stop_id"].astype("string")
theo["stop_id"] = theo["stop_id"].astype("string")
tr["secs"] = tr["secs"].astype("int64")
theo["secs"] = theo["secs"].astype("int64")

# ---- 5. Retard = écart avec l'horaire théorique LE PLUS PROCHE (même arrêt)
merged = pd.merge_asof(tr.sort_values("secs"), theo,
                       on="secs", by="stop_id",
                       direction="nearest", tolerance=TOLERANCE_S)
merged["delay_min"] = (merged["secs"] - merged["secs_theo"]) / 60
ok = merged.dropna(subset=["delay_min"])

print(f"\nMatchés : {len(ok)}/{len(merged)}")
print(ok["delay_min"].describe())
print("\nDistribution par tranches :")
print(pd.cut(ok["delay_min"], [-30, -5, -2, 2, 5, 15, 30, 60]).value_counts().sort_index())