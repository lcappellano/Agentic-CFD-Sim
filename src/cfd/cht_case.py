"""Reusable two-region conformal-mesh OpenCFD v2412 CHT builder (SI).

Named patches: inlet, outlet, heated, outerWalls. Volume regions: fluid, solid.
All physical inputs must be explicit in a configuration JSON.
"""
import argparse,json,math,re,subprocess,hashlib
from pathlib import Path

def write(path,body,cls='dictionary',obj=None):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(f'FoamFile {{ version 2.0; format ascii; class {cls}; object {obj or path.name}; }}\n'+body+'\n')

def build(case,mesh,props,iterations,config):
    if props is None: raise ValueError('Explicit thermal estimates.json required')
    basis=json.loads(props.read_text())
    cfg=json.loads(config.read_text())
    required=['inlet_temperature_K','outlet_absolute_pressure_Pa','mass_flow_kg_s','heat_flux_W_m2','inlet_area_m2','inlet_direction','hydraulic_diameter_m','geometry_manifest']
    for key in required:
        if key not in cfg: raise ValueError('Missing case setting '+key)
    tin=cfg['inlet_temperature_K']; pout=cfg['outlet_absolute_pressure_Pa']; mdot=cfg['mass_flow_kg_s']; flux=cfg['heat_flux_W_m2']
    if min(tin,pout,mdot,flux,cfg['inlet_area_m2'],cfg['hydraulic_diameter_m'])<=0: raise ValueError('Case settings must be positive SI values')
    direction=cfg['inlet_direction']; norm=math.sqrt(sum(x*x for x in direction))
    if len(direction)!=3 or abs(norm-1)>1e-6: raise ValueError('inlet_direction must be unit vector pointing into fluid')
    case.mkdir(parents=True,exist_ok=False)
    (case/"adapter-cht_case.py").write_bytes(Path(__file__).read_bytes())
    write(case/'system/controlDict',f'''application chtMultiRegionSimpleFoam;
startFrom latestTime; startTime 0; stopAt endTime; endTime {iterations}; deltaT 1;
writeControl timeStep; writeInterval 100; purgeWrite 2; writeFormat ascii; writePrecision 12; runTimeModifiable true;
functions {{
    solidWallHeatFlux {{ type wallHeatFlux; libs (fieldFunctionObjects); region solid; writeControl timeStep; writeInterval 10; }}
    fluidWallHeatFlux {{ type wallHeatFlux; libs (fieldFunctionObjects); region fluid; writeControl timeStep; writeInterval 10; }}
    yPlus {{ type yPlus; libs (fieldFunctionObjects); region fluid; writeControl writeTime; }}
    fluidMinMax {{ type fieldMinMax; libs (fieldFunctionObjects); region fluid; fields (T p U); executeControl timeStep; executeInterval 20; writeControl timeStep; writeInterval 20; }}
'''+ '\n'.join(f'''{name} {{ type surfaceFieldValue; libs (fieldFunctionObjects); region {region}; regionType patch; name {patch}; operation {op}; fields ({fields}); writeFields false; writeControl timeStep; writeInterval 10; {extra} }}''' for name,region,patch,op,fields,extra in [
 ('inletPressure','fluid','inlet','areaAverage','p',''),('outletPressure','fluid','outlet','areaAverage','p',''),
 ('inletMass','fluid','inlet','sum','phi',''),('outletMass','fluid','outlet','sum','phi',''),
 ('inletTemperature','fluid','inlet','weightedAverage','T','weightField phi;'),('outletTemperature','fluid','outlet','weightedAverage','T','weightField phi;'),
 ('heatedPower','solid','heated','areaIntegrate','wallHeatFlux',''),('interfacePower','solid','solid_to_fluid','areaIntegrate','wallHeatFlux',''),('fluidPower','fluid','fluid_to_solid','areaIntegrate','wallHeatFlux',''),
 ('heatedMax','solid','heated','max','T',''),('wettedMax','fluid','fluid_to_solid','max','T','')])+ '\n}\n')
    write(case/'system/fvSchemes','ddtSchemes { default steadyState; } gradSchemes { default Gauss linear; } divSchemes { default none; } laplacianSchemes { default Gauss linear corrected; } interpolationSchemes { default linear; } snGradSchemes { default corrected; }')
    write(case/'system/fvSolution','')
    for cmd in [['gmshToFoam',str(mesh.resolve())],['splitMeshRegions','-cellZones','-overwrite']]:
        with (case/('log.'+cmd[0])).open('w') as log: subprocess.run(cmd+['-case',str(case.resolve())],stdout=log,stderr=subprocess.STDOUT,check=True)
    boundary=case/'constant/solid/polyMesh/boundary'
    boundary.write_text(re.sub(r'type\s+patch;', 'type wall;', boundary.read_text()))
    write(case/'constant/regionProperties','regions (fluid (fluid) solid (solid));')
    write(case/'constant/g','dimensions [0 1 -2 0 0 0 0]; value (0 0 0);','uniformDimensionedVectorField')
    wp=basis['water_properties']
    rho,cp,mu,kappa=[wp[k] for k in ['density_kg_m3','cp_J_kg_K','dynamic_viscosity_Pa_s','conductivity_W_m_K']]
    # These are explicit baseline constants; property provenance is in thermal report.
    write(case/'constant/fluid/thermophysicalProperties',f'''thermoType {{ type heRhoThermo; mixture pureMixture; transport const; thermo hConst; equationOfState rhoConst; specie specie; energy sensibleEnthalpy; }}
mixture {{ specie {{ molWeight 18.015; }} equationOfState {{ rho {rho}; }} thermodynamics {{ Cp {cp}; Hf 0; }} transport {{ mu {mu}; Pr {mu*cp/kappa}; }} }}''')
    copper=basis['copper_properties']
    write(case/'constant/solid/thermophysicalProperties',f"""thermoType {{ type heSolidThermo; mixture pureMixture; transport constIso; thermo hConst; equationOfState rhoConst; specie specie; energy sensibleEnthalpy; }}
mixture {{ specie {{ molWeight 63.546; }} equationOfState {{ rho {copper['density_kg_m3']}; }} thermodynamics {{ Cp {copper['cp_J_kg_K']}; Hf 0; }} transport {{ kappa {copper['conductivity_W_m_K']}; }} }}""")
    write(case/'constant/fluid/turbulenceProperties','simulationType RAS; RAS { RASModel kEpsilon; turbulence on; printCoeffs on; }')
    for region in ['fluid','solid']:
        write(case/f'constant/{region}/radiationProperties','radiation off; radiationModel none;')
        write(case/f'system/{region}/fvSchemes','''ddtSchemes { default steadyState; }
gradSchemes { default Gauss linear; }
divSchemes { default none; div(phi,U) bounded Gauss linearUpwind grad(U); div(phi,h) bounded Gauss upwind; div(phi,K) Gauss upwind; div(phi,k) bounded Gauss upwind; div(phi,epsilon) bounded Gauss upwind; div(((rho*nuEff)*dev2(T(grad(U))))) Gauss linear; }
laplacianSchemes { default Gauss linear limited 0.5; }
interpolationSchemes { default linear; }
snGradSchemes { default limited 0.5; }
fluxRequired { default no; p_rgh; }''')
        write(case/f'system/{region}/fvSolution','''solvers {
p_rgh { solver GAMG; tolerance 1e-9; relTol 0.01; smoother GaussSeidel; }
"(U|h|k|epsilon|rho)" { solver PBiCGStab; preconditioner DILU; tolerance 1e-9; relTol 0.01; }
}
SIMPLE { momentumPredictor yes; nNonOrthogonalCorrectors 1; }
relaxationFactors { fields { p_rgh 0.3; rho 1; } equations { U 0.7; h 0.9; k 0.7; epsilon 0.7; } }''')
    write(case/'system/solid/fvSchemes','ddtSchemes { default steadyState; } gradSchemes { default leastSquares; } divSchemes { default none; } laplacianSchemes { default Gauss linear corrected; } interpolationSchemes { default linear; } snGradSchemes { default corrected; }')
    write(case/'system/solid/fvSolution', 'solvers { h { solver PCG; preconditioner DIC; tolerance 1e-10; relTol 0.001; } } SIMPLE { nNonOrthogonalCorrectors 3; } relaxationFactors { equations { h 0.9; } }')
    def field(region,name,dim,value,bcs,vector=False):
        write(case/f'0/{region}/{name}',f'dimensions {dim};\ninternalField uniform {value};\nboundaryField {{\n'+ '\n'.join(f'{p} {{ {b} }}' for p,b in bcs.items())+'\n}', 'volVectorField' if vector else 'volScalarField')
    coupled=lambda method:f'type compressible::turbulentTemperatureCoupledBaffleMixed; Tnbr T; kappaMethod {method}; value uniform {tin};'
    # Names created by splitMeshRegions are mappedWall and retain reciprocal region information.
    wall='fluid_to_solid'; uwall='type noSlip;'
    speed=mdot/(rho*cfg['inlet_area_m2']); kval=1.5*(speed*cfg.get('turbulence_intensity',.05))**2; length=.07*cfg['hydraulic_diameter_m']; eps=.09**.75*kval**1.5/length
    velocity='('+ ' '.join(str(speed*x) for x in direction)+')'
    field('fluid','U','[0 1 -1 0 0 0 0]',velocity,{'inlet':f'type flowRateInletVelocity; massFlowRate constant {mdot}; rho rho; rhoInlet {rho}; value uniform {velocity};','outlet':'type zeroGradient;',wall:uwall},True)
    for name in ['p','p_rgh']:
        field('fluid',name,'[1 -1 -2 0 0 0 0]',pout,{'inlet':'type zeroGradient;' if name=='p_rgh' else f'type calculated; value uniform {pout};','outlet':f'type fixedValue; value uniform {pout};' if name=='p_rgh' else f'type calculated; value uniform {pout};',wall:f'type fixedFluxPressure; value uniform {pout};' if name=='p_rgh' else f'type calculated; value uniform {pout};'})
    field('fluid','T','[0 0 0 1 0 0 0]',tin,{'inlet':f'type fixedValue; value uniform {tin};','outlet':'type zeroGradient;',wall:coupled('fluidThermo')})
    for name,value,dim,walltype in [('k',kval,'[0 2 -2 0 0 0 0]','kqRWallFunction'),('epsilon',eps,'[0 2 -3 0 0 0 0]','epsilonWallFunction'),('nut',0,'[0 2 -1 0 0 0 0]','nutkWallFunction'),('alphat',0,'[1 -1 -1 0 0 0 0]','compressible::alphatJayatillekeWallFunction')]:
        field('fluid',name,dim,value,{'inlet':f'type {"fixedValue" if name in ("k","epsilon") else "calculated"}; value uniform {value};','outlet':f'type {"zeroGradient" if name in ("k","epsilon") else "calculated"}; value uniform {value};',wall:f'type {walltype}; value uniform {value};'})
    field('solid','T','[0 0 0 1 0 0 0]',tin,{'heated':f'type externalWallHeatFluxTemperature; mode flux; q uniform {flux}; kappaMethod solidThermo; value uniform {tin};','outerWalls':'type zeroGradient;','solid_to_fluid':coupled('solidThermo')})
    field('solid','p','[1 -1 -2 0 0 0 0]',pout,{p:f'type calculated; value uniform {pout};' for p in ['heated','outerWalls','solid_to_fluid']})
    inputs=[mesh,props,config,Path(__file__),Path(cfg['geometry_manifest'])]
    hashes={str(p.resolve()):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    (case/'manifest.json').write_text(json.dumps({'input_sha256':hashes,'solver':'OpenCFD v2412 patch260127 chtMultiRegionSimpleFoam','geometry_changed':False,'pressure_definition':'p and p_rgh in absolute Pa; g=0','configuration':cfg,'limitations':['Constant properties liquid enthalpy cpT model; single phase only','Uniform inlet; no external fittings or reservoir','RANS wall functions require near-wall review','No experimental validation'],'simulation_executed':False,'numerically_verified':False},indent=2))
    (case/'case.foam').touch()
    settings=dict(cfg,solver='OpenCFD v2412 chtMultiRegionSimpleFoam',rho_kg_m3=rho,cp_J_kg_K=cp,mu_Pa_s=mu,k_W_m_K=kappa,gravity_m_s2=[0,0,0],thermal_property_input=str(props),turbulence_length_scale_m=length,wall_model='standard kEpsilon + Jayatilleke thermal wall function',iterations=iterations)
    (case/'baseline-settings.json').write_text(json.dumps(settings,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('case',type=Path);p.add_argument('mesh',type=Path);p.add_argument('--properties',type=Path,required=True);p.add_argument('--config',type=Path,required=True);p.add_argument('--iterations',type=int,default=1500);a=p.parse_args();build(a.case,a.mesh,a.properties,a.iterations,a.config)
