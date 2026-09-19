"""Build an OpenCFD v2412 two-region ``chtMultiRegionSimpleFoam`` case.

Inputs: a conformal MSH2 mesh with cell zones ``fluid``/``solid`` and patches
``inlet``, ``outlet``, ``heated``, ``outerWalls``; a material basis; and the
complete settings produced by :func:`src.cfd.settings.case_settings`.
"""
import argparse
import json
from pathlib import Path
import re
import shutil

from src.cfd.transport import fluid_dictionary, solid_dictionary
from src.cfd.turbulence import setup as turbulence_setup
from src.foam.dictionary import write_dictionary, write_field, vector_text
from src.foam.environment import run_tool, openfoam_version
from src.foam.hashing import digest

MONITORS = [
    ('inletPressure', 'fluid', 'inlet', 'areaAverage', 'p', ''),
    ('outletPressure', 'fluid', 'outlet', 'areaAverage', 'p', ''),
    ('inletMass', 'fluid', 'inlet', 'sum', 'phi', ''),
    ('outletMass', 'fluid', 'outlet', 'sum', 'phi', ''),
    ('inletTemperature', 'fluid', 'inlet', 'weightedAverage', 'T', 'weightField phi;'),
    ('outletTemperature', 'fluid', 'outlet', 'weightedAverage', 'T', 'weightField phi;'),
    ('heatedPower', 'solid', 'heated', 'areaIntegrate', 'wallHeatFlux', ''),
    ('interfacePower', 'solid', 'solid_to_fluid', 'areaIntegrate', 'wallHeatFlux', ''),
    ('fluidPower', 'fluid', 'fluid_to_solid', 'areaIntegrate', 'wallHeatFlux', ''),
    ('heatedMax', 'solid', 'heated', 'max', 'T', ''),
    ('wettedMax', 'fluid', 'fluid_to_solid', 'max', 'T', ''),
]


def control_dict(settings):
    functions = [
        'solidWallHeatFlux { type wallHeatFlux; libs (fieldFunctionObjects); region solid; writeControl timeStep; writeInterval 10; }',
        'fluidWallHeatFlux { type wallHeatFlux; libs (fieldFunctionObjects); region fluid; writeControl timeStep; writeInterval 10; }',
        'yPlus { type yPlus; libs (fieldFunctionObjects); region fluid; writeControl writeTime; }',
        'fluidTemperatureGradient { type grad; libs (fieldFunctionObjects); region fluid; field T; result gradT; '
        'executeControl timeStep; executeInterval 10; writeControl writeTime; }',
        f'fluidMinMax {{ type fieldMinMax; libs (fieldFunctionObjects); region fluid; fields (T p U); '
        f'executeControl timeStep; executeInterval {settings["field_minmax_interval"]}; '
        f'writeControl timeStep; writeInterval {settings["field_minmax_interval"]}; }}',
    ]
    for name, region, patch, operation, fields, extra in MONITORS:
        functions.append(f'{name} {{ type surfaceFieldValue; libs (fieldFunctionObjects); region {region}; '
                         f'regionType patch; name {patch}; operation {operation}; fields ({fields}); '
                         f'writeFields false; writeControl timeStep; writeInterval 10; {extra} }}')
    body = '\n    '.join(functions)
    return (f'application chtMultiRegionSimpleFoam;\nstartFrom latestTime; startTime 0; stopAt endTime; '
            f'endTime {settings["iterations"]}; deltaT 1;\nwriteControl timeStep; writeInterval {settings["write_interval"]}; '
            f'purgeWrite 2; writeFormat ascii; writePrecision 12; runTimeModifiable true;\n'
            f'functions\n{{\n    {body}\n}}')


def fluid_schemes(settings):
    return ('ddtSchemes { default steadyState; }\n'
            'gradSchemes { default Gauss linear; }\n'
            'divSchemes { default none; div(phi,U) bounded Gauss linearUpwind grad(U); div(phi,h) bounded Gauss upwind; '
            'div(phi,K) Gauss upwind; div(phi,k) bounded Gauss upwind; div(phi,epsilon) bounded Gauss upwind; '
            'div(phi,omega) bounded Gauss upwind; div(((rho*nuEff)*dev2(T(grad(U))))) Gauss linear; }\n'
            f'laplacianSchemes {{ default {settings["fluid_laplacian"]}; }}\n'
            'interpolationSchemes { default linear; }\n'
            'snGradSchemes { default limited 0.5; }\n'
            'fluxRequired { default no; p_rgh; }\n'
            'wallDist { method meshWave; }')


def fluid_solution(settings):
    return ('solvers {\n'
            'p_rgh { solver GAMG; tolerance 1e-9; relTol 0.01; smoother GaussSeidel; }\n'
            '"(U|h|k|epsilon|omega|rho)" { solver PBiCGStab; preconditioner DILU; tolerance 1e-9; relTol 0.01; }\n'
            '}\n'
            'SIMPLE { momentumPredictor yes; nNonOrthogonalCorrectors 1; }\n'
            f'relaxationFactors {{ fields {{ p_rgh {settings["pressure_relaxation"]}; rho 1; }} '
            f'equations {{ U {settings["velocity_relaxation"]}; h {settings["fluid_enthalpy_relaxation"]}; '
            'k 0.7; epsilon 0.7; omega 0.7; } }')


