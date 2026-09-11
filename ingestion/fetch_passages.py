import os
from datetime import datetime, timezone
import requests
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine

load_dotenv()
API_KEY = os.getenv("IDFM_API_KEY")
URL = "https://prim.iledefrance-mobilites.fr/marketplace/estimated-timetable?LineRef=ALL"

def first(x):
    """Extrait .value du premier élément si liste SIRI, sinon la valeur brute."""
    if isinstance(x, list) and x:
        item = x[0]
        return item.get("value") if isinstance(item, dict) else item
    return None

def fetch() -> dict:
    r = requests.get(URL, headers={"apikey": API_KEY}, timeout=120)
    r.raise_for_status()
    return r.json()

def flatten(data: dict) -> pd.DataFrame:
    delivery = data["Siri"]["ServiceDelivery"]
    response_ts = delivery["ResponseTimestamp"]
    rows = []
    for frame in delivery["EstimatedTimetableDelivery"]:
        for ejvf in frame["EstimatedJourneyVersionFrame"]:
            for j in ejvf["EstimatedVehicleJourney"]:
                ctx = {
                    "response_ts": response_ts,
                    "recorded_at": j.get("RecordedAtTime"),
                    "line_id": (j.get("LineRef") or {}).get("value"),
                    "line_name": first(j.get("PublishedLineName")),
                    "direction": (j.get("DirectionRef") or {}).get("value"),
                    "destination": first(j.get("DestinationName")),
                    "mode": first(j.get("VehicleMode")),
                    "operator": (j.get("OperatorRef") or {}).get("value"),
                    "journey_id": (j.get("DatedVehicleJourneyRef") or {}).get("value"),
                }
                calls = (j.get("EstimatedCalls") or {}).get("EstimatedCall") or []
                for c in calls:
                    rows.append({
                        **ctx,
                        "stop_id": (c.get("StopPointRef") or {}).get("value"),
                        "expected_departure": c.get("ExpectedDepartureTime"),
                        "departure_status": c.get("DepartureStatus"),
                    })
    return pd.DataFrame(rows)

ENGINE = create_engine("postgresql+psycopg2://transport:transport@localhost:5432/transport_pulse")

if __name__ == "__main__":
    df = flatten(fetch())
    df = df.drop_duplicates()          # protection anti-doublons

    # 1. Archive parquet (inchangé)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    os.makedirs("data/raw", exist_ok=True)
    df.to_parquet(f"data/raw/passages_{ts}.parquet", index=False)

    # 2. Insertion dans Postgres (append)
    df.to_sql("raw_passages", ENGINE, if_exists="append", index=False)
    print(f"{len(df):,} lignes -> data/raw + postgres.raw_passages")
