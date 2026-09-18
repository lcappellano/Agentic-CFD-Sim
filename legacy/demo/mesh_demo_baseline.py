#!/usr/bin/env python3
"""Conformal tetrahedral mesh of the verified demo, sized near its bore wall.

Run with workbench job. Specified edge sizes are not achieved wall-cell y+;
CFD must report wall-distance/y+ and mesh sensitivity independently.
"""
import argparse
import json
from pathlib import Path
from src.cad.step_preview import backend
from src.foam.hashing import digest

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('geometry');p.add_argument('output')
p.add_argument('--wall-size',type=float,default=.0005)
p.add_argument('--bulk-size',type=float,default=.002)
p.add_argument('--keep-interface-group',action='store_true')
a=p.parse_args()
geo=Path(a.geometry).resolve(); out=Path(a.output).resolve()
if out.exists(): raise ValueError('Refuse to overwrite mesh')
if not 0<a.wall_size<=a.bulk_size: raise ValueError('Invalid SI mesh sizes')
m=json.loads((geo/'manifest.json').read_text())
for name,h in m['files'].items():
    if digest(geo/name)!=h: raise ValueError(f'Geometry changed: {name}')
g=backend();g.initialize()
try:
    g.open(str(geo/'coupled.geo'))
    if not a.keep_interface_group:g.model.removePhysicalGroups([(2,5)])
    f=g.model.mesh.field.add('Distance')
    g.model.mesh.field.setNumbers(f,'SurfacesList',m['boundary_map']['interface']['occ_surface_tags'])
    g.model.mesh.field.setNumber(f,'Sampling',100)
    t=g.model.mesh.field.add('Threshold')
    for k,v in {'InField':f,'SizeMin':a.wall_size,'SizeMax':a.bulk_size,'DistMin':0,'DistMax':.003}.items():
        g.model.mesh.field.setNumber(t,k,v)
    g.model.mesh.field.setAsBackgroundMesh(t)
    g.option.setNumber('Mesh.MeshSizeMin',a.wall_size)
    g.option.setNumber('Mesh.MeshSizeMax',a.bulk_size)
    g.option.setNumber('Mesh.MeshSizeFromCurvature',36)
    g.option.setNumber('Mesh.MeshSizeExtendFromBoundary',0)
    g.option.setNumber('Mesh.Algorithm3D',1)
    g.option.setNumber('Mesh.Optimize',1)
    g.option.setNumber('Mesh.MshFileVersion',2.2)
    g.model.mesh.generate(3)
    out.parent.mkdir(parents=True,exist_ok=True)
    g.write(str(out))
    counts={name:sum(len(tags) for tags in g.model.mesh.getElements(3,r['occ_volume_tag'])[1]) for name,r in m['regions'].items()}
    report={'geometry_manifest_sha256':digest(geo/'manifest.json'),'mesh_sha256':digest(out),'adapter_sha256':digest(__file__),'gmsh_runtime':g.option.getString('General.Version'),'units':'m','element_counts':counts,'sizing':{'wall_edge_target_m':a.wall_size,'bulk_edge_target_m':a.bulk_size,'transition_distance_m':.003},'wall_distance_and_yplus':'not checked; CFD solver must verify','boundary_layers':'isotropic tetra refinement; no prismatic layers','interface_group_exported':a.keep_interface_group}
    out.with_suffix('.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
finally:g.finalize()
