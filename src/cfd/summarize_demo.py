"""Read ASCII OpenFOAM baseline monitoring and boundary fields without extra dependencies."""
import argparse,json,re,math
from pathlib import Path

def numbers(case,name):
    paths=sorted((case/'postProcessing').glob('*/'+name+'/*/surfaceFieldValue.dat'),key=lambda p:float(p.parent.name))
    if not paths: return []
    rows={}
    for p in paths:
        for line in p.read_text().splitlines():
            if not line.startswith('#') and line.strip():
                ns=[float(x) for x in line.replace('(',' ').replace(')',' ').split()]
                rows[ns[0]]=ns[1:]
    return [(t,v) for t,v in sorted(rows.items())]

def patch_values(text,patch):
    match=re.search(r'\b'+re.escape(patch)+r'\s*\{',text)
    if not match: raise ValueError(patch)
    start=match.end();level=1;i=start
    while level:
        if text[i]=='{':level+=1
        elif text[i]=='}':level-=1
        i+=1
    block=text[start:i-1]
    v=re.search(r'\bvalue\s+(nonuniform\s+List<\w+>\s+(\d+)\s*\((.*?)\)\s*;|uniform\s+(.*?);)',block,re.S)
    if not v: raise ValueError('No value '+patch)
    raw=v.group(3) if v.group(2) else v.group(4)
    if '(' in raw:return [[float(z) for z in x.split()] for x in re.findall(r'\(([^()]+)\)',raw)]
    return [float(x) for x in raw.split()]

def mesh_list(path):
    text=path.read_text();text=re.sub(r'/\*.*?\*/|//[^\n]*','',text,flags=re.S)
    text=text[text.index('}')+1:]
    return text[text.index('(')+1:text.rindex(')')]

def read_boundary(field,patch,mesh):
    text=field.read_text()
    block=re.search(r'\b'+patch+r'\s*\{(.*?)\}',(mesh/'boundary').read_text(),re.S).group(1)
    start=int(re.search(r'startFace\s+(\d+)',block).group(1));count=int(re.search(r'nFaces\s+(\d+)',block).group(1))
    try: vals=patch_values(text,patch)
    except ValueError:
        bc=re.search(r'\b'+patch+r'\s*\{(.*?)\}',text,re.S).group(1)
        if 'zeroGradient' not in bc:raise
        internal=text.split('internalField',1)[1].split('boundaryField',1)[0]
        vals=patch_values('internal { value '+internal+' }','internal')
        owners=[int(x) for x in mesh_list(mesh/'owner').split()]
        return [vals[owners[i]] for i in range(start,start+count)]
    if len(vals)==1:vals=vals*count
    if len(vals)!=count:raise ValueError('Patch value count mismatch')
    return vals

def inlet_diffusion_aligned_hex(case,latest):
    mesh=case/'constant/fluid/polyMesh'
    pts=[[float(z) for z in x.split()] for x in re.findall(r'\(([^()]+)\)',mesh_list(mesh/'points'))]
    faces=[[int(z) for z in x.split()] for x in re.findall(r'\d+\(([^()]+)\)',mesh_list(mesh/'faces'))]
    owners=[int(x) for x in mesh_list(mesh/'owner').split()];neighbours=[int(x) for x in mesh_list(mesh/'neighbour').split()]
    block=re.search(r'inlet\s*\{(.*?)\}',(mesh/'boundary').read_text(),re.S).group(1)
    start=int(re.search(r'startFace\s+(\d+)',block).group(1));count=int(re.search(r'nFaces\s+(\d+)',block).group(1))
    target={owners[i]:set() for i in range(start,start+count)}
    for i,face in enumerate(faces):
        if owners[i] in target:target[owners[i]].update(face)
        if i<len(neighbours) and neighbours[i] in target:target[neighbours[i]].update(face)
    if any(len(nodes)!=8 for nodes in target.values()):return None
    text=(latest/'fluid/T').read_text().split('internalField',1)[1].split('boundaryField',1)[0]
    temp=patch_values('internal { value '+text+' }','internal')
    alphat=read_boundary(latest/'fluid/alphat','inlet',mesh)
    settings=json.loads((case/'baseline-settings.json').read_text());cp=settings['cp_J_kg_K'];k=settings['k_W_m_K'];total=0
    for j,i in enumerate(range(start,start+count)):
        poly=[pts[n] for n in faces[i]]
        if any(abs(p[0])>1e-12 for p in poly):return None
        area=abs(sum(poly[n][1]*poly[(n+1)%len(poly)][2]-poly[(n+1)%len(poly)][1]*poly[n][2] for n in range(len(poly)))/2)
        distance=sum(pts[n][0] for n in target[owners[i]])/8
        total+=(k+cp*alphat[j])*(300-temp[owners[i]])/distance*area
    return total

