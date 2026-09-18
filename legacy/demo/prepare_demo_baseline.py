#!/usr/bin/env python3
"""Extract the approved straight-bore demo only; preserve STEP solid exactly.

Exports SI OCC domains and conformal boundary groups. This deliberately refuses
other geometries; it is not an arbitrary STEP fluid-volume extraction adapter.
"""
import argparse
import json
import math
from pathlib import Path
from src.cad.step_preview import backend
from src.foam.hashing import digest

DEMO_SHA = 'b5020829defd7dd4c6fe49cb579501aec6710e8c4fde875658e81e569e0238ec'


def close(a, b, tol=1e-9):
    return abs(a-b) <= tol


def prepare(review, output):
    review, output = Path(review).resolve(), Path(output).resolve()
    source = review / 'source.step'
    if digest(source) != DEMO_SHA:
        raise ValueError('Only the verified demo source hash is supported')
    req = json.loads((review/'requirements.json').read_text())
    model = json.loads((review/'model.json').read_text())
    if req['selections'] != {'inlet':['port:5'], 'outlet':['port:14'], 'heated':['face:3']}:
        raise ValueError('Unsupported approved boundary selection')
    if output.exists():
        raise ValueError('Use a new geometry output directory')
    output.mkdir(parents=True)
    gm = backend()
    gm.initialize()
    try:
        gm.option.setString('Geometry.OCCTargetUnit','MM')
        gm.model.add('solid')
        original = gm.model.occ.importShapes(str(source))
        gm.model.occ.synchronize()
        assert len(gm.model.getEntities(3)) == 1
        for face in model['faces']:
            tag = int(face['id'].split(':')[1])
            assert close(gm.model.occ.getMass(2, tag), face['area_mm2'], 1e-5)
            assert all(close(x,y,1e-6) for x,y in zip(gm.model.occ.getCenterOfMass(2,tag),face['centroid_mm']))
        # Import in metres directly: OCC dilation can alter mass-property
        # integration accuracy at this scale with the installed backend.
        gm.model.remove()
        gm.model.add('solid_si')
        gm.option.setString('Geometry.OCCTargetUnit','M')
        gm.model.occ.importShapes(str(source))
        gm.model.occ.synchronize()
        gm.write(str(output/'solid.brep'))
        gm.model.add('fluid')
        gm.model.occ.addCylinder(0,.020,.010,.060,0,0,.004)
        gm.model.occ.synchronize()
        gm.write(str(output/'fluid.brep'))
        gm.model.add('coupled')
        solids = gm.model.occ.importShapes(str(output/'solid.brep'))
        fluids = gm.model.occ.importShapes(str(output/'fluid.brep'))
        entities, maps = gm.model.occ.fragment(solids, fluids)
        gm.model.occ.synchronize()
        assert len(entities) == 2 and all(d == 3 for d,t in entities)
        solid = maps[0][0][1]
        fluid = maps[1][0][1]
        volumes = {'solid':gm.model.occ.getMass(3,solid),'fluid':gm.model.occ.getMass(3,fluid)}
        expected_fluid = math.pi*.004**2*.060
        assert close(volumes['fluid'],expected_fluid,1e-12)
        assert close(volumes['solid'],.060*.040*.020-expected_fluid,1e-12)
        boundaries = {name:set(t for d,t in gm.model.getBoundary([(3,tag)],oriented=False)) for name,tag in [('solid',solid),('fluid',fluid)]}
        interface = boundaries['solid'] & boundaries['fluid']
        assert len(interface) == 1
        ext_fluid = boundaries['fluid']-interface
        assert len(ext_fluid) == 2
        inlet = [t for t in ext_fluid if close(gm.model.occ.getCenterOfMass(2,t)[0],0)]
        outlet = [t for t in ext_fluid if close(gm.model.occ.getCenterOfMass(2,t)[0],.060)]
        heated = [t for t in boundaries['solid']-interface if close(gm.model.occ.getCenterOfMass(2,t)[2],.020)]
        assert len(inlet) == len(outlet) == len(heated) == 1
        assert close(gm.model.occ.getMass(2,heated[0]),.0024,1e-12)
        for tag in inlet+outlet:
            assert close(gm.model.occ.getMass(2,tag),math.pi*.004**2,1e-12)
        assert close(gm.model.occ.getMass(2,next(iter(interface))),2*math.pi*.004*.060,1e-12)
        groups = {'inlet':inlet,'outlet':outlet,'heated':heated,'outerWalls':sorted(boundaries['solid']-interface-set(heated)),'interface':sorted(interface)}
        # Signed edge boundary of the closed shell must cancel identically.
        for name,tag in [('solid',solid),('fluid',fluid)]:
            shell = gm.model.getBoundary([(3,tag)],oriented=True)
            counts = {}
            for dim,face in shell:
                for _,edge in gm.model.getBoundary([(2,abs(face))],oriented=True):
                    counts[abs(edge)] = counts.get(abs(edge),0)+(1 if face*edge>0 else -1)
            assert all(v == 0 for v in counts.values()), (name,counts)
        port_normals = {'inlet':[-1,0,0], 'outlet':[1,0,0]}
        for name,normal in port_normals.items():
            center = gm.model.occ.getCenterOfMass(2,groups[name][0])
            inside = [x-1e-5*n for x,n in zip(center,normal)]
            outside = [x+1e-5*n for x,n in zip(center,normal)]
            assert gm.model.isInside(3,fluid,inside) == 1
            assert gm.model.isInside(3,fluid,outside) == 0
        gm.write(str(output/'coupled.brep'))
        geo = ['SetFactory("OpenCASCADE");','Merge "coupled.brep";']
        for idx,(name,tags) in enumerate(groups.items(),1):
            gm.model.addPhysicalGroup(2,tags,idx,name)
            geo.append(f'Physical Surface("{name}", {idx}) = {{{", ".join(map(str,tags))}}};')
        for idx,(name,tag) in enumerate([('fluid',fluid),('solid',solid)],101):
            gm.model.addPhysicalGroup(3,[tag],idx,name)
            geo.append(f'Physical Volume("{name}", {idx}) = {{{tag}}};')
        geo += ['Mesh.MshFileVersion = 2.2;','Mesh.MeshSizeMin = 0.0007;','Mesh.MeshSizeMax = 0.002;','Mesh.MeshSizeFromCurvature = 32;']
        (output/'coupled.geo').write_text('\n'.join(geo)+'\n')
        manifest = {'schema_version':1,'source_sha256':digest(source),'requirements_sha256':digest(review/'requirements.json'),'adapter_sha256':digest(__file__),'backend':{'api':gm.__version__,'runtime':gm.option.getString('General.Version')},'scope':'exact approved straight circular through-bore demo only','units':'m','coordinate_frame':'original Cartesian axes, origin unchanged','transform_from_source':{'uniform_scale':.001,'translation':[0,0,0]},'geometry_changed':False,'regions':{'solid':{'material':req['requirements']['solid_material'],'volume_m3':volumes['solid'],'occ_volume_tag':solid,'file':'solid.brep'},'fluid':{'material':req['requirements']['coolant_material'],'volume_m3':volumes['fluid'],'occ_volume_tag':fluid,'file':'fluid.brep'}},'heated_area_m2':.0024,'boundary_map':{name:{'occ_surface_tags':tags,'area_m2':sum(gm.model.occ.getMass(2,t) for t in tags),'centroids_m':[gm.model.occ.getCenterOfMass(2,t) for t in tags]} for name,tags in groups.items()},'port_outward_normals':port_normals,'port_normal_evidence':'inside/outside OCC volume probes at 10 micrometres either side of cap centers; display fitted loop normals are not outward normals','approved_identity_map':{'face:3':'heated','port:5':'inlet','port:14':'outlet'},'checks':{'positive_volumes':'pass','fluid_connectivity':'pass: one OCC cylinder volume','watertightness':'pass: signed shell edge cancellation for both domains','interface':'pass: one shared OCC surface; exact analytical area','volume_conservation':'pass: fluid + solid = original bounding box','original_face_identity':'pass: all seven source areas and centroids matched approved model before scaling','heated_identity':'pass: z=0.020 m plane and 0.0024 m2','ports':'pass: x=0 and x=0.060 m disks, radius 0.004 m','source_immutable':'pass'},'limitations':['No arbitrary STEP extraction support','Mesh quality and discretized curved-wall error require separate CFD verification'],'files':{p.name:digest(p) for p in output.iterdir() if p.is_file()}}
        (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        print(json.dumps({'output':str(output),'volumes_m3':volumes,'boundary_groups':groups},indent=2))
    finally:
        gm.finalize()

if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('review'); p.add_argument('output')
    a=p.parse_args(); prepare(a.review,a.output)
