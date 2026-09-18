"""Check and solve an already built OpenCFD2412 fixed-demo case; invoke via workbench job."""
import argparse,json,subprocess,hashlib
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('case',type=Path);p.add_argument('--ranks',type=int,default=1);a=p.parse_args();case=a.case.resolve()
for region in ['fluid','solid']:
    path=case/f'log.checkMesh.{region}'
    with path.open('w') as log:subprocess.run(['checkMesh','-case',str(case),'-region',region],stdout=log,stderr=subprocess.STDOUT,check=True)
    if 'Mesh OK.' not in path.read_text():raise RuntimeError(f'{region} mesh failed quality check')
command=['chtMultiRegionSimpleFoam','-case',str(case)]
if a.ranks>1:
    (case/'system/decomposeParDict').write_text('FoamFile { version 2.0; format ascii; class dictionary; object decomposeParDict; }\nnumberOfSubdomains '+str(a.ranks)+'; method scotch;\n')
    for region in ['fluid','solid']:(case/f'system/{region}/decomposeParDict').write_text((case/'system/decomposeParDict').read_text())
    with (case/'log.decomposePar').open('w') as log:subprocess.run(['decomposePar','-case',str(case),'-allRegions'],stdout=log,stderr=subprocess.STDOUT,check=True)
    command=['mpirun','--bind-to','none','-np',str(a.ranks)]+command+['-parallel']
with (case/'log.solver').open('w') as log:subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True)
if a.ranks>1:
    with (case/'log.reconstructPar').open('w') as log:subprocess.run(['reconstructPar','-case',str(case),'-allRegions','-latestTime'],stdout=log,stderr=subprocess.STDOUT,check=True)
m=json.loads((case/'manifest.json').read_text());m['simulation_executed']=True;m['numerically_verified']=False;m['case_configuration_sha256']={str(p.relative_to(case)):hashlib.sha256(p.read_bytes()).hexdigest() for folder in ['0','constant','system'] for p in (case/folder).rglob('*') if p.is_file()};(case/'manifest.json').write_text(json.dumps(m,indent=2)+'\n')
