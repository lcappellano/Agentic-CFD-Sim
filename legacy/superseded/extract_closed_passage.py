#!/usr/bin/env python3
"""Exact OCC extraction for one solid with two opposed axis-aligned end ports.

Uses a clipping enclosure to disconnect the passage from the external void.
Rejects unsupported port arrangements and ambiguous cavities rather than guessing.
All geometry is imported directly in SI; source STEP is never modified.
"""
import argparse
import json
import math
from pathlib import Path
from step_preview import backend, digest


def near(a,b,rel=1e-6,abs_tol=1e-10):
    return abs(a-b)<=max(abs_tol,rel*max(abs(a),abs(b)))


def surface_matches(g,tag,face,scale=.001):
    return near(g.model.occ.getMass(2,tag),face['area_mm2']*scale**2) and all(near(x,y*scale,abs_tol=1e-8) for x,y in zip(g.model.occ.getCenterOfMass(2,tag),face['centroid_mm']))


def boundary(g,tag):
    return set(t for d,t in g.model.getBoundary([(3,tag)],oriented=False))


def shell_check(g,tag):
    counts={}
    for _,face in g.model.getBoundary([(3,tag)],oriented=True):
        for _,edge in g.model.getBoundary([(2,abs(face))],oriented=True):
            counts[abs(edge)]=counts.get(abs(edge),0)+(1 if face*edge>0 else -1)
    if any(counts.values()): raise ValueError('Non-closed oriented OCC shell')


