"""Diagnostic constant-cell-velocity flux through actual tetrahedral mesh cuts.

Bins classify the cut fluid polygons; nominal rectangles never replace geometry.
This interpolation is not the solver's conservative face-flux reconstruction.
"""
import argparse
import itertools
import json
import math
from pathlib import Path
from src.foam.hashing import digest
from src.verification.audit_fields import thermo_declaration_check
from src.verification.independent_reader import Mesh, clean


def tetra_cut(vertices, x, tolerance=1e-12):
    if len(vertices) != 4:
        raise ValueError('Only four-vertex tetrahedral cells supported')
    distances = [p[0]-x if abs(p[0]-x)>tolerance else 0. for p in vertices]
    # Half-open convention: a coincident face belongs to the negative-x cell.
    if min(distances) >= 0 or max(distances) < 0:
        return []
    points = [tuple(p[1:]) for p,d in zip(vertices,distances) if d == 0]
    for i,j in itertools.combinations(range(4),2):
        if distances[i]*distances[j] < 0:
            f=distances[i]/(distances[i]-distances[j])
            points.append(tuple(vertices[i][k]+f*(vertices[j][k]-vertices[i][k]) for k in (1,2)))
    unique=[]
    for point in points:
        if not any(math.dist(point,p)<=tolerance for p in unique): unique.append(point)
    if len(unique)<3:return []
    centre=[sum(p[k] for p in unique)/len(unique) for k in (0,1)]
    return sorted(unique,key=lambda p:math.atan2(p[1]-centre[1],p[0]-centre[0]))


def area(polygon):
    if len(polygon)<3:return 0.
    # Shift the origin to avoid cancellation for small cuts far from zero.
    y,z=polygon[0]
    return abs(math.fsum((a[0]-y)*(b[1]-z)-(b[0]-y)*(a[1]-z)
                        for a,b in zip(polygon,polygon[1:]+polygon[:1])))*.5


def clip_bin(polygon, y_bounds, z_bounds):
    result=list(polygon)
    for axis,bounds in enumerate((y_bounds,z_bounds)):
        for bound,sign in ((bounds[0],1),(bounds[1],-1)):
            source,result=result,[]
            if not source:break
            for a,b in zip(source,source[1:]+source[:1]):
                da,db=sign*(a[axis]-bound),sign*(b[axis]-bound)
                if da>=0:result.append(a)
                if (da>=0)!=(db>=0):
                    f=da/(da-db)
                    result.append(tuple(a[k]+f*(b[k]-a[k]) for k in (0,1)))
    return result


def integrate(cells, velocities, channels, rho):
    if len(cells)!=len(velocities) or not math.isfinite(rho) or rho<=0:
        raise ValueError('Invalid field size or constant density')
    if not channels or len({c['id'] for c in channels})!=len(channels):
        raise ValueError('Nonempty unique channel IDs required')
    planes={c['x_m'] for c in channels}
    if len(planes)!=1 or not all(math.isfinite(v) for v in planes):raise ValueError('One finite common x plane required')
    if len({tuple(c['positive_flow_normal']) for c in channels})!=1:raise ValueError('Common positive-flow normal required')
    for c in channels:
        if c['positive_flow_normal'] not in ([-1,0,0],[1,0,0]):raise ValueError('Expected unit x normal')
        for key in ('y_bounds_m','z_bounds_m'):
            if len(c[key])!=2 or not all(math.isfinite(v) for v in c[key]) or not c[key][0]<c[key][1]:
                raise ValueError('Invalid channel bounds')
    for a,b in itertools.combinations(channels,2):
        if all(min(a[k][1],b[k][1])>max(a[k][0],b[k][0]) for k in ('y_bounds_m','z_bounds_m')):
            raise ValueError('Channel bins overlap')
    outputs=[{'id':c['id'],'area_m2':0.,'mass_flow_kg_s':0.,'reversed_mass_flow_kg_s':0.,'cut_cells':0} for c in channels]
    total_area=0.
    for vertices,velocity in zip(cells,velocities):
        if len(velocity)!=3 or not all(math.isfinite(v) for v in velocity):raise ValueError('Invalid velocity')
        polygon=tetra_cut(vertices,next(iter(planes)))
        total_area+=area(polygon)
        if not polygon:continue
        for c,out in zip(channels,outputs):
            cut_area=area(clip_bin(polygon,c['y_bounds_m'],c['z_bounds_m']))
            if cut_area<=0:continue
            mass=rho*velocity[0]*c['positive_flow_normal'][0]*cut_area
            out['area_m2']+=cut_area
            out['mass_flow_kg_s']+=mass
            out['reversed_mass_flow_kg_s']+=max(-mass,0)
            out['cut_cells']+=1
    return {'channels':outputs,'entire_fluid_cut_area_m2':total_area,
            'unclassified_cut_area_m2':total_area-sum(c['area_m2'] for c in outputs),
            'sum_mass_flow_kg_s':sum(c['mass_flow_kg_s'] for c in outputs)}


