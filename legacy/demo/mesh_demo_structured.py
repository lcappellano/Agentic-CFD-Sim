#!/usr/bin/env python3
"""Analytic conformal hexahedral O-grid for the exact hash-guarded demo.

Central square + four fluid blocks + four copper blocks are extruded along x.
The circular boundary is faceted only by mesh discretization; CAD is unchanged.
"""
import argparse
import json
import math
from pathlib import Path
from src.foam.hashing import digest
from legacy.demo.prepare_demo_baseline import DEMO_SHA


def build(geometry, output, level, fluid_radial=None):
    geo=Path(geometry).resolve();out=Path(output).resolve()
    if out.exists() or out.with_suffix('.json').exists():raise ValueError('Use new mesh paths')
    manifest=json.loads((geo/'manifest.json').read_text())
    if manifest['source_sha256']!=DEMO_SHA or manifest['units']!='m':raise ValueError('Unsupported geometry')
    for name,h in manifest['files'].items():
        if digest(geo/name)!=h:raise ValueError('Geometry hash mismatch')
    n,nr,ns,nx = (16,8,14,48) if level=='coarse' else (24,12,20,72)
    if fluid_radial is not None:
        if fluid_radial < 2: raise ValueError('Need at least two fluid radial layers')
        nr=fluid_radial
    a=.0015;r=.004;length=.060
    points=[]; lookup={};cells=[];outer=[];interface=[]
    def point(y,z):
        key=(round(y,14),round(z,14))
        if key not in lookup:lookup[key]=len(points);points.append((y,z))
        return lookup[key]
    def cell(ids,region):cells.append((ids,region))
    square=[[point(-a+2*a*i/n,-a+2*a*j/n) for j in range(n+1)] for i in range(n+1)]
    for i in range(n):
        for j in range(n):cell([square[i][j],square[i+1][j],square[i+1][j+1],square[i][j+1]],'fluid')
    for sector in range(4):
        inner=[];circle=[];outside=[]
        for j in range(n+1):
            u=-1+2*j/n
            y,z=[(a,a*u),(-a*u,a),(-a,-a*u),(a*u,-a)][sector]
            inner.append((y,z));rho=math.hypot(y,z);circle.append((r*y/rho,r*z/rho))
            outside.append([(.020,.010*u),(-.020*u,.010),(-.020,-.010*u),(.020*u,-.010)][sector])
        for region,start,end,layers,q in [('fluid',inner,circle,nr,.88**(8/nr)),('solid',circle,outside,ns,1.15**(14/ns))]:
            grid=[]
            for k in range(layers+1):
                t=(q**k-1)/(q**layers-1)
                grid.append([point(s[0]+t*(e[0]-s[0]),s[1]+t*(e[1]-s[1])) for s,e in zip(start,end)])
            for k in range(layers):
                for j in range(n):
                    ids=[grid[k][j],grid[k+1][j],grid[k+1][j+1],grid[k][j+1]]
                    cell(ids,region)
                    if region=='fluid' and k==layers-1:interface.append((grid[k+1][j],grid[k+1][j+1],len(cells)-1))
            if region=='solid':
                for j in range(n):outer.append((grid[-1][j],grid[-1][j+1],'heated' if sector==1 else 'outerWalls'))
    def area(ids):return .5*sum(points[ids[i]][0]*points[ids[(i+1)%4]][1]-points[ids[(i+1)%4]][0]*points[ids[i]][1] for i in range(4))
    areas=[area(ids) for ids,_ in cells]
    if min(areas)<=0:raise ValueError('Non-positive cross-section area')
    volumes={name:sum(ar for ar,(_,reg) in zip(areas,cells) if reg==name)*length for name in ['fluid','solid']}
    reference={name:reg['volume_m3'] for name,reg in manifest['regions'].items()}
    errors={name:abs(volumes[name]/reference[name]-1) for name in volumes}
    if max(errors.values())>.005:raise ValueError('Excessive faceting volume error')
    if abs(sum(volumes.values())-.060*.040*.020)>1e-14:raise ValueError('Volume conservation failure')
    centers=[tuple(sum(points[v][d] for v in ids)/4 for d in [0,1]) for ids,_ in cells]
    wall_dist=[]
    for p0,p1,ci in interface:
        y0,z0=points[p0];y1,z1=points[p1];yc,zc=centers[ci]
        wall_dist.append(abs((y1-y0)*(zc-z0)-(z1-z0)*(yc-y0))/math.hypot(y1-y0,z1-z0))
    # Cross-section connectivity and normal-angle checks; axial extrusion is orthogonal.
    edge_cells={}
    for ci,(ids,reg) in enumerate(cells):
        for j in range(4):edge_cells.setdefault(tuple(sorted([ids[j],ids[(j+1)%4]])),[]).append(ci)
    if any(len(v)>2 for v in edge_cells.values()):raise ValueError('Non-manifold section')
    max_nonorth=0
    adjacency={name:{} for name in ['fluid','solid']}
    for (p0,p1),owners in edge_cells.items():
        if len(owners)==2:
            i,j=owners;dy=centers[j][0]-centers[i][0];dz=centers[j][1]-centers[i][1]
            ey=points[p1][0]-points[p0][0];ez=points[p1][1]-points[p0][1]
            c=abs(dy*ez-dz*ey)/(math.hypot(dy,dz)*math.hypot(ey,ez))
            max_nonorth=max(max_nonorth,math.degrees(math.acos(min(1,c))))
            if cells[i][1]==cells[j][1]:
                adj=adjacency[cells[i][1]];adj.setdefault(i,set()).add(j);adj.setdefault(j,set()).add(i)
    for reg,adj in adjacency.items():
        seen=set();todo=[next(i for i,(_,name) in enumerate(cells) if name==reg)]
        while todo:
            ci=todo.pop()
            if ci in seen:continue
            seen.add(ci);todo.extend(adj.get(ci,set())-seen)
        if len(seen)!=sum(name==reg for _,name in cells):raise ValueError('Disconnected region')
    if max_nonorth>70:raise ValueError(f'Excessive nonorthogonality {max_nonorth}')
    phys={'inlet':1,'outlet':2,'heated':3,'outerWalls':4,'fluid':101,'solid':102}
    nn=len(points)
    def nid(k,i):return k*nn+i+1
    boundary=[]
    for ids,reg in cells:
        boundary.append(([nid(0,i) for i in reversed(ids)],'inlet' if reg=='fluid' else 'outerWalls'))
        boundary.append(([nid(nx,i) for i in ids],'outlet' if reg=='fluid' else 'outerWalls'))
    for k in range(nx):
        for p0,p1,name in outer:boundary.append(([nid(k,p0),nid(k+1,p0),nid(k+1,p1),nid(k,p1)],name))
    out.parent.mkdir(parents=True,exist_ok=True)
    with out.open('w') as f:
        f.write('$MeshFormat\n2.2 0 8\n$EndMeshFormat\n$PhysicalNames\n6\n')
        for name,tag in phys.items():f.write(f'{3 if tag>100 else 2} {tag} "{name}"\n')
        f.write(f'$EndPhysicalNames\n$Nodes\n{nn*(nx+1)}\n')
        for k in range(nx+1):
            for i,(y,z) in enumerate(points):f.write(f'{nid(k,i)} {length*k/nx:.16g} {y+.020:.16g} {z+.010:.16g}\n')
        f.write(f'$EndNodes\n$Elements\n{len(boundary)+len(cells)*nx}\n')
        ei=0
        for ids,name in boundary:
            ei+=1;f.write(f'{ei} 3 2 {phys[name]} {phys[name]} '+ ' '.join(map(str,ids))+'\n')
        for k in range(nx):
            for ids,reg in cells:
                ei+=1;hexids=[nid(k,i) for i in ids]+[nid(k+1,i) for i in ids]
                f.write(f'{ei} 5 2 {phys[reg]} {phys[reg]} '+' '.join(map(str,hexids))+'\n')
        f.write('$EndElements\n')
    report={'geometry_manifest_sha256':digest(geo/'manifest.json'),'source_sha256':DEMO_SHA,'mesh_sha256':digest(out),'adapter_sha256':digest(__file__),'units':'m','mesh_type':'conformal extruded O-grid hexahedra','level':level,'fluid_radial_override':fluid_radial,'wall_refinement_policy':'Preserve log-layer wall-function validity when selecting fluid radial override; check solved y+','element_counts':{name:sum(reg==name for _,reg in cells)*nx for name in ['fluid','solid']},'sizing':{'circumferential_segments':4*n,'fluid_radial_layers':nr,'solid_radial_layers':ns,'axial_layers':nx,'axial_spacing_m':length/nx,'fluid_wall_cell_center_distance_m':[min(wall_dist),max(wall_dist)]},'mesh_volumes_m3':volumes,'volume_relative_errors_vs_exact_CAD':errors,'heated_area_m2':.0024,'checks':{'positive_section_areas':min(areas),'connected_regions':'pass','shared_interface_nodes':'pass','total_volume_conservation':'pass','max_internal_face_nonorthogonality_deg':max_nonorth},'limitations':['Straight extruded demonstration geometry only','Circular surface represented by controlled polygon faceting','OpenFOAM checkMesh and solution y+ still required']}
    out.with_suffix('.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('geometry');p.add_argument('output');p.add_argument('--level',choices=['coarse','fine'],default='coarse')
    p.add_argument('--fluid-radial',type=int,help='Override fluid radial layers to preserve wall-function y+ while refining other directions')
    a=p.parse_args();build(a.geometry,a.output,a.level,a.fluid_radial)
