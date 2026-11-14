"""Speed highlights and conservative, per-driver low-MPH anomaly checks."""
import pandas as pd


def speed_summary(frame):
    speeds = pd.to_numeric(frame['mph'], errors='coerce').dropna()
    if speeds.empty:
        return {'fastest_mph': None, 'slowest_mph': None, 'median_mph': None, 'speed_passes': 0}
    return {'fastest_mph': float(speeds.max()), 'slowest_mph': float(speeds.min()),
            'median_mph': float(speeds.median()), 'speed_passes': int(speeds.size)}


def slow_mph_outliers(frame, min_passes=5, min_drop_mph=5.0, drop_fraction=0.05):
    """Flag passes >= max(5 mph, 5% of baseline) below driver's median speed.

    Uses ONLY the supplied frame, so caller can compare nationals/divisionals
    separately. At least five valid speed passes are required; absence of
    outliers with less data is not evidence of normal performance.
    """
    speeds = pd.to_numeric(frame['mph'], errors='coerce')
    good = speeds.dropna()
    if len(good) < min_passes:
        return frame.iloc[0:0].copy(), None
    baseline = float(good.median())
    threshold = max(min_drop_mph, baseline * drop_fraction)
    result = frame.loc[speeds <= baseline - threshold].copy()
    result['mph'] = speeds.loc[result.index]
    result['Below median (MPH)'] = (baseline - result['mph']).round(2)
    return result.sort_values('mph'), {'median': baseline, 'threshold': threshold, 'n': len(good)}