def solid_schemes(settings):
    return (f'ddtSchemes {{ default steadyState; }} gradSchemes {{ default {settings["solid_gradient"]}; }} '
            'divSchemes { default none; } laplacianSchemes { default Gauss linear corrected; } '
            'interpolationSchemes { default linear; } snGradSchemes { default corrected; }')


def solid_solution(settings):
    # relTol 0: a relative tolerance leaves the linear final residual near relTol x initial, failing
    # the linear-final gate. The initial-residual floor is a gradient-scheme matter (memory/cfd.md).
    return ('solvers { h { solver PCG; preconditioner DIC; tolerance 1e-10; relTol 0; } } '
            f'SIMPLE {{ nNonOrthogonalCorrectors {settings["solid_nonorthogonal_correctors"]}; }} '
            f'relaxationFactors {{ equations {{ h {settings["solid_enthalpy_relaxation"]}; }} }}')


def convert_mesh(case, mesh):
    """gmshToFoam then splitMeshRegions; root schemes must exist before splitting."""
    write_dictionary(case / 'system/fvSchemes',
                     'ddtSchemes { default steadyState; } gradSchemes { default Gauss linear; } divSchemes { default none; } '
                     'laplacianSchemes { default Gauss linear corrected; } interpolationSchemes { default linear; } '
                     'snGradSchemes { default corrected; }')
    write_dictionary(case / 'system/fvSolution', '')
    run_tool(['gmshToFoam', str(mesh), '-case', str(case)], case, case / 'log.gmshToFoam')
    run_tool(['splitMeshRegions', '-cellZones', '-overwrite', '-case', str(case)], case, case / 'log.splitMeshRegions')
    boundary = case / 'constant/solid/polyMesh/boundary'
    boundary.write_text(re.sub(r'type\s+patch;', 'type wall;', boundary.read_text()))


