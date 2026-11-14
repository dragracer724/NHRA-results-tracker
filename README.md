# NHRA Super Comp-only Elimination Season Tracker

## What's different
- **Super Comp only**, with the 8.90-second ET over/under index.
- National events or genuine Lucas Oil Division 1–7 events; the NHRA live timing directory's **OTHER EVENTS** category (Hot Rod Reunion, Jr. finals, ET finals, national opens, etc.) is excluded.
- Season-long driver averages using published elimination time slips from all successfully retrieved rounds.
- Fastest 1/4-mile MPH, median MPH, and low-speed outliers.
- Finds only events with matching recorded elimination passes; no match is not proof of non-attendance.
- Reuses one headless Microsoft Edge browser across season scans to reduce startup overhead. Selecting a single event uses the standard browser setup.

## Windows 10 installation
1. Extract the ZIP; open the `nhra_eliminations_tracker` folder.
2. Click File Explorer's address bar, type `cmd`, and press Enter.
3. Run `py -3.13 -m pip install -r requirements.txt`.
4. Run `py -3.13 -m streamlit run app.py`.
5. Choose One driver, enter name or car number, choose Season search scope and division, then use **Search selected events**.

## Limitations
The app uses **public NHRA Detailed Results pages**, not a confirmed direct live timing API. The NHRA Round dropdown is dynamically rendered and may fail to automate; the dashboard flags unverified round selection rather than claiming complete season data. Not every division/event necessarily runs Super Comp, and missing matches can be a collection failure. No real-time feed guarantee. Some older season directory pages may use a different layout.

Existing databases are not copied into the new extracted folder; older databases should not be reused unless you know their recorded events came from genuine Super Comp Lucas Oil divisional/national races.