def audit(case, sections, settings_path, iteration):
    settings=json.loads(settings_path.read_text()); spec=json.loads(sections.read_text())
    if spec['units']!='m':raise ValueError('Channel bins must use metres')
    hashes={str(p):digest(p) for p in (sections,settings_path,Path(__file__))}
    thermo_path=case/'constant/fluid/thermophysicalProperties'
    declaration=thermo_declaration_check(settings,clean(thermo_path))
    if declaration['status']!='pass':raise ValueError('Unsupported or inconsistent constant density/Cp declaration')
    hashes[str(thermo_path)]=digest(thermo_path)
    mesh=Mesh(case/'constant/fluid/polyMesh',hashes)
    nodes=[set() for _ in range(mesh.cell_count)]
    counts=[0]*mesh.cell_count
    for i,face in enumerate(mesh.faces):
        if len(face)!=3:raise ValueError('Only triangular tetrahedron faces supported')
        for cell in ([mesh.owners[i],mesh.neighbours[i]] if i<len(mesh.neighbours) else [mesh.owners[i]]):
            nodes[cell].update(face);counts[cell]+=1
    if any(len(n)!=4 or count!=4 for n,count in zip(nodes,counts)):raise ValueError('Non-tetrahedral topology')
    values=mesh.read(case/iteration/'fluid/U',expected_dimensions=[0,1,-1,0,0,0,0])
    result=integrate([[mesh.points[n] for n in cell] for cell in nodes],values,spec['channels'],settings['rho_kg_m3'])
    ports={port:sum(mesh.read(case/iteration/'fluid/phi',port,[1,0,-1,0,0,0,0])) for port in ('inlet','outlet')}
    result.update(case=str(case),iteration=iteration,source_sha256=hashes,port_signed_outward_mass_kg_s=ports,
                  status='diagnostic_cell_velocity_cut_not_conservative_face_flux',
                  limitation='Piecewise constant saved cell U on exact mesh-plane polygons; no nodal interpolation. Mesh approximates CAD fillets. Sum mismatch reflects interpolation and/or convergence; not a mass-conservation acceptance test.')
    result['sum_relative_to_inlet_difference']=result['sum_mass_flow_kg_s']/(-ports['inlet'])-1 if ports['inlet'] else None
    result['sum_relative_to_outlet_difference']=result['sum_mass_flow_kg_s']/ports['outlet']-1 if ports['outlet'] else None
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case',type=Path);parser.add_argument('--sections',type=Path,required=True)
    parser.add_argument('--settings',type=Path,required=True);parser.add_argument('--iteration',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();result=audit(args.case,args.sections,args.settings,args.iteration)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x') as stream:json.dump(result,stream,indent=2,allow_nan=False)
    print(json.dumps({k:v for k,v in result.items() if k!='source_sha256'},indent=2))