def prepare(review,output):
    review,output=Path(review).resolve(),Path(output).resolve()
    source=review/'source.step'; original_hash=digest(source)
    model=json.loads((review/'model.json').read_text()); req=json.loads((review/'requirements.json').read_text())
    if model['source']['sha256']!=original_hash: raise ValueError('STEP hash changed')
    faces={f['id']:f for f in model['faces']}; ports={f['id']:f for f in model['virtual_faces']}
    selections=req['selections']
    if any(len(selections[k])!=1 for k in ('inlet','outlet')): raise ValueError('Requires one inlet and outlet')
    caps={k:ports[selections[k][0]] for k in ('inlet','outlet')}
    centers=[caps[k]['centroid_mm'] for k in caps]
    axes=[i for i in range(3) if abs(centers[0][i]-centers[1][i])>1e-5]
    if len(axes)!=1: raise ValueError('Ports must be opposed and axis aligned')
    axis=axes[0]
    if any(abs(abs(p['normal'][axis])-1)>1e-6 for p in caps.values()): raise ValueError('Non-axial port normals')
    if output.exists(): raise ValueError('Use new output directory')
    output.mkdir(parents=True)
    g=backend();g.initialize()
    try:
        g.option.setNumber('General.NumThreads',1)
        g.option.setString('Geometry.OCCTargetUnit','M');g.model.add('solid')
        solids=g.model.occ.importShapes(str(source));g.model.occ.synchronize()
        if len(solids)!=1 or solids[0][0]!=3: raise ValueError('One solid required')
        solid=solids[0][1]
        for f in faces.values():
            if not surface_matches(g,int(f['id'].split(':')[1]),f): raise ValueError('Approved face mismatch '+f['id'])
        source_volume=g.model.occ.getMass(3,solid);g.write(str(output/'solid.brep'))
        bb=g.model.getBoundingBox(3,solid); lo=[bb[i]-.01 for i in range(3)];hi=[bb[i+3]+.01 for i in range(3)]
        lo[axis]=min(c[axis] for c in centers)*.001;hi[axis]=max(c[axis] for c in centers)*.001
        if bb[axis]<lo[axis]-1e-6 or bb[axis+3]>hi[axis]+1e-6: raise ValueError('Ports must lie on extreme clipping planes')
        box=g.model.occ.addBox(*lo,*[hi[i]-lo[i] for i in range(3)])
        voids,_=g.model.occ.cut([(3,box)],solids);g.model.occ.synchronize()
        candidates=[]
        for d,t in voids:
            b=boundary(g,t)
            matches={k:[f for f in b if surface_matches(g,f,p)] for k,p in caps.items()}
            if all(len(v)==1 for v in matches.values()): candidates.append(t)
        if len(candidates)!=1: raise ValueError(f'Expected single connected passage; found {candidates}')
        fluid=candidates[0]; fluid_volume=g.model.occ.getMass(3,fluid)
        g.model.occ.remove([(d,t) for d,t in voids if t!=fluid],recursive=True);g.model.occ.synchronize()
        shell_check(g,fluid);g.write(str(output/'fluid.brep'))
        g.model.add('coupled');ss=g.model.occ.importShapes(str(output/'solid.brep'));ff=g.model.occ.importShapes(str(output/'fluid.brep'))
        ents,maps=g.model.occ.fragment(ss,ff);g.model.occ.synchronize()
        if len(ents)!=2 or any(len(m)!=1 for m in maps): raise ValueError('Fragmentation changed region count')
        solid=maps[0][0][1];fluid=maps[1][0][1]
        volumes={n:g.model.occ.getMass(3,t) for n,t in [('solid',solid),('fluid',fluid)]}
        if min(volumes.values())<=0 or not near(volumes['solid'],source_volume) or not near(volumes['fluid'],fluid_volume): raise ValueError('Volume changed')
        sb,fb=boundary(g,solid),boundary(g,fluid); interface=sb&fb
        groups={k:[f for f in fb-interface if surface_matches(g,f,p)] for k,p in caps.items()}
        groups['heated']=[f for f in sb-interface if any(surface_matches(g,f,faces[key]) for key in selections['heated'])]
        if any(len(groups[k])!=1 for k in caps) or len(groups['heated'])!=len(selections['heated']): raise ValueError('Boundary identity ambiguous')
        if fb-interface != set(groups['inlet']+groups['outlet']): raise ValueError('Unexpected exposed fluid surface')
        groups['outerWalls']=sorted(sb-interface-set(groups['heated']));groups['interface']=sorted(interface)
        if not interface: raise ValueError('No shared interface')
        normals={}
        for k,p in caps.items():
            normal=[0,0,0];normal[axis]=1 if p['centroid_mm'][axis]*.001==hi[axis] else -1
            c=g.model.occ.getCenterOfMass(2,groups[k][0])
            if g.model.isInside(3,fluid,[c[i]-normal[i]*1e-6 for i in range(3)])!=1 or g.model.isInside(3,fluid,[c[i]+normal[i]*1e-6 for i in range(3)])!=0: raise ValueError('Port normal check failed')
            normals[k]=normal
        for t in (solid,fluid):shell_check(g,t)
        g.write(str(output/'coupled.brep'))
        geo=['SetFactory("OpenCASCADE");','Merge "coupled.brep";']
        for idx,(name,tags) in enumerate(groups.items(),1):geo.append(f'Physical Surface("{name}", {idx}) = {{{", ".join(map(str,tags))}}};')
        for idx,(name,tag) in enumerate([('fluid',fluid),('solid',solid)],101):geo.append(f'Physical Volume("{name}", {idx}) = {{{tag}}};')
        (output/'coupled.geo').write_text('\n'.join(geo)+'\n')
        if digest(source)!=original_hash:raise ValueError('Source modified')
        manifest={'schema_version':1,'source_sha256':original_hash,'requirements_sha256':digest(review/'requirements.json'),'adapter_sha256':digest(__file__),'backend':{'api':g.__version__,'runtime':g.option.getString('General.Version')},'scope':'one connected solid with two opposed circular axis-aligned ports at extreme clipping planes','units':'m','coordinate_frame':'original Cartesian axes and origin','transform_from_source':{'uniform_scale':.001,'translation':[0,0,0]},'geometry_changed':False,'regions':{n:{'material':req['requirements']['solid_material' if n=='solid' else 'coolant_material'],'volume_m3':volumes[n],'occ_volume_tag':t,'file':n+'.brep'} for n,t in [('solid',solid),('fluid',fluid)]},'heated_area_m2':sum(g.model.occ.getMass(2,t) for t in groups['heated']),'boundary_map':{n:{'occ_surface_tags':ts,'area_m2':sum(g.model.occ.getMass(2,t) for t in ts),'centroids_m':[g.model.occ.getCenterOfMass(2,t) for t in ts]} for n,ts in groups.items()},'port_outward_normals':normals,'port_diameter_m':{n:2*p['radius_mm']*.001 for n,p in caps.items()},'approved_identity_map':{key:role for role,keys in selections.items() for key in keys},'checks':{'positive_volumes':'pass','fluid_connectivity':'pass: exactly one OCC volume with both approved caps','watertightness':'pass: signed shell edge cancellation in both domains','interface':'pass: common OCC surfaces after conformal fragmentation','source_solid_volume_conservation':'pass','fluid_volume_conservation':'pass','original_face_identity':'pass: all approved areas and centroids checked after direct SI import','heated_identity':'pass: approved areas/centroids uniquely matched','ports':'pass: cap areas/centroids, exposed boundary completeness, and inward/outward probes','source_immutable':'pass'},'limitations':['Extraction supports the documented opposed end-port class only','Mesh quality, channel resolution, wall treatment and CFD convergence require independent verification'],'files':{p.name:digest(p) for p in output.iterdir() if p.is_file()}}
        (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        print(json.dumps({'output':str(output),'volumes_m3':volumes,'heated_area_m2':manifest['heated_area_m2'],'interface_faces':len(interface)},indent=2))
    finally:g.finalize()

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('review');p.add_argument('output');a=p.parse_args();prepare(a.review,a.output)
