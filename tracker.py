"""NHRA publicly accessible detailed-results collector.

Uses ordinary web pages, not an undocumented/private timing API. Be respectful
of website access controls and request rates.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
from datetime import datetime, timezone
from urllib.parse import urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup

FIELDS = ["lane", "driver", "car_number", "class", "dial_in", "rt", "ft60", "ft330",
          "ft660", "mph660", "ft1000", "et", "mph", "over_under", "mov", "first"]
HEADERS = ["Lane", "Driver", "Car No.", "Class", "Dial In", "RT", "60 FT", "330 FT",
           "660 FT", "660 MPH", "1000 FT", "ET", "MPH", "Ov/Un", "MOV", "First"]
NUMERIC = ["dial_in", "rt", "ft60", "ft330", "ft660", "mph660", "ft1000", "et", "mph", "over_under", "mov", "first"]
USER_AGENT = "NHRA-Racer-Results-Tracker/1.0 (personal-use; page-based results reader)"


def validate_url(url: str) -> str:
    p = urlparse(url.strip())
    if p.scheme != "https" or p.hostname not in ("www.nhra.com", "nhra.com"):
        raise ValueError("Use an https://www.nhra.com/results/... detailed-results page URL.")
    if not p.path.startswith("/results/") or "/detailed-results/" not in p.path:
        raise ValueError("Choose an NHRA Detailed Results category page, not the live-timing landing page.")
    return url.strip()


def parse_html(html: str, source_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    heading = soup.find(["h1", "h2"], string=re.compile(r"Race|Nationals", re.I))
    event = heading.get_text(" ", strip=True) if heading else source_url.split("/detailed-results/")[0].rstrip("/").split("/")[-1]
    category = source_url.split("/detailed-results/")[-1].split("?")[0].strip("/")
    rows = []
    # NHRA detailed results show multiple head-to-head tables. Look only at
    # tables whose headers match actual timing fields; skip summary mirrors.
    for table_index, table in enumerate(soup.select("table")):
        trs = table.select("tr")
        if not trs:
            continue
        header_index = None
        for i, tr in enumerate(trs):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"], recursive=False)]
            normalized = {re.sub(r"[^a-z0-9]+", "", s.lower()) for s in cells}
            if {"lane", "driver", "rt", "et"}.issubset(normalized) and ("60ft" in normalized):
                header_index = i
                break
        if header_index is None:
            continue
        run_index = 0
        for tr in trs[header_index + 1:]:
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"], recursive=False)]
            if len(cells) < len(FIELDS) or cells[0].strip().lower() not in {"left", "right"}:
                continue
            vals = cells[:len(FIELDS)]
            row = dict(zip(FIELDS, vals))
            raw_driver = row["driver"]
            row["winner"] = bool(re.search(r"\bWIN\b", raw_driver, re.I))
            row["driver"] = re.sub(r"\s+\bWIN\b\s*", "", raw_driver, flags=re.I).strip()
            if row["driver"] in ("--", "", "-"):
                continue
            row["event"] = event
            row["category"] = category
            row["source_url"] = source_url
            row["table_number"] = table_index
            row["pair_number"] = run_index // 2 + 1
            row["round"] = ""  # NHRA's result pages do not always encode a reliable round label.
            row["observed_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            # Avoid transient/placeholder entries without a measured time.
            if all(row[f] in ("", "--", "-") for f in ("rt", "ft60", "et")):
                continue
            for field in NUMERIC:
                if row[field] in ("", "--", "-"):
                    row[field] = None
                else:
                    try:
                        row[field] = float(row[field])
                    except ValueError:
                        row[field] = None
            identifier = "|".join([source_url, str(table_index), str(row["pair_number"]),
                                   row["lane"], row["driver"], row["car_number"],
                                   str(row["rt"]), str(row["et"])])
            row["record_id"] = hashlib.sha256(identifier.encode()).hexdigest()
            rows.append(row)
            run_index += 1
    return rows


def download_results(url: str) -> list[dict]:
    url = validate_url(url)
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=25)
    resp.raise_for_status()
    results = parse_html(resp.text, url)
    if not results:
        raise ValueError("No timing rows found. This page may have no published results yet, or NHRA may have changed its HTML layout.")
    return results


def connect(path: str = "nhra_runs.sqlite3") -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute("CREATE TABLE IF NOT EXISTS runs (record_id TEXT PRIMARY KEY, source_url TEXT NOT NULL, driver TEXT, car_number TEXT, data_json TEXT NOT NULL)")
    conn.commit()
    return conn


def save_rows(conn: sqlite3.Connection, rows: list[dict]) -> int:
    import json
    count = 0
    for row in rows:
        cursor = conn.execute("INSERT OR IGNORE INTO runs(record_id,source_url,driver,car_number,data_json) VALUES (?,?,?,?,?)",
                              (row["record_id"], row["source_url"], row["driver"], row["car_number"], json.dumps(row)))
        count += cursor.rowcount
    conn.commit()
    return count


def read_rows(conn: sqlite3.Connection) -> pd.DataFrame:
    import json
    rows = [json.loads(r[0]) for r in conn.execute("SELECT data_json FROM runs")]
    return pd.DataFrame(rows)


def filter_driver(frame: pd.DataFrame, name: str, number: str) -> pd.DataFrame:
    if frame.empty:
        return frame
    mask = pd.Series(True, index=frame.index)
    if name.strip():
        mask &= frame["driver"].str.contains(re.escape(name.strip()), case=False, na=False)
    if number.strip():
        mask &= frame["car_number"].astype(str).str.strip().str.casefold().eq(number.strip().casefold())
    return frame.loc[mask].copy()


def matching_row(row: dict, name: str, number: str) -> bool:
    """Match names by words and car number exactly; both must match if supplied."""
    if not (name.strip() or number.strip()):
        return False
    if number.strip() and str(row.get("car_number", "")).strip().casefold() != number.strip().casefold():
        return False
    if name.strip():
        pattern = r"\b" + r"\s+".join(re.escape(part) for part in name.strip().split()) + r"\b"
        if not re.search(pattern, str(row.get("driver", "")), re.I):
            return False
    return True
