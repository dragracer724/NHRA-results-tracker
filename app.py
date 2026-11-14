"""NHRA published elimination season tracker. Run: py -3.13 -m streamlit run app.py"""
from datetime import date, datetime
import re
import time
import pandas as pd
import streamlit as st
from discovery import CATEGORIES, discover
from eliminations import fetch_all_elimination_rounds
from tracker import connect, matching_row, read_rows, save_rows
from index_stats import FIXED_INDEX, VARIABLE, enrich, driver_averages
from speed_stats import speed_summary, slow_mph_outliers

st.set_page_config(page_title='NHRA Season Elimination Tracker', page_icon='🏁', layout='wide')
st.title('🏁 NHRA Super Comp Season Tracker')
st.caption('Super Comp (8.90 index) · elimination rounds only · national and Lucas Oil divisional events')
st.info('Source: NHRA public Detailed Results (not the direct live feed). Results may be delayed or incomplete. A season search must finish to check every listed event.')

with st.sidebar:
    st.header('Racer / season')
    scope = st.radio('Tracking mode', ['One driver', 'Every driver'], horizontal=True)
    driver = st.text_input('Driver name', placeholder='Full name or surname', disabled=scope == 'Every driver')
    number = st.text_input('Car number (optional)', placeholder='Exact car number', disabled=scope == 'Every driver')
    category = 'Super Comp'
    st.caption('Class: **Super Comp** · 8.90 index (fixed)')
    year = int(st.number_input('Season', min_value=2023, max_value=2035, value=date.today().year))
    st.caption('Search by name alone if a car-number format could differ. If both are entered, both must match.')
    st.divider()
    st.header('Season search scope')
    season_scope = st.radio('Include events from', ['Both', 'Nationals only', 'Divisionals only'], index=0, help='Controls which events the full-season search scans and which results appear in the driver profile.')
    season_division = st.selectbox('Search which divisions?', ['All divisions'] + [f'Division {d}' for d in range(1, 8)], index=0, disabled=season_scope == 'Nationals only', help='Filters divisional event discovery and the displayed driver profile. Nationals are never filtered by division.')
    st.divider()
    st.header('Single-event tools')
    kind = st.radio('Event series', ['National', 'Divisional'], horizontal=True)
    division = st.selectbox('Division', ['All divisions'] + [f'Division {d}' for d in range(1, 8)], index=7) if kind == 'Divisional' else None
    auto = st.toggle('Auto-check selected event every 60 seconds', value=False)

@st.cache_data(ttl=300, show_spinner=False)
def directory(yr, series, div=None):
    selected_divisions = [int(div.split()[-1])] if series == 'Divisional' and div and div != 'All divisions' else None
    return discover(yr, series, selected_divisions)[0]

def sorted_events(events):
    def sort_key(e):
        part = e['url'].rstrip('/').split('/')[-1]
        return int(part) if part.isdecimal() else 0
    return sorted(events, key=sort_key, reverse=True)

conn = connect()
st.session_state.setdefault('season_report', None)
st.session_state.setdefault('last_check', None)
valid_driver = bool(driver.strip() or number.strip())

# Season scan and season display follow the explicit season scope; single-event settings are independent.
season_series = (['National', 'Divisional'] if season_scope == 'Both'
                 else ['National'] if season_scope == 'Nationals only' else ['Divisional'])
