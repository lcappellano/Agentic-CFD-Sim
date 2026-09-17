"""Independent ASCII polyMesh boundary-area/orientation audit, fixed demo only."""
import argparse
import hashlib
import json
import math
import re
from pathlib import Path


def body(path):
    text = path.read_text()
    text = re.sub(r'/\*.*?\*/|//[^\n]*', '', text, flags=re.S)
    text = re.sub(r'FoamFile\s*\{.*?\}', '', text, flags=re.S)
    match = re.search(r'\b(\d+)\s*\(', text)
    if not match:
        raise ValueError(f'No ASCII list: {path}')
    return int(match.group(1)), text[match.end():]


def audit(case):
    results = {}
    hashes = {}
    for region in ('fluid', 'solid'):
        mesh = case / 'constant' / region / 'polyMesh'
        np, points = body(mesh / 'points')
        pts = [tuple(map(float, p.split())) for p in re.findall(r'\(([^()]*)\)', points)]
        nf, faces = body(mesh / 'faces')
        fs = [list(map(int, f.split())) for f in re.findall(r'\d+\(([^()]*)\)', faces)]
        assert len(pts) == np and len(fs) == nf
        text = (mesh / 'boundary').read_text()
        patches = {}
        for name, content in re.findall(r'(\w+)\s*\{([^{}]*)\}', text):
            count = re.search(r'\bnFaces\s+(\d+)', content)
            start = re.search(r'\bstartFace\s+(\d+)', content)
            if not count or not start:
                continue
            areas = []
            vectors = []
            for face in fs[int(start.group(1)):int(start.group(1))+int(count.group(1))]:
                vector = [0., 0., 0.]
                origin = pts[face[0]]
                for a, b in zip(face[1:-1], face[2:]):
                    u = [pts[a][j]-origin[j] for j in range(3)]
                    v = [pts[b][j]-origin[j] for j in range(3)]
                    for j in range(3):
                        vector[j] += .5*(u[(j+1)%3]*v[(j+2)%3]-u[(j+2)%3]*v[(j+1)%3])
                vectors.append(vector)
                areas.append(math.sqrt(sum(x*x for x in vector)))
            patches[name] = dict(faces=len(areas), area_m2=sum(areas),
                                 oriented_area_m2=[sum(v[j] for v in vectors) for j in range(3)])
        results[region] = patches
        for name in ('points', 'faces', 'boundary'):
            p = mesh/name
            hashes[str(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
    f, s = results['fluid'], results['solid']
    checks = {
        'inlet_outward_minus_x': f['inlet']['oriented_area_m2'][0] < 0,
        'outlet_outward_plus_x': f['outlet']['oriented_area_m2'][0] > 0,
        'heated_area_matches_approved': abs(s['heated']['area_m2']/.0024-1)<1e-8,
        'paired_interface_area_matches': abs(f['fluid_to_solid']['area_m2']/s['solid_to_fluid']['area_m2']-1)<1e-8,
    }
    return dict(case=str(case), patches=results, checks={k:'pass' if v else 'fail' for k,v in checks.items()},
                applied_heat_W=s['heated']['area_m2']*100000, input_sha256=hashes)


if __name__ == '__main__':
    p=argparse.ArgumentParser();p.add_argument('case',type=Path);p.add_argument('--output',type=Path)
    a=p.parse_args(); result=audit(a.case); rendered=json.dumps(result,indent=2)+'\n'
    if a.output:a.output.write_text(rendered)
    print(rendered)
