"""Solver log parsing: residual histories across original and resumed logs."""
import math
from pathlib import Path
import re

RESIDUAL = re.compile(r'Solving for (\w+), Initial residual = ([^,]+), Final residual = ([^,]+)')


def residual_history(case, latest=None, window=None):
    """Residual samples keyed by ``region:equation`` over the closing window."""
    samples = {}
    for path in sorted(Path(case).glob('log.solver*')):
        time, region = None, None
        with path.open(errors='replace') as stream:
            for line in stream:
                if line.startswith('Time = '):
                    time = float(line.split('=')[1])
                elif line.startswith('Solving for '):
                    region = line.split()[-1]
                else:
                    found = RESIDUAL.search(line)
                    if found and time is not None and (latest is None or latest - window <= time <= latest):
                        samples.setdefault(f'{region}:{found.group(1)}', []).append(
                            (time, float(found.group(2)), float(found.group(3))))
    return samples


def residual_maxima(case, latest, window):
    """Per-equation maxima and window completeness over the closing window."""
    result = {}
    for key, rows in residual_history(case, latest, window).items():
        times = sorted({row[0] for row in rows})
        finite = all(math.isfinite(row[1]) and math.isfinite(row[2]) for row in rows)
        result[key] = {
            'initial': max(row[1] for row in rows) if finite else math.inf,
            'linear_final': max(row[2] for row in rows) if finite else math.inf,
            'finite': finite,
            'first_iteration': times[0], 'last_iteration': times[-1],
            'unique_iterations': len(times),
            'window_complete': (times[0] <= latest - window and times[-1] == latest and len(times) > 1
                                and max(b - a for a, b in zip(times, times[1:])) <= 1),
        }
    return result
