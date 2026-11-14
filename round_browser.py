"""Collect published NHRA elimination rounds by operating the site's Round selector.

Uses Microsoft Edge already installed on Windows. Does NOT access a private API.
Every round is collected from a fresh rendered DOM, with an explicit round label.
"""
from __future__ import annotations
import re
from bs4 import BeautifulSoup

ROUND_RE = re.compile(r'(?i)\b(?:round\s*\d+|\d+(?:st|nd|rd|th)\s+round|(?:quarter|semi)?\s*finals?|eliminations?\s*(?:round\s*)?\d+|(?:E|R)\s*[-#]?\s*\d+)\b')


def _clean(s):
    return re.sub(r'\s+', ' ', str(s or '')).strip()


def _is_round_option(label):
    s = _clean(label).lower()
    return bool(ROUND_RE.search(s)) and not bool(re.search(r'qualif|practice|time trial', s))


def _round_label(label):
    s = _clean(label)
    return s if s else 'Round not specified'


def get_rounds_from_select_html(html):
    """Find native HTML round dropdown; return (selector index, [(value,label)])."""
    soup = BeautifulSoup(html, 'lxml')
    selects = soup.find_all('select')
    for ix, sel in enumerate(selects):
        options = [(_clean(opt.get('value')), _clean(opt.get_text(' ', strip=True)))
                   for opt in sel.find_all('option')]
        actual = [(v, t) for v,t in options if _is_round_option(t) or (_clean(t).isdigit() and re.search('round',_clean(' '.join([sel.get('name',''),sel.get('id',''),sel.get('aria-label','')])) , re.I))]
        assoc = _clean(' '.join([sel.get('aria-label',''),sel.get('name',''),sel.get('id',''),
                                  sel.parent.get_text(' ', strip=True)[:150] if sel.parent else '']))
        if actual and ('round' in assoc.lower() or len(actual)>1):
            return ix, actual
    return None, []


def collect_rendered_rounds(url, parse_fn, event, category, timeout_ms=14000, shared_browser=None):
    """Return (runs, info) after selecting all published elimination rounds.

    parse_fn(html, source_url, event, category, round_label) must return records.
    Raises a helpful error when Edge/Playwright isn't available.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as ex:
        raise RuntimeError('Browser round collection needs Playwright. Run: py -3.13 -m pip install -r requirements.txt') from ex
    scans, warnings = [], []
    from contextlib import nullcontext
    runner = nullcontext(None) if shared_browser is not None else sync_playwright()
    with runner as p:
        try:
           browser = shared_browser or p.chromium.launch(executable_path='/usr/bin/chromium', headless=True, args=['--no-sandbox', '--disable-extensions'])
        except Exception as ex:
            raise RuntimeError('Could not open Microsoft Edge for round collection: '+str(ex)[:180]) from ex
        try:
            page = browser.new_page(viewport={'width': 1440, 'height': 900}, locale='en-US')
            page.goto(url, wait_until='domcontentloaded', timeout=timeout_ms)
            page.wait_for_timeout(550)
            # Option lists can be inserted after AJAX loads.
            html = page.content()
            index, options = get_rounds_from_select_html(html)
            if index is None:
                # Selectors implemented with custom ARIA combobox are common.
                # Attempt to open the UI's Round combobox and click its round options.
                options = _collect_custom_round_options(page)
                if options:
                    for label in options:
                        try:
                            page.goto(url, wait_until='domcontentloaded', timeout=timeout_ms)
                            page.wait_for_timeout(300)
                            _select_custom_round(page, label)
                            page.wait_for_timeout(450)
                            rows = parse_fn(page.content(), page.url, event, category, label)
                            scans.append({'round':label,'rows':rows})
                        except Exception as ex:
                            warnings.append(f'{label}: {_clean(str(ex))[:150]}')
                else:
                    # Do not misrepresent final/default view as every round.
                    rows = parse_fn(html, url, event, category, 'Round unverified (default view)')
                    scans.append({'round':'Round unverified (default view)','rows':rows})
                    warnings.append('Could not detect NHRA Round dropdown. Only default page was read; earlier rounds are NOT confirmed.')
            else:
                # Include only actual round options, never qualifying.
                for value, label in options:
                    try:
                        page.goto(url, wait_until='domcontentloaded', timeout=timeout_ms)
                        page.wait_for_timeout(250)
                        loc = page.locator('select').nth(index)
                        if value:
                            loc.select_option(value=value, timeout=7000)
                        else:
                            loc.select_option(label=label, timeout=7000)
                        page.wait_for_timeout(450)
                        rows = parse_fn(page.content(), page.url, event, category, label)
                        scans.append({'round':label,'rows':rows})
                    except Exception as ex:
                        warnings.append(f'{label}: {_clean(str(ex))[:150]}')
        finally:
            try:
                page.close()
            except Exception:
                pass
            if shared_browser is None:
                browser.close()
    # Dedupe only exact same round+event+lane+driver+car+timing; never remove
    # the same driver's runs in distinct elimination rounds.
    # If the site ignores our round selection and serves the same time slips,
    # never silently count a final multiple times as different rounds.
    seen_signatures = set()
    verified_scans = []
    for part in scans:
        signature = tuple(sorted((r.get('car_number'),r.get('driver'),r.get('et'),r.get('rt')) for r in part['rows']))
        if part['rows'] and signature in seen_signatures:
            warnings.append(f"{part['round']}: identical timing rows to an earlier selection; round not counted (possible NHRA selector issue).")
            continue
        if signature:
            seen_signatures.add(signature)
        verified_scans.append(part)
    scans = verified_scans
    unique = {r['record_id']:r for part in scans for r in part['rows']}
    info = {'rounds': [(x['round'],len(x['rows'])) for x in scans],
            'warnings':warnings, 'round_count':len(scans),
            'verified_rounds':sum(x['round']!='Round unverified (default view)' for x in scans)}
    return list(unique.values()), info


def _collect_custom_round_options(page):
    """Probe accessible custom dropdown, without assuming NHRA's UI framework."""
    try:
        # Prefer round-labelled controls.
        candidates = page.get_by_role('combobox', name=re.compile('round',re.I))
        if candidates.count():
            candidates.first.click(timeout=4000)
        else:
            # Label may be a separate sibling; try a visible Round caption.
            caption = page.get_by_text('Round', exact=True)
            if not caption.count():
                return []
            caption.first.click(timeout=3000)
        page.wait_for_timeout(250)
        labels = page.locator('[role="option"], [role="menuitem"], li').all_text_contents()
        return list(dict.fromkeys(_clean(s) for s in labels if _is_round_option(s)))[:25]
    except Exception:
        return []


def _select_custom_round(page, label):
    c = page.get_by_role('combobox', name=re.compile('round',re.I))
    if c.count():
        c.first.click()
    else:
        page.get_by_text('Round',exact=True).first.click()
    opt = page.get_by_role('option', name=label, exact=True)
    if opt.count():
        opt.first.click()
    else:
        page.get_by_text(label, exact=True).last.click()