def build(case, mesh, basis, settings, geometry_manifest=None):
    case, mesh = Path(case).resolve(), Path(mesh).resolve()
    metadata_path = mesh.with_suffix('.json')
    metadata = json.loads(metadata_path.read_text())
    if metadata['mesh_sha256'] != digest(mesh):
        raise ValueError('Mesh hash differs from its metadata')
    if geometry_manifest is not None and metadata['geometry_manifest_sha256'] != digest(geometry_manifest):
        raise ValueError('Mesh does not belong to this geometry manifest')
    required = ['inlet_temperature_K', 'outlet_absolute_pressure_Pa', 'mass_flow_kg_s', 'heat_flux_W_m2',
                'inlet_area_m2', 'inlet_direction', 'hydraulic_diameter_m', 'iterations', 'turbulence_model',
                'turbulence_intensity', 'solid_gradient', 'solid_nonorthogonal_correctors', 'solid_enthalpy_relaxation',
                'fluid_enthalpy_relaxation', 'velocity_relaxation', 'pressure_relaxation', 'fluid_laplacian',
                'write_interval', 'field_minmax_interval']
    missing = [key for key in required if key not in settings]
    if missing:
        raise ValueError('Missing case settings: ' + ', '.join(missing))
    tin, pout, mdot, flux = (settings[k] for k in ('inlet_temperature_K', 'outlet_absolute_pressure_Pa', 'mass_flow_kg_s', 'heat_flux_W_m2'))
    fluid = basis['fluid_properties']
    rho = fluid['density_kg_m3']
    speed = mdot / (rho * settings['inlet_area_m2'])
    direction = settings['inlet_direction']
    turbulence = turbulence_setup(settings['turbulence_model'], speed, settings['turbulence_intensity'],
                                  .07 * settings['hydraulic_diameter_m'])
    fluid_thermo = fluid_dictionary(basis, tin)
    case.mkdir(parents=True, exist_ok=False)
    write_dictionary(case / 'system/controlDict', control_dict(settings))
    convert_mesh(case, mesh)
    write_dictionary(case / 'constant/regionProperties', 'regions (fluid (fluid) solid (solid));')
    write_dictionary(case / 'constant/g', 'dimensions [0 1 -2 0 0 0 0]; value (0 0 0);', 'uniformDimensionedVectorField')
    write_dictionary(case / 'constant/fluid/thermophysicalProperties', fluid_thermo)
    write_dictionary(case / 'constant/solid/thermophysicalProperties', solid_dictionary(basis))
    if turbulence['simulation_type'] == 'laminar':
        write_dictionary(case / 'constant/fluid/turbulenceProperties', 'simulationType laminar;')
    else:
        write_dictionary(case / 'constant/fluid/turbulenceProperties',
                         f'simulationType RAS; RAS {{ RASModel {turbulence["RASModel"]}; turbulence on; printCoeffs on; }}')
    for region in ('fluid', 'solid'):
        write_dictionary(case / f'constant/{region}/radiationProperties', 'radiation off; radiationModel none;')
    write_dictionary(case / 'system/fluid/fvSchemes', fluid_schemes(settings))
    write_dictionary(case / 'system/fluid/fvSolution', fluid_solution(settings))
    write_dictionary(case / 'system/solid/fvSchemes', solid_schemes(settings))
    write_dictionary(case / 'system/solid/fvSolution', solid_solution(settings))
    wall = 'fluid_to_solid'
    velocity = vector_text(speed * x for x in direction)
    coupled = lambda method: f'type compressible::turbulentTemperatureCoupledBaffleMixed; Tnbr T; kappaMethod {method}; value uniform {tin};'
    write_field(case, 'fluid', 'U', '[0 1 -1 0 0 0 0]', velocity, {
        'inlet': f'type flowRateInletVelocity; massFlowRate constant {mdot}; rho rho; rhoInlet {rho}; value uniform {velocity};',
        'outlet': 'type zeroGradient;', wall: 'type noSlip;'}, vector=True)
    write_field(case, 'fluid', 'p', '[1 -1 -2 0 0 0 0]', pout,
                {patch: f'type calculated; value uniform {pout};' for patch in ('inlet', 'outlet', wall)})
    write_field(case, 'fluid', 'p_rgh', '[1 -1 -2 0 0 0 0]', pout, {
        'inlet': 'type zeroGradient;', 'outlet': f'type fixedValue; value uniform {pout};',
        wall: f'type fixedFluxPressure; value uniform {pout};'})
    initial = settings.get('initial_temperature_K') or {}
    fluid_T0, solid_T0 = initial.get('fluid', tin), initial.get('solid', tin)
    write_field(case, 'fluid', 'T', '[0 0 0 1 0 0 0]', fluid_T0, {
        'inlet': f'type fixedValue; value uniform {tin};', 'outlet': 'type zeroGradient;', wall: coupled('fluidThermo')})
    for name, value, dimensions, wall_type in turbulence['fields']:
        transported = name in ('k', 'epsilon', 'omega')
        write_field(case, 'fluid', name, dimensions, value, {
            'inlet': f'type {"fixedValue" if transported else "calculated"}; value uniform {value};',
            'outlet': f'type {"zeroGradient" if transported else "calculated"}; value uniform {value};',
            wall: f'type {wall_type}; value uniform {value};'})
    write_field(case, 'solid', 'T', '[0 0 0 1 0 0 0]', solid_T0, {
        'heated': f'type externalWallHeatFluxTemperature; mode flux; q uniform {flux}; kappaMethod solidThermo; value uniform {tin};',
        'outerWalls': 'type zeroGradient;', 'solid_to_fluid': coupled('solidThermo')})
    write_field(case, 'solid', 'p', '[1 -1 -2 0 0 0 0]', pout,
                {patch: f'type calculated; value uniform {pout};' for patch in ('heated', 'outerWalls', 'solid_to_fluid')})
    if geometry_manifest is not None:
        shutil.copyfile(geometry_manifest, case / 'geometry-manifest.json')
    (case / 'basis.json').write_text(json.dumps(basis, indent=2) + '\n')
    settings = dict(settings, wall_model=turbulence['description'], inlet_speed_m_s=speed,
                    openfoam_version=openfoam_version(), transport_polynomials=basis.get('transport_polynomials'),
                    transport_model=basis.get('transport_model', 'constant'))
    (case / 'settings.json').write_text(json.dumps(settings, indent=2) + '\n')
    sources = {name: digest(Path(__file__).with_name(name)) for name in ('cht_case.py', 'transport.py', 'turbulence.py')}
    manifest = {'schema_version': 2, 'solver': settings['solver'], 'openfoam_version': settings['openfoam_version'],
                'input_sha256': {'mesh': digest(mesh), 'mesh_metadata': digest(metadata_path),
                                 'geometry_manifest': digest(geometry_manifest) if geometry_manifest else None,
                                 'basis': digest(case / 'basis.json'), 'settings': digest(case / 'settings.json')},
                'builder_sha256': sources, 'pressure_definition': 'p and p_rgh are absolute static pressure in Pa; g = 0',
                'simulation_executed': False, 'execution_status': 'not_started', 'numerically_verified': False}
    (case / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (case / 'case.foam').touch()
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case', type=Path)
    parser.add_argument('mesh', type=Path)
    parser.add_argument('--basis', type=Path, required=True, help='material basis JSON')
    parser.add_argument('--settings', type=Path, required=True, help='complete case settings JSON')
    parser.add_argument('--geometry', type=Path, help='geometry manifest to bind and copy into the case')
    args = parser.parse_args()
    build(args.case, args.mesh, json.loads(args.basis.read_text()), json.loads(args.settings.read_text()), args.geometry)
    print(json.dumps({'case': str(args.case), 'built': True}))


if __name__ == '__main__':
    main()
