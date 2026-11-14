"""NHRA public detailed-results eliminations reader.

Reads HTML published by NHRA. This does NOT use NHRA's dynamically delivered
live-timing feed. Winner-marked pairs and solo byes are supported.
"""
import hashlib
import re
from datetime import datetime, timezone
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from tracker import FIELDS, NUMERIC
from discovery import BASE, fetch


def category_url(event_url, slug):
    p = urlparse(event_url)
    if p.scheme != 'https' or p.hostname not in ('www.nhra.com','nhra.com') or not p.path.startswith('/results/'):
        raise ValueError('Invalid NHRA event URL')
    return BASE + p.path.rstrip('/') + '/detailed-results/' + slug


def clean(v):
    return re.sub(r'\s+', ' ', v or '').strip()


def normalized_header(v):
    return re.sub(r'[^a-z0-9]', '', v.casefold())


def parse_eliminations(html, url, event, category, selected_round=None):
    soup = BeautifulSoup(html, 'lxml')
    results = []
    # Each standard NHRA timing table has the same 16-column header.
    for ti, table in enumerate(soup.select('table')):
        trs = table.find_all('tr')
        for hindex, tr in enumerate(trs):
            head = [normalized_header(c.get_text(' ', strip=True)) for c in tr.find_all(['th','td'], recursive=False)]
            if len(head) < 16 or head[:3] != ['lane', 'driver', 'carno'] or '60ft' not in head or 'et' not in head:
                continue
            pair = []
            for subsequent in trs[hindex + 1:]:
                cells = [clean(c.get_text(' ', strip=True)) for c in subsequent.find_all(['th','td'], recursive=False)]
                if cells and normalized_header(cells[0]) == 'lane':
                    break
                if len(cells) < 16 or cells[0].lower() not in ('left', 'right'):
                    continue
                row = dict(zip(FIELDS, cells[:16]))
                raw_name = row['driver']
                row['winner'] = bool(re.search(r'\bWIN\b|\bW\b$', raw_name, re.I))
                row['driver'] = re.sub(r'\s*\b(?:WIN|W)\b\s*$', '', raw_name, flags=re.I).strip()
                pair.append(row)
                if len(pair) == 2:
                    # Winners are only shown on elimination time slips; also
                    # handles byes with a '--' placeholder in the other lane.
                    if any(p['winner'] for p in pair) and {p['lane'].lower() for p in pair} == {'left','right'}:
                        pair_id = len(results) // 2
                        for r in pair:
                            if r['driver'] in ('', '--', '-') or r['car_number'] in ('', '--', '-'):
                                continue
                            if all(r.get(k) in ('','--','-') for k in ('rt','ft60','et')):
                                continue
                            for key in NUMERIC:
                                try:
                                    r[key] = float(r[key])
                                except (ValueError, TypeError):
                                    r[key] = None
                            prior = table.find_previous(['h2','h3','h4'])
                            label = clean(prior.get_text(' ', strip=True)) if prior else ''
                            round_name = selected_round or (label[:80] if re.search(r'round|semi.?final|quarter.?final', label, re.I) else 'Elimination (round unspecified)')
                            r.update(event=event['name'], kind=event['kind'], division=event['division'],
                                     event_url=event['url'], source_url=url, category=category,
                                     round=round_name, pair_number=pair_id + 1,
                                     observed_at=datetime.now(timezone.utc).isoformat(timespec='seconds'))
                            # Do not include volatile time in fingerprint.
                            raw_id = '|'.join([event['url'], category, round_name, str(ti), str(hindex), str(pair_id), r['lane'],
                                               r['car_number'], r['driver'], str(r['rt']), str(r['et'])])
                            r['record_id'] = hashlib.sha256(raw_id.encode()).hexdigest()
                            results.append(r)
                    pair = []
            # Only first timing header per table.
            break
    return results


def fetch_eliminations(event, slug, category):
    url = category_url(event['url'], slug)
    return parse_eliminations(fetch(url), url, event, category)


def fetch_all_elimination_rounds(event, slug, category, shared_browser=None):
    """Browse the NHRA Round dropdown and collect every selectable elimination round."""
    from round_browser import collect_rendered_rounds
    url = category_url(event['url'], slug)
    return collect_rendered_rounds(url, parse_eliminations, event, category, shared_browser=shared_browser)
