"""Independent final ASCII boundary flux/temperature audit for the demo."""
import argparse
import hashlib
import json
import re
from pathlib import Path


def values(entry):
    uniform = re.search(r'\buniform\s+([^;]+);',entry)
    if uniform:
        s=uniform.group(1).strip()
        return [tuple(map(float,s.strip('()').split())) if s.startswith('(') else float(s)]
    m=re.search(r'nonuniform\s+List<(scalar|vector)>\s+(\d+)\s*\((.*?)\)\s*;',entry,re.S)
    if not m:raise ValueError('Unsupported ASCII field entry')
    vals=([tuple(map(float,x.split())) for x in re.findall(r'\(([^()]+)\)',m.group(3))]
          if m.group(1)=='vector' else list(map(float,m.group(3).split())))
    assert len(vals)==int(m.group(2))
    return vals


def patch(case,time,region,name,patch):
    mesh=case/'constant'/region/'polyMesh'
    b=re.search(r'\b'+patch+r'\s*\{([^{}]+)\}',(mesh/'boundary').read_text()).group(1)
    n=int(re.search(r'nFaces\s+(\d+)',b).group(1));start=int(re.search(r'startFace\s+(\d+)',b).group(1))
    text=(case/time/region/name).read_text()
    b=re.search(r'\b'+patch+r'\s*\{([^{}]+)\}',text).group(1)
    if re.search(r'\bvalue\s',b):vs=values(re.split(r'\bvalue\s+',b,maxsplit=1)[1])
    elif 'zeroGradient' in b:
        v=values(text.split('internalField',1)[1].split('boundaryField',1)[0])
        owners=(mesh/'owner').read_text(); owners=owners[owners.index('}')+1:]
        owners=list(map(int,owners[owners.index('(')+1:owners.rindex(')')].split()))
        vs=[v[0] if len(v)==1 else v[owners[i]] for i in range(start,start+n)]
    else:raise ValueError('Cannot recover patch '+patch+' field '+name)
    if len(vs)==1:vs*=n
    assert len(vs)==n
    return vs


def audit(case):
    time=max((p.name for p in case.iterdir() if p.is_dir() and re.fullmatch(r'\d+(?:\.\d+)?',p.name)),key=float)
    out={'case':str(case),'time':time,'ports':{}}
    cp=json.loads((case/'baseline-settings.json').read_text())['cp_J_kg_K']
    for port in ('inlet','outlet'):
        fs=patch(case,time,'fluid','phi',port); ts=patch(case,time,'fluid','T',port);us=patch(case,time,'fluid','U',port)
        out['ports'][port]={'mass_kg_s':sum(fs),'sensible_flux_W':sum(f*cp*(t-300) for f,t in zip(fs,ts)),
                            'kinetic_flux_W':sum(f*sum(v*v for v in u)/2 for f,u in zip(fs,us))}
    out['advected_energy_W']=sum(p['sensible_flux_W']+p['kinetic_flux_W'] for p in out['ports'].values())
    out['heated_max_K']=max(patch(case,time,'solid','T','heated'))
    out['wetted_max_K']=max(patch(case,time,'fluid','T','fluid_to_solid'))
    ps=values((case/time/'fluid/p').read_text().split('internalField',1)[1].split('boundaryField',1)[0])
    for port in ('inlet','outlet','fluid_to_solid'):ps+=patch(case,time,'fluid','p',port)
    out['pmin_absolute_Pa']=min(ps)
    paths=[case/time/'fluid'/n for n in ('T','U','phi','p')]+[case/time/'solid/T',case/'baseline-settings.json',case/'constant/fluid/polyMesh/owner']
    out['input_sha256']={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    return out


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('case',type=Path);p.add_argument('--output',type=Path)
    a=p.parse_args();s=json.dumps(audit(a.case),indent=2)+'\n'
    if a.output:a.output.write_text(s)
    print(s)