def wall_yplus_geometry(case,values):
    mesh=case/'constant/fluid/polyMesh'
    pts=[[float(z) for z in x.split()] for x in re.findall(r'\(([^()]+)\)',mesh_list(mesh/'points'))]
    faces=[[int(z) for z in x.split()] for x in re.findall(r'\d+\(([^()]+)\)',mesh_list(mesh/'faces'))]
    block=re.search(r'fluid_to_solid\s*\{(.*?)\}',(mesh/'boundary').read_text(),re.S).group(1)
    start=int(re.search(r'startFace\s+(\d+)',block).group(1));count=int(re.search(r'nFaces\s+(\d+)',block).group(1))
    if count!=len(values):raise ValueError('yPlus face mismatch')
    areas=[];centres=[]
    for face in faces[start:start+count]:
        poly=[pts[n] for n in face];av=[0.,0.,0.]
        for i,p in enumerate(poly):
            q=poly[(i+1)%len(poly)]
            av[0]+=p[1]*q[2]-p[2]*q[1];av[1]+=p[2]*q[0]-p[0]*q[2];av[2]+=p[0]*q[1]-p[1]*q[0]
        areas.append(.5*math.sqrt(sum(x*x for x in av)));centres.append([sum(p[j] for p in poly)/len(poly) for j in range(3)])
    inds=[i for i,v in enumerate(values) if v<30]
    return {'area_fraction_below30':sum(areas[i] for i in inds)/sum(areas),'minimum_location_m':centres[min(range(count),key=values.__getitem__)],'below30_x_range_m':[min(centres[i][0] for i in inds),max(centres[i][0] for i in inds)] if inds else None}

def hottest_location(case,latest):
    mesh=case/'constant/solid/polyMesh'
    pts=[[float(z) for z in x.split()] for x in re.findall(r'\(([^()]+)\)',mesh_list(mesh/'points'))]
    faces=[[int(z) for z in x.split()] for x in re.findall(r'\d+\(([^()]+)\)',mesh_list(mesh/'faces'))]
    block=re.search(r'heated\s*\{(.*?)\}',(mesh/'boundary').read_text(),re.S).group(1)
    start=int(re.search(r'startFace\s+(\d+)',block).group(1))
    vals=patch_values((latest/'solid/T').read_text(),'heated');i=max(range(len(vals)),key=vals.__getitem__)
    face=faces[start+i]
    return {'temperature_K':vals[i],'coordinate_m':[sum(pts[j][k] for j in face)/len(face) for k in range(3)],'location_kind':'hottest heated boundary face centroid','global_face_index':start+i}

