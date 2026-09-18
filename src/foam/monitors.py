"""Readers for function-object output under postProcessing/."""
from pathlib import Path


def _rows(paths):
    rows = {}
    for path in paths:
        for line in path.read_text().splitlines():
            if line.strip() and not line.lstrip().startswith('#'):
                numbers = [float(v) for v in line.replace('(', ' ').replace(')', ' ').split()]
                rows[numbers[0]] = numbers[1:]
    return [(time, values) for time, values in sorted(rows.items())]


def monitor_rows(case, name):
    """(time, [values]) rows of a surfaceFieldValue monitor across restarts."""
    paths = sorted(Path(case).glob('postProcessing/*/' + name + '/*/surfaceFieldValue.dat'),
                   key=lambda p: float(p.parent.name))
    return _rows(paths)


def monitor_last(case, name):
    rows = monitor_rows(case, name)
    return rows[-1] if rows else None


def window_range(rows, latest, window):
    """Max minus min of the first column over the closing iteration window."""
    values = [row[0] for time, row in rows if time >= latest - window]
    return max(values) - min(values) if values else None


def full_window(rows, latest, window, max_gap=10):
    """True when samples cover [latest-window, latest] without large gaps."""
    times = sorted({time for time, _ in rows if latest - window <= time <= latest})
    return (bool(times) and times[0] <= latest - window and times[-1] == latest and len(times) > 1
            and max(b - a for a, b in zip(times, times[1:])) <= max_gap)


def field_min_max(case, region, field):
    """Latest fieldMinMax record for one field: (time, min, min_location, max, max_location)."""
    records = []
    for path in Path(case).glob(f'postProcessing/{region}/*/*/fieldMinMax.dat'):
        for line in path.read_text().splitlines():
            tokens = line.replace('(', ' ').replace(')', ' ').split()
            if tokens and not tokens[0].startswith('#') and len(tokens) > 1 and tokens[1] == field:
                numbers = [float(v) for v in tokens[2:]]
                records.append((float(tokens[0]), numbers[0], numbers[1:4], numbers[4], numbers[5:8]))
    return max(records, key=lambda r: r[0]) if records else None
