"""Reproducible fixed-demo OpenCFD v2412 CHT case builder (SI)."""
import argparse,json,math,re,subprocess,hashlib
from pathlib import Path

def write(path,body,cls='dictionary',obj=None):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(f'FoamFile {{ version 2.0; format ascii; class {cls}; object {obj or path.name}; }}\n'+body+'\n')

def build(case,mesh,props,iterations):
    if props is None: raise ValueError('Explicit thermal estimates.json required')
    basis=json.loads(props.read_text())
    case.mkdir(parents=True,exist_ok=False)
    (case/"adapter-demo_case.py").write_bytes(Path(__file__).read_bytes())
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
    write(case/'constant/solid/thermophysicalProperties','''thermoType { type heSolidThermo; mixture pureMixture; transport constIso; thermo hConst; equationOfState rhoConst; specie specie; energy sensibleEnthalpy; }
mixture { specie { molWeight 63.546; } equationOfState { rho 8920; } thermodynamics { Cp 394; Hf 0; } transport { kappa 394; } }''')
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
    coupled=lambda method:f'type compressible::turbulentTemperatureCoupledBaffleMixed; Tnbr T; kappaMethod {method}; value uniform 300;'
    # Names created by splitMeshRegions are mappedWall and retain reciprocal region information.
    wall='fluid_to_solid'; uwall='type noSlip;'
    speed=.5/(rho*math.pi*.004**2); kval=1.5*(speed*.05)**2; eps=.09**.75*kval**1.5/(.07*.008)
    field('fluid','U','[0 1 -1 0 0 0 0]',f'({speed} 0 0)',{'inlet':'type flowRateInletVelocity; massFlowRate constant 0.5; rho rho; rhoInlet 997.047013; value uniform ('+str(speed)+' 0 0);','outlet':'type zeroGradient;',wall:uwall},True)
    for name in ['p','p_rgh']:
        field('fluid',name,'[1 -1 -2 0 0 0 0]',111325,{'inlet':'type zeroGradient;' if name=='p_rgh' else 'type calculated; value uniform 111325;','outlet':'type fixedValue; value uniform 111325;' if name=='p_rgh' else 'type calculated; value uniform 111325;',wall:'type fixedFluxPressure; value uniform 111325;' if name=='p_rgh' else 'type calculated; value uniform 111325;'})
    field('fluid','T','[0 0 0 1 0 0 0]',300,{'inlet':'type fixedValue; value uniform 300;','outlet':'type zeroGradient;',wall:coupled('fluidThermo')})
    for name,value,dim,walltype in [('k',kval,'[0 2 -2 0 0 0 0]','kqRWallFunction'),('epsilon',eps,'[0 2 -3 0 0 0 0]','epsilonWallFunction'),('nut',0,'[0 2 -1 0 0 0 0]','nutkWallFunction'),('alphat',0,'[1 -1 -1 0 0 0 0]','compressible::alphatJayatillekeWallFunction')]:
        field('fluid',name,dim,value,{'inlet':f'type {"fixedValue" if name in ("k","epsilon") else "calculated"}; value uniform {value};','outlet':f'type {"zeroGradient" if name in ("k","epsilon") else "calculated"}; value uniform {value};',wall:f'type {walltype}; value uniform {value};'})
    field('solid','T','[0 0 0 1 0 0 0]',300,{'heated':'type externalWallHeatFluxTemperature; mode flux; q uniform 100000; kappaMethod solidThermo; value uniform 300;','outerWalls':'type zeroGradient;','solid_to_fluid':coupled('solidThermo')})
    field('solid','p','[1 -1 -2 0 0 0 0]',111325,{p:'type calculated; value uniform 111325;' for p in ['heated','outerWalls','solid_to_fluid']})
    inputs=[mesh,props,Path(__file__),mesh.with_suffix('.json'),case.parent/'geometry/v3/manifest.json',case.parent/'requirements_review/requirements.json']
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    (case/'manifest.json').write_text(json.dumps({'input_sha256':hashes,'solver':'OpenCFD v2412 patch260127 chtMultiRegionSimpleFoam','geometry_changed':False,'pressure_definition':'p and p_rgh in absolute Pa; g=0','thermal_boundary':'100000W/m2 into heated solid; all other exterior surfaces adiabatic','inlet':'uniform mass flow 0.5kg/s, T300K; turbulence intensity5%, length .07D','limitations':['Constant properties incompressible liquid enthalpy cpT model','Uniform inlet developing flow; no external fittings or reservoir','RANS wall functions; no experimental validation'],'simulation_executed':False},indent=2))
    (case/'case.foam').touch()
    (case/'baseline-settings.json').write_text(json.dumps({'solver':'OpenCFD v2412 chtMultiRegionSimpleFoam','rho_kg_m3':rho,'cp_J_kg_K':cp,'mu_Pa_s':mu,'k_W_m_K':kappa,'mass_flow_kg_s':.5,'outlet_absolute_pressure_Pa':111325,'gravity_m_s2':[0,0,0],'inlet_turbulence_intensity':.05,'thermal_property_input':str(props),'turbulence_length_scale_m':.00056,'heat_flux_W_m2':100000,'wall_model':'standard kEpsilon velocity wall functions + Jayatilleke thermal wall function Prt0.85','iterations':iterations},indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('case',type=Path);p.add_argument('mesh',type=Path);p.add_argument('--properties',type=Path);p.add_argument('--iterations',type=int,default=1500);a=p.parse_args();build(a.case,a.mesh,a.properties,a.iterations)