season_division_number = None if season_division == 'All divisions' else int(season_division.split()[-1])
scope_key = (season_scope, season_division if 'Divisional' in season_series else '—')
if scope == 'One driver':
    st.subheader('Full-season driver profile')
    st.write('Search **only the series and divisions selected in Season search scope** on the left. The resulting profile includes only events where this driver has a matching elimination pass. Averages use individual passes, not event averages.')
    st.caption('Selected scope: ' + (season_scope if season_scope != 'Both' else 'Nationals + divisionals') + (f' · {season_division}' if 'Divisional' in season_series else ''))
    st.caption('A full-season search can take a while because it opens each event’s round selector in Microsoft Edge. Keep this tab running until the scan completes. Refresh runs later to check newly posted results.')
    if not valid_driver:
        st.warning('Enter a driver name or car number on the left.')

    col1, col2 = st.columns([1, 1])
    full_search = col1.button(f'🔎 Search {year} selected events', type='primary', use_container_width=True, disabled=not valid_driver)
    recent_search = col2.button('🔄 Refresh latest selected events', use_container_width=True, disabled=not valid_driver)

    if full_search or recent_search:
        event_lists, directory_errors = [], []
        for series in season_series:
            try:
                event_lists.extend(directory(year, series, season_division if series == 'Divisional' else None))
            except Exception as ex:
                directory_errors.append(f'{series} directory could not be loaded: {ex}')
        unique = {e['url']: e for e in event_lists}
        all_events = sorted_events(list(unique.values()))
        if recent_search:
            # Latest five events per selected series; division filter already applied.
            all_events = sorted_events([e for k in season_series for e in sorted_events([x for x in unique.values() if x['kind'] == k])[:5]])
        summary = {'year': year, 'class': category, 'name': driver.strip(), 'number': number.strip(),
                   'listed': len(all_events), 'checked': 0, 'errors': directory_errors.copy(), 'hits': 0,
                   'matched_events': set(), 'new': 0, 'incomplete_rounds': [], 'by_series': {'National': 0, 'Divisional': 0},
                   'finished': False, 'scope_key': scope_key}
        if not all_events:
            st.error('No event listings found. ' + ' '.join(directory_errors))
        else:
            bar = st.progress(0, text='Starting season search')
            status = st.empty()
            # Reuse one hidden Edge instance across a season scan to avoid
            # repeatedly starting a browser for every race.
            from playwright.sync_api import sync_playwright
            browser_runner = sync_playwright()
            pw = browser_runner.start()
            shared_browser = None
            try:
                shared_browser = pw.chromium.launch(channel='msedge', headless=True, args=['--disable-extensions'])
                for i, event in enumerate(all_events):
                    status.write(f'Checking {i + 1}/{len(all_events)}: {event["kind"]} · {event["name"]}')
                    try:
                        runs, detail = fetch_all_elimination_rounds(event, CATEGORIES[category], category, shared_browser=shared_browser)
                        matching = [r for r in runs if matching_row(r, driver, number)]
                        summary['hits'] += len(matching)
                        summary['new'] += save_rows(conn, matching)
                        if matching:
                            summary['matched_events'].add(event['url'])
                            summary['by_series'][event['kind']] += len(matching)
                        if detail.get('warnings'):
                            summary['incomplete_rounds'].append(event['name'])
                    except Exception as ex:
                        summary['errors'].append(f'{event["kind"]} · {event["name"]}: {str(ex)[:150]}')
                    summary['checked'] += 1
                    bar.progress((i + 1) / len(all_events), text=f'{i + 1} of {len(all_events)} listed events checked')
                    if i < len(all_events) - 1: time.sleep(0.05)
            finally:
                if shared_browser is not None:
                    shared_browser.close()
                browser_runner.stop()
            summary['finished'] = True
            st.session_state.season_report = summary
            bar.empty()
            status.empty()

    report = st.session_state.season_report
    if report and (report['year'], report['class'], report['name'], report['number'], report.get('scope_key')) == (year, category, driver.strip(), number.strip(), scope_key):
        st.success(f"Last scan: checked {report['checked']}/{report['listed']} listed events · matched {len(report['matched_events'])} events · {report['hits']} time slips seen · {report['new']} newly saved")
        st.caption(f"National matches: {report['by_series']['National']} runs · Divisional matches: {report['by_series']['Divisional']} runs")
        if report['hits'] == 0:
            st.info('No Super Comp results matched. If round-selection verification failed, this may be a collection problem, not a lack of race entries.')
        if report['errors']:
            st.warning(f"{len(report['errors'])} directories/event pages failed. Season totals may be incomplete.")
            with st.expander('See unavailable pages'):
                for x in report['errors']: st.write(x)
        if report['incomplete_rounds']:
            st.warning(f"Round-selection verification failed on {len(report['incomplete_rounds'])} events. Those event results may only cover a subset of rounds.")
            with st.expander('See events with unverified rounds'):
                st.write(', '.join(report['incomplete_rounds']))

st.divider()
st.subheader('Check one event')
try:
    events = sorted_events(directory(year, kind, division))
except Exception as ex:
    events = []
    st.warning(f'Event directory unavailable: {ex}')

selected = None
if events:
    selected = events[st.selectbox('Event to refresh', list(range(len(events))), format_func=lambda i: events[i]['name'] + (f" · Division {events[i]['division']}" if events[i]['division'] else ''))]
    st.markdown(f"[NHRA Live Timing]({selected['url']}/live-timing) · [NHRA Detailed Results]({selected['url']}/detailed-results/{CATEGORIES[category]})")

def scan_one(event):
    try:
        rows, details = fetch_all_elimination_rounds(event, CATEGORIES[category], category)
        matched = rows if scope == 'Every driver' else [r for r in rows if matching_row(r, driver, number)]
        new = save_rows(conn, matched)
        return {'text': f"{event['name']}: {len(rows)} published elimination time slips · {len(matched)} matched · {new} new saved", 'warnings': details.get('warnings', []), 'error': False}
    except Exception as ex:
        return {'text': f"Could not fetch {event['name']}: {ex}", 'error': True, 'warnings': []}

single = st.button('🔄 Refresh selected event', disabled=selected is None or (scope == 'One driver' and not valid_driver))
if single and selected:
    st.session_state.last_check = scan_one(selected)
