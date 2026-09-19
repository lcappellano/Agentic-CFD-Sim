"""Check raw solver/monitor convergence against a predeclared criteria file."""
import argparse
import json
import math
from pathlib import Path
import re

from src.foam.hashing import digest


def monitor(case, name, hashes):
    rows = {}
    for path in sorted((case / 'postProcessing').glob('*/' + name + '/*/surfaceFieldValue.dat')):
        hashes[str(path)] = digest(path)
        for line in path.read_text().splitlines():
            if line.strip() and not line.lstrip().startswith('#'):
                values = list(map(float, line.translate(str.maketrans({'(':' ', ')':' '})).split()))
                rows[values[0]] = values[1:]
    return rows


def review(case, audit_path, criteria_path):
    case = Path(case).resolve()
    audit = json.loads(audit_path.read_text())
    criteria = json.loads(criteria_path.read_text())
    hashes = {str(p):digest(p) for p in (audit_path, criteria_path, Path(__file__))}
    settings_path = case / 'settings.json'
    settings = json.loads(settings_path.read_text())
    hashes[str(settings_path)] = digest(settings_path)
    model = settings.get('turbulence_model', 'kEpsilon')
    checks = []
    def add(name, ok, evidence):
        checks.append({'check':name, 'status':'not checked' if ok is None else 'pass' if ok else 'fail', 'evidence':evidence})
    final = float(audit['time'])
    start = final - criteria['final_window_iterations']
    names = ['heatedMax','wettedMax','inletPressure','outletPressure','inletMass','outletMass',
             'heatedPower','interfacePower','fluidPower']
    histories = {name:monitor(case,name,hashes) for name in names}
    windows = {name:{time:values[0] for time,values in rows.items() if start<=time<=final}
               for name,rows in histories.items()}
    for name, window in windows.items():
        add('monitor_times:' + name, bool(window) and max(window)==final and max(window)-min(window)>=criteria['final_window_iterations'],
            {'first':min(window) if window else None,'last':max(window) if window else None,'samples':len(window)})
    for name in ('heatedMax','wettedMax'):
        window = windows[name]
        variation = max(window.values())-min(window.values()) if len(window)>1 else None
        add('temperature_stability:' + name, variation<=criteria['temperature_range_K'] if variation is not None else None,
            {'range_K':variation,'required_K':criteria['temperature_range_K']})
    common = sorted(set(windows['inletPressure']) & set(windows['outletPressure']))
    dp = [windows['inletPressure'][t]-windows['outletPressure'][t] for t in common]
    variation = (max(dp)-min(dp))/abs(dp[-1]) if len(dp)>1 and dp[-1] else None
    add('pressure_drop_stability', variation<=criteria['pressure_drop_range_relative'] if variation is not None else None,
        {'range_fraction':variation,'required_fraction':criteria['pressure_drop_range_relative']})
    comparisons = [('heatedMax', audit['heated']['maximum_K']),('wettedMax',audit['wetted_maximum_K']),
                   ('inletMass',audit['ports']['inlet']['signed_outward_mass_kg_s']),
                   ('outletMass',audit['ports']['outlet']['signed_outward_mass_kg_s'])]
    for name,value in comparisons:
        measured = windows[name].get(final)
        add('raw_field_vs_monitor:' + name, abs(measured-value)<=max(1e-6,abs(value)*1e-8) if measured is not None else None,
            {'raw_field':value,'monitor':measured})
    residuals, iteration, region = {}, None, None
    for log in sorted(case.glob('log.solver*')):
        hashes[str(log)] = digest(log)
        iteration, region = None, None
        for line in log.read_text().splitlines():
            if line.startswith('Time = '):
                iteration = float(line.split('=')[1])
            if line.startswith('Solving for '):
                region = line.split()[-1]
            found = re.search(r'Solving for (\w+), Initial residual = ([^,]+), Final residual = ([^,]+)', line)
            if found and iteration is not None and start<=iteration<=final:
                key = str(region)+':'+found.group(1)
                residuals.setdefault(key,[]).append((float(found.group(2)),float(found.group(3)),iteration))
    required = {'fluid:Ux', 'fluid:Uy', 'fluid:Uz', 'fluid:p_rgh', 'fluid:h', 'solid:h'}
    if model == 'kEpsilon':
        required |= {'fluid:k', 'fluid:epsilon'}
    elif model == 'kOmegaSST_spalding':
        required |= {'fluid:k', 'fluid:omega'}
    add('residual_equations_present', required<=set(residuals), {'required':sorted(required),'present':sorted(residuals)})
    maxima = {key:{'initial':max(v[0] for v in rows),'linear_final':max(v[1] for v in rows),'count':len(rows)}
              for key,rows in residuals.items()}
    for key in sorted(required):
        value = maxima.get(key)
        rows = residuals.get(key, [])
        times = sorted({row[2] for row in rows})
        finite = bool(rows) and all(math.isfinite(v) for row in rows for v in row)
        add('residual_window:' + key, finite and bool(times) and times[0] <= start+1
            and times[-1] == final and all(b-a <= 1 for a,b in zip(times,times[1:])),
            {'finite':finite,'first':times[0] if times else None,'last':times[-1] if times else None,
             'distinct_iterations':len(times)})
        add('residual:' + key, value['initial']<=criteria['initial_residual_max']
            and value['linear_final']<=criteria['linear_final_residual_max'] if value is not None else None,
            value)
    return {'case':str(case),'time':final,'scope':'independent convergence history review',
            'checks':checks,'final_window_residual_maxima':maxima,
            'convergence_checks_pass':all(x['status']=='pass' for x in checks),
            'input_sha256':hashes}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case',type=Path)
    parser.add_argument('--audit',type=Path,required=True)
    parser.add_argument('--criteria',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    result = review(args.case,args.audit,args.criteria)
    with args.output.open('x') as stream:
        json.dump(result,stream,indent=2,allow_nan=False)
        stream.write('\n')
    print(json.dumps({'convergence_checks_pass':result['convergence_checks_pass'],
                      'checks':result['checks']},indent=2))
