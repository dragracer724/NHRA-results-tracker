"""Elimination-only driver statistics. Values are seconds; missing indexes stay missing."""
import pandas as pd

FIXED_INDEX = {'Super Comp': 8.90, 'Super Gas': 9.90, 'Super Street': 10.90}
VARIABLE = {'Competition Eliminator', 'Stock Eliminator', 'Super Stock', 'Top Dragster', 'Top Sportsman', 'Sportsman Motorcycle'}

def enrich(df: pd.DataFrame, category: str) -> pd.DataFrame:
    out = df.copy()
    if out.empty:
        return out
    out['et'] = pd.to_numeric(out.get('et'), errors='coerce')
    out['dial_in'] = pd.to_numeric(out.get('dial_in'), errors='coerce')
    if category in FIXED_INDEX:
        # The displayed dial-in can incorporate track-specific corrections.
        # Prefer NHRA's posted value, and only use the standard when absent.
        out['reference_et'] = out['dial_in'].fillna(FIXED_INDEX[category])
        out['reference_type'] = 'NHRA posted index / standard'
    elif category in VARIABLE:
        out['reference_et'] = out['dial_in']
        out['reference_type'] = 'NHRA posted dial-in or personal/class index'
    else:
        out['reference_et'] = pd.Series(float('nan'), index=out.index)
        out['reference_type'] = 'Not an index/dial-in class'
    out['et_over_under'] = (out['et'] - out['reference_et']).round(3)
    for key in ('rt', 'ft60', 'ft330', 'ft660', 'mph660', 'ft1000', 'mph'):
        if key in out:
            out[key] = pd.to_numeric(out[key], errors='coerce')
    return out

def driver_averages(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    grouped = df.groupby(['driver', 'car_number'], dropna=False)
    result = grouped.agg(
        passes=('record_id', 'count'), wins=('winner', 'sum'),
        avg_rt=('rt', 'mean'), avg_60ft=('ft60', 'mean'),
        avg_330ft=('ft330', 'mean'), avg_660ft=('ft660', 'mean'),
        avg_1000ft=('ft1000', 'mean'), avg_et=('et', 'mean'),
        avg_mph=('mph', 'mean'), fastest_mph=('mph', 'max'), avg_over_under=('et_over_under', 'mean'),
        indexed_passes=('et_over_under', 'count'),
        events=('event_url', 'nunique')
    ).reset_index()
    result['win_pct'] = (result['wins'] / result['passes'] * 100).round(1)
    for col in result.columns:
        if col.startswith('avg_'):
            result[col] = result[col].round(4)
    return result.sort_values(['passes', 'driver'], ascending=[False, True])