def summarize(case):
    names=['inletPressure','outletPressure','inletMass','outletMass','inletTemperature','outletTemperature','heatedMax','wettedMax','heatedPower','interfacePower','fluidPower']
    data={n:numbers(case,n) for n in names};last={n:r[-1][1][0] if r else None for n,r in data.items()}
    latest=max((p for p in case.iterdir() if p.is_dir() and re.fullmatch(r'\d+(\.\d+)?',p.name)),key=lambda p:float(p.name))
    if any(not r or r[-1][0]!=float(latest.name) for r in data.values()):raise ValueError('Monitor and saved field timestamps differ')
    kinetic={}
    for patch in ['inlet','outlet']:
        phi=read_boundary(latest/'fluid/phi',patch,case/'constant/fluid/polyMesh');u=read_boundary(latest/'fluid/U',patch,case/'constant/fluid/polyMesh')
        if len(u)==1:u=u*len(phi)
        if len(phi)==1:phi=phi*len(u)
        if len(phi)!=len(u):raise ValueError('Unequal phi/U patch sizes')
        kinetic[patch]=sum(f*.5*sum(v*v for v in vel) for f,vel in zip(phi,u))
    cp=json.loads((case/'baseline-settings.json').read_text())['cp_J_kg_K']
    # Reference enthalpy at inlet300 K avoids amplifying tiny continuity error.
    heat=cp*(last['outletMass']*(last['outletTemperature']-300)+last['inletMass']*(last['inletTemperature']-300))
    out={'case':str(case),'latest_fields':latest.name,'monitor_last':last,'sensible_heat_pickup_W':heat,'kinetic_energy_flux_W':kinetic,'modeled_advected_energy_pickup_W':heat+sum(kinetic.values()),'pressure_drop_Pa':last['inletPressure']-last['outletPressure'],'mass_imbalance_fraction':abs(last['inletMass']+last['outletMass'])/abs(last['inletMass']),'final_100_iteration_ranges':{n:(max(v[0] for t,v in r if t>=r[-1][0]-100)-min(v[0] for t,v in r if t>=r[-1][0]-100)) if r else None for n,r in data.items()}}
    yp=patch_values((latest/'fluid/yPlus').read_text(),'fluid_to_solid')
    out['yplus_face_count_distribution']={'min':min(yp),'max':max(yp),'mean':sum(yp)/len(yp),'fraction_below30':sum(x<30 for x in yp)/len(yp),'fraction_above300':sum(x>300 for x in yp)/len(yp)}
    minmax=list((case/'postProcessing/fluid/fluidMinMax').glob('*/fieldMinMax.dat'))
    lines=[l for f in minmax for l in f.read_text().splitlines() if not l.startswith('#') and l.split()[1:2]==['p']]
    line=max(lines,key=lambda l:float(l.split()[0]));nums=[float(x) for x in line.replace('(',' ').replace(')',' ').split()[2:]]
    out['minimum_absolute_pressure_Pa']=nums[0]
    out['minimum_pressure_location_m']=nums[1:4]
    out['yplus_spatial_review']=wall_yplus_geometry(case,yp)
    out['heated_maximum_location']=hottest_location(case,latest)
    pin=dict(data['inletPressure']);pout=dict(data['outletPressure']);ts=sorted(set(pin)&set(pout));dp=[pin[t][0]-pout[t][0] for t in ts if t>=ts[-1]-100]
    out['pressure_drop_drift_fraction']=(max(dp)-min(dp))/abs(dp[-1])
    out['energy_imbalance_without_inlet_diffusion_fraction']=abs(out['modeled_advected_energy_pickup_W']-last['heatedPower'])/last['heatedPower']
    residuals={}
    current_time=0;region=None
    for line in (case/'log.solver').read_text().splitlines():
        if line.startswith('Time = '):current_time=float(line.split('=')[1])
        if line.startswith('Solving for '):region=line.split()[-1]
        m=re.search(r'Solving for (\w+), Initial residual = ([^,]+), Final residual = ([^,]+)',line)
        if m and current_time>=float(latest.name)-100:
            key=str(region)+':'+m.group(1);residuals.setdefault(key,[]).append([float(m.group(2)),float(m.group(3))])
    qin=inlet_diffusion_aligned_hex(case,latest)
    out['inlet_diffusive_heat_into_fluid_W']=qin
    if qin is not None:out['energy_imbalance_with_inlet_diffusion_fraction']=abs(out['modeled_advected_energy_pickup_W']-last['heatedPower']-qin)/last['heatedPower']
    out['last100_residual_max']={k:{'initial':max(v[0] for v in vs),'linear_final':max(v[1] for v in vs)} for k,vs in residuals.items()}
    out['single_passage_flow_maldistribution']='not applicable: one connected bore; no parallel branches'
    out['energy_accounting_note']=('Inlet diffusive heat integrated using exact orthogonal extruded-hex inlet normal gradient; outlet diffusion is zeroGradient. ' if qin is not None else 'Inlet diffusive heat not integrated for this mesh. ')+'Liquid enthalpy model cpT excludes pressure-dependent enthalpy and viscous heating fidelity is limited.'
    (case/'summary.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('case',type=Path);a=p.parse_args();summarize(a.case)
