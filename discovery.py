"""Discover NHRA national races and actual Lucas Oil divisional events only.

The NHRA divisional-live-timing page also contains an OTHER EVENTS section
(Jr. finals, Hot Rod Reunion, ET finals, regional races, etc.). Only links
inside an explicit DIVISION 1–7 heading are allowed into divisional searches.
"""
import re
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup

BASE = 'https://www.nhra.com'
DIVISION_PAGES = {2026: '/divisional-live-timing', 2025: '/divisional-live-timing-2025', 2024: '/divisional-live-timing-2024', 2023: '/divisional-live-timing-2023'}
NATIONAL_SERIES = 'nhra-mission-foods-drag-racing-series'
CATEGORIES = {'Super Comp': 'super-comp'}
HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; NHRA-results-personal-tracker/3.0)'}

def fetch(url):
    r = requests.get(url, headers=HEADERS, timeout=18)
    r.raise_for_status()
    return r.text

def parse_nationals(html, year):
    soup = BeautifulSoup(html, 'html.parser')
    pattern = re.compile(rf'^/results/{year}/{NATIONAL_SERIES}/\d+/?$')
    seen, results = set(), []
    for a in soup.select('a[href]'):
        parsed = urlparse(urljoin(BASE, a['href']))
        if parsed.hostname not in {'nhra.com', 'www.nhra.com'} or not pattern.fullmatch(parsed.path):
            continue
        url = BASE + parsed.path.rstrip('/')
        if url in seen: continue
        seen.add(url)
        label = a.get_text(' ', strip=True)
        if label.lower() == 'results':
            label = (a.parent.get_text(' ', strip=True) or label)[:140]
        results.append({'name': label or url.split('/')[-1], 'url': url, 'kind': 'National', 'division': None})
    return results

DIVISION_HEADING = re.compile(r'^DIVISION\s*([1-7])$', re.I)
EXCLUDED = re.compile(r'\b(?:hot\s*rod\s*reunion|junior|jr\.?\s*drag|jrdl|et\s*finals?|bracket\s*finals?|national\s*open|regional)\b', re.I)

def parse_divisions(html, year):
    soup = BeautifulSoup(html, 'html.parser')
    pattern = re.compile(rf'^/results/{year}/lucas-oil-drag-racing-series/d([1-7])/\d{{8}}/?$')
    seen, events = set(), []
    # For each results link, find the nearest preceding section heading. This
    # excludes OTHER EVENTS, even if NHRA gives those links a Division URL.
    for a in soup.select('a[href]'):
        parsed = urlparse(urljoin(BASE, a['href']))
        if parsed.hostname not in {'nhra.com', 'www.nhra.com'}: continue
        match = pattern.fullmatch(parsed.path)
        if not match: continue
        heading = a.find_previous(re.compile('^h[1-6]$'))
        heading_text = heading.get_text(' ', strip=True) if heading else ''
        heading_match = DIVISION_HEADING.fullmatch(heading_text)
        if not heading_match or int(heading_match.group(1)) != int(match.group(1)):
            continue
        row = a.find_parent('tr')
        name = row.get_text(' ', strip=True) if row else a.parent.get_text(' ', strip=True)
        name = re.sub(r'\s*Results\s*$', '', name, flags=re.I).strip()
        if EXCLUDED.search(name): continue
        url = BASE + parsed.path.rstrip('/')
        if url in seen: continue
        seen.add(url)
        events.append({'name': (name or f'Division {match.group(1)} – {parsed.path.rstrip("/").split("/")[-1]}')[:180],
                       'url':url, 'kind':'Divisional', 'division':int(match.group(1))})
    return events

def discover(year, kind, divisions=None):
    if not 2020 <= year <= 2035: raise ValueError('Invalid season')
    if kind == 'National':
        url = f'{BASE}/results/{year}/{NATIONAL_SERIES}'
        result = parse_nationals(fetch(url), year)
    else:
        path = DIVISION_PAGES.get(year, f'/divisional-live-timing-{year}')
        url = BASE + path
        result = parse_divisions(fetch(url), year)
        if divisions: result = [e for e in result if e['division'] in divisions]
    if not result: raise ValueError(f'No eligible events found at {url}; NHRA may have changed its directory format.')
    return result, url
