"""Synthetic benchmark parts with independently known answers (no user review; runs carry the unapproved flag).

``smooth_tube_handoff`` writes a copper block with a straight round bore, heated on its top face, as an
unapproved handoff directory. Fully developed turbulent pipe flow is the best-measured flow there is:
friction from Nikuradse's smooth-pipe data and the Princeton Superpipe (Petukhov's fit, a few percent) and
heat transfer from the Petukhov and Kirillov data behind Gnielinski's correlation (10 to 15 percent). Those
are experiments, not this code, so ``src.verification.duct_benchmark`` compares a solved case against them.
"""
import json
import math
from pathlib import Path

from src.cad.step_preview import backend, preview_step
from src.foam.hashing import digest


def smooth_tube_handoff(destination, bore_mm=2.0, length_mm=100.0, block_mm=8.0, heat_flux_W_m2=1e6,
                        inlet_K=293.15, limit_K=473.15, outlet_Pa=800000.0, solid='copper', fluid='water'):
    """Block ``length_mm`` along x, ``block_mm`` square, bore of ``bore_mm`` on its axis, heated on the +z face."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    step = destination / 'source.step'
    gmsh = backend()
    gmsh.initialize()
    try:
        gmsh.option.setNumber('General.Terminal', 0)
        gmsh.option.setString('Geometry.OCCTargetUnit', 'MM')  # the extractor's 'M' setting survives finalize() in-process
        box = gmsh.model.occ.addBox(0, 0, 0, length_mm, block_mm, block_mm)
        bore = gmsh.model.occ.addCylinder(0, 0.5 * block_mm, 0.5 * block_mm, length_mm, 0, 0, 0.5 * bore_mm)
        gmsh.model.occ.cut([(3, box)], [(3, bore)])
        gmsh.model.occ.synchronize()
        if len(gmsh.model.getEntities(3)) != 1:
            raise ValueError('Tube block is not one solid')
        gmsh.write(str(step))
    finally:
        gmsh.finalize()
    model = preview_step(step, destination / 'model.json')
    ports = sorted(model['virtual_faces'], key=lambda v: v['centroid_mm'][0])
    if len(ports) != 2:
        raise ValueError(f'Expected two bore openings, found {len(ports)}')
    heated = max(model['faces'], key=lambda f: f['centroid_mm'][2])
    requirements = {'schema_version': 1, 'revision': 1, 'model_fingerprint': model['import_fingerprint'],
                    'selections': {'inlet': [ports[0]['id']], 'outlet': [ports[1]['id']], 'heated': [heated['id']]},
                    'requirements': {'solid_material': solid, 'coolant_material': fluid, 'inlet_temperature_K': inlet_K,
                                     'maximum_surface_temperature_K': limit_K,
                                     'heat_load': {'mode': 'heat_flux_W_m2', 'value': heat_flux_W_m2},
                                     'outlet_absolute_pressure_bounds_Pa': [outlet_Pa, outlet_Pa],
                                     'mass_flow_bounds_kg_s': [None, None], 'units_confirmed': True,
                                     'notes': 'SYNTHETIC BENCHMARK PART (smooth round tube); generated, not a user approval'}}
    (destination / 'requirements.json').write_text(json.dumps(requirements, indent=2) + '\n')
    record = {'benchmark': 'smooth_tube', 'units': 'mm', 'bore_mm': bore_mm, 'length_mm': length_mm, 'block_mm': block_mm,
              'length_over_diameter': length_mm / bore_mm, 'axis': 'x', 'heated_face': heated['id'],
              'heated_area_mm2': heated['area_mm2'], 'wetted_area_mm2': math.pi * bore_mm * length_mm,
              'source_sha256': digest(step), 'references': {
                  'friction': 'Petukhov fit of smooth-pipe data (Nikuradse; Superpipe), Darcy f = (0.79 ln Re - 1.64)^-2',
                  'heat_transfer': 'Gnielinski correlation of the Petukhov-Kirillov data set'}}
    (destination / 'benchmark.json').write_text(json.dumps(record, indent=2) + '\n')
    return destination


def volume_flow_for_reynolds(reynolds, bore_m, rho, mu):
    """Volume flow (m3/s) giving the Reynolds number in a round bore."""
    speed = reynolds * mu / (rho * bore_m)
    return speed * math.pi * (0.5 * bore_m) ** 2