if st.session_state.last_check:
    res = st.session_state.last_check
    (st.error if res['error'] else st.success)(res['text'])
    for warning in res.get('warnings', []): st.warning(warning)

@st.fragment(run_every='60s')
def current_panel():
    if auto and selected and (scope == 'Every driver' or valid_driver):
        res = scan_one(selected)
        st.caption('Automatic selected-event check: ' + res['text'])
    df = read_rows(conn)
    if df.empty:
        st.info('No saved elimination passes yet. Run the full-season search above.')
        return
    for field in ('kind','division','category','event_url','winner','car_number','round','driver','record_id'):
        if field not in df: df[field] = None
    # Guard against runs from previous seasons stored in the same database.
    df = df[df['event_url'].astype(str).str.contains(r'/results/' + str(year) + r'/', regex=True, na=False)]
    df = df[df['category'] == category]
    # Reject stale records from unrelated events saved by older versions.
    try:
        eligible_urls = set()
        for eligible_series in ('National', 'Divisional'):
            try:
                eligible_urls.update(e['url'] for e in directory(year, eligible_series))
            except Exception:
                pass
        if eligible_urls:
            df = df[df['event_url'].isin(eligible_urls)]
        else:
            st.warning('Could not verify current NHRA event directories. Previously saved data has not been schedule-verified.')
    except Exception:
        pass
    if scope == 'One driver':
        if not valid_driver:
            st.info('Enter a driver name or car number to see their season profile.')
            return
        mask = df.apply(lambda row: matching_row(row.to_dict(), driver, number), axis=1)
        df = df[mask]
        # Season-wide profile reflects the same selected scope as the discovery/search.
        df = df[df['kind'].isin(season_series)]
        if 'Divisional' in season_series and season_division_number is not None:
            df = df[(df['kind'] != 'Divisional') | (pd.to_numeric(df['division'], errors='coerce') == season_division_number)]
    # Every-driver mode is single-series and optionally division-scoped.
    else:
        df = df[df['kind'] == kind]
        if kind == 'Divisional' and division != 'All divisions':
            df = df[pd.to_numeric(df['division'], errors='coerce') == int(division.split()[-1])]
    if df.empty:
        st.info('No saved elimination passes for this driver and class in the selected season. Try the full-season search. No result does not prove the racer did not attend.')
        return
    df = enrich(df, category)
    df['winner'] = df['winner'].fillna(False).astype(bool)
    if 'observed_at' in df: df = df.sort_values('observed_at', ascending=False)
    cols = ['rt','ft60','ft330','ft660','mph660','ft1000','et','mph','et_over_under']
    def summary_table(frame):
        if frame.empty: return pd.DataFrame()
        agg = {'Elimination passes': len(frame), 'Events found': frame['event_url'].nunique(), 'Wins': int(frame['winner'].sum()),
               'Win %': round(100 * frame['winner'].sum() / len(frame), 1),
               'Fastest MPH': speed_summary(frame)['fastest_mph'],
               'Slowest MPH': speed_summary(frame)['slowest_mph']}
        for col in cols:
            agg['Avg ' + col] = round(pd.to_numeric(frame[col], errors='coerce').mean(), 4) if pd.to_numeric(frame[col], errors='coerce').notna().any() else None
        agg['Indexed passes'] = int(pd.to_numeric(frame['et_over_under'], errors='coerce').count())
        return pd.DataFrame([agg])
    if scope == 'One driver':
        st.header(f'{year} driver elimination profile')
        st.caption('Showing only ' + (season_scope if season_scope != 'Both' else 'nationals and divisionals') + (f' · {season_division}' if 'Divisional' in season_series else '') + '. Averages use all saved individual passes within this filter (including previously scanned events).')
        a, b, c = st.columns(3)
        a.metric('Total elimination passes', len(df))
        b.metric('National events attended (found)', df[df['kind']=='National']['event_url'].nunique())
        c.metric('Divisional events attended (found)', df[df['kind']=='Divisional']['event_url'].nunique())
        st.subheader('Season total · selected scope')
        st.dataframe(summary_table(df), hide_index=True, use_container_width=True)
        st.subheader('National-event average')
        national = df[df['kind'] == 'National']
        if national.empty: st.caption('No matching national-event time slips found.')
        else: st.dataframe(summary_table(national), hide_index=True, use_container_width=True)
        st.subheader('Divisional-event average · ' + (season_division if season_division != 'All divisions' else 'Divisions 1–7 combined'))
        divisional = df[df['kind'] == 'Divisional']
        if divisional.empty: st.caption('No matching divisional-event time slips found.')
        else:
            st.dataframe(summary_table(divisional), hide_index=True, use_container_width=True)
            with st.expander('Divisional averages by division'):
                for d in range(1,8):
                    part = divisional[pd.to_numeric(divisional['division'], errors='coerce') == d]
                    if not part.empty:
                        st.markdown(f'**Division {d}**')
                        st.dataframe(summary_table(part), hide_index=True, use_container_width=True)
        st.subheader('Speed highlights and unusually slow passes')
        st.caption('Fastest MPH is the highest recorded quarter-mile trap speed, not the average. Low-MPH outliers are compared to your own season median and require at least five measured speeds.')
        for label, sample in [('Overall season', df), ('Nationals', national), ('Divisionals', divisional)]:
            if sample.empty:
                continue
            speed = speed_summary(sample)
            st.markdown('**' + label + '**')
            left, mid, right = st.columns(3)
            left.metric('Fastest MPH', f"{speed['fastest_mph']:.2f}" if speed['fastest_mph'] is not None else '—')
            mid.metric('Median MPH', f"{speed['median_mph']:.2f}" if speed['median_mph'] is not None else '—')
            slow, rule = slow_mph_outliers(sample)
            right.metric('Slow MPH outliers', str(len(slow)) if rule else 'N/A')
            if speed['fastest_mph'] is not None:
                fastest = sample[pd.to_numeric(sample['mph'], errors='coerce') == speed['fastest_mph']]
                st.caption('Fastest pass: ' + ' · '.join(str(x) for x in [fastest.iloc[0]['event'], fastest.iloc[0]['round'], f"{speed['fastest_mph']:.2f} MPH"]))
            if rule is None:
                st.caption('Need at least 5 passes with recorded MPH to flag slow outliers for this grouping.')
            elif slow.empty:
                st.caption(f"No passes at least {rule['threshold']:.2f} MPH below the {rule['median']:.2f} MPH median.")
            else:
                st.caption(f"Flagged if at least {rule['threshold']:.2f} MPH below this group's {rule['median']:.2f} MPH median. May reflect lifting, a problem, or other race circumstances; not automatically a mechanical issue.")
                shown = ['event','round','mph','Below median (MPH)','et','rt','et_over_under','source_url']
                st.dataframe(slow[[c for c in shown if c in slow]], hide_index=True, use_container_width=True,
                             column_config={'source_url': st.column_config.LinkColumn('NHRA result')})
        st.subheader('Only matching events within your selected season scope')
        # Each event appears once; attendance is inferred ONLY from matching time slips.
        grouped = df.groupby(['kind','event_url'], dropna=False)
        records = []
        for (series, event_url), group in grouped:
            records.append({'Series': series, 'Division': ('Division ' + str(int(group['division'].dropna().iloc[0]))) if series == 'Divisional' and not group['division'].dropna().empty else '—',
                            'Event': group['event'].iloc[0], 'Passes': len(group),
                            'Wins': int(group['winner'].sum()), 'Avg RT': round(group['rt'].mean(), 4),
                            'Avg ET': round(group['et'].mean(), 4), 'Fastest MPH': pd.to_numeric(group['mph'], errors='coerce').max(), 'Avg ET over/under': round(group['et_over_under'].mean(), 4),
                            'Source': event_url})
        attended = pd.DataFrame(records).sort_values(['Series','Event'])
        for series in ('National','Divisional'):
            group = attended[attended['Series']==series]
            if not group.empty:
                st.markdown('**' + series + ' events**')
                st.dataframe(group, hide_index=True, use_container_width=True,
                             column_config={'Source': st.column_config.LinkColumn('NHRA event page')})
        st.download_button('Download season event breakdown (CSV)', attended.to_csv(index=False), file_name=f'nhra_{year}_{category.lower().replace(" ","_")}_events.csv', mime='text/csv')
    else:
        st.header('Every-driver averages (saved results)')
        st.dataframe(driver_averages(df), hide_index=True, use_container_width=True)
    if category in FIXED_INDEX:
        st.caption(f'{category}: standard {FIXED_INDEX[category]:.2f}-second index, unless NHRA posts a different run-specific value. Negative ET over/under means quicker than the index.')
    elif category in VARIABLE:
        st.caption('ET over/under compares ET to the NHRA posted run-specific dial-in/index when available. Missing indexes are not guessed.')
    st.subheader('All collected elimination time slips')
    fields = ['kind','division','event','round','driver','car_number','winner','dial_in','reference_et','et_over_under','rt','ft60','ft330','ft660','mph660','ft1000','et','mph','source_url']
    view = df[[c for c in fields if c in df]].copy()
    st.dataframe(view, hide_index=True, use_container_width=True)
    st.download_button('Download elimination passes (CSV)', view.to_csv(index=False), file_name=f'nhra_{year}_elimination_passes.csv', mime='text/csv')
    st.caption('Only observed time slips are counted; missing events/pages/rounds can affect averages. No matching run is not proof of non-attendance.')

current_panel()
