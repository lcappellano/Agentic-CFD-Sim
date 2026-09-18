"""Independent manifold receipt/region audit; no meshing or solver execution.

Use the project venv through the recorded job runner. OCC is read-only in this
audit; generated BREP files and source STEP are never rewritten.
"""
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def content_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def audit(run, geometry):
    run, geometry = Path(run).resolve(), Path(geometry).resolve()
    checks, hashes = [], {}
    def read(path):
        hashes[str(path)] = digest(path)
        return json.loads(path.read_text())
    def check(name, result, evidence):
        checks.append({'check': name, 'status': 'pass' if result else 'fail', 'evidence': evidence})
    receipt = run / 'requirements_review'
    approval = read(receipt / 'approval.json')
    requirements = read(receipt / 'requirements.json')
    model = read(receipt / 'model.json')
    manifest = read(geometry / 'manifest.json')
    project = read(run / 'resolved-project.json')
    overrides = read(run / 'user-overrides.json')
    for path in (receipt / 'source.step', run / 'inputs/source.step'):
        hashes[str(path)] = digest(path)
        check('source_snapshot:' + str(path.relative_to(run)),
              hashes[str(path)] == approval['source_sha256'] == manifest['source_sha256'], hashes[str(path)])
    check('approved_receipt_binding', approval.get('confirmed') is True
          and approval['draft_sha256'] == content_hash(requirements)
          and approval['model_sha256'] == hashes[str(receipt / 'model.json')]
          and requirements['model_fingerprint'] == model['import_fingerprint']
          and approval['revision'] == requirements['revision'], approval)
    check('geometry_requirement_binding', manifest['requirements_sha256'] == hashes[str(receipt / 'requirements.json')],
          manifest['requirements_sha256'])
    for name, expected in manifest['files'].items():
        path = geometry / name
        hashes[str(path)] = digest(path)
        check('geometry_file:' + name, hashes[str(path)] == expected, hashes[str(path)])
    source_faces = {x['id']: x for x in model['faces'] + model.get('virtual_faces', [])}
    expected_map = {identity: role for role, identities in requirements['selections'].items() for identity in identities}
    check('boundary_identity_map', manifest['approved_identity_map'] == expected_map, expected_map)
    check('metre_conversion', model['units'] == 'mm' and manifest['units'] == 'm'
          and manifest['transform_from_source'] == {'uniform_scale': .001, 'translation': [0, 0, 0]},
          manifest['transform_from_source'])
    check('fixed_geometry', project['geometry_changes_allowed'] is False and manifest['geometry_changed'] is False,
          {'project_geometry_changes_allowed': project['geometry_changes_allowed'],
           'manifest_geometry_changed': manifest['geometry_changed']})
    for role, identities in requirements['selections'].items():
        actual = manifest['boundary_map'][role]
        area = sum(source_faces[x]['area_mm2'] for x in identities) * 1e-6
        wanted = sorted([[v * .001 for v in source_faces[x]['centroid_mm']] for x in identities])
        found = sorted(actual['centroids_m'])
        check('approved_area:' + role, math.isclose(area, actual['area_m2'], rel_tol=1e-6, abs_tol=1e-12),
              {'approved_area_m2': area, 'geometry_area_m2': actual['area_m2']})
        check('approved_centroid:' + role, len(wanted) == len(found)
              and all(math.dist(a, b) <= 1e-8 for a, b in zip(wanted, found)),
              {'approved_centroids_m': wanted, 'geometry_centroids_m': found})
    heat_W = manifest['heated_area_m2'] * project['heat_flux_W_m2']
    check('one_approved_heated_face', project['heated_faces'] == requirements['selections']['heated']
          and len(project['heated_faces']) == 1, {'selection': project['heated_faces'], 'power_W': heat_W})
    check('explicit_chat_overrides', overrides['source_geometry_and_selection_unchanged'] is True
          and project['volume_flow_bounds_L_min'] == [1, 50]
          and project['mass_flow_bounds_kg_s'] != [1, 50]
          and 'radiation neglected' in project['other_thermal_boundaries'].lower(),
          {'overrides': overrides, 'resolved_other_thermal_boundaries': project['other_thermal_boundaries'],
           'mass_conversion': 'Deferred to sourced inlet density/case settings; archived kg/s entry is not reused.'})

    wrapper = ROOT / 'src/cad/vendor/gmsh.py'
    spec = importlib.util.spec_from_file_location('independent_occ_backend', wrapper)
    gmsh = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gmsh)
    hashes[str(wrapper)] = digest(wrapper)
    gmsh.initialize()
    geometry_evidence = {}
    try:
        gmsh.option.setNumber('General.NumThreads', 1)
        version = gmsh.option.getString('General.Version')
        for region in ('solid', 'fluid'):
            gmsh.model.add('audit_' + region)
            gmsh.model.occ.importShapes(str(geometry / manifest['regions'][region]['file']))
            gmsh.model.occ.synchronize()
            volumes = gmsh.model.getEntities(3)
            check(region + ':single_occ_volume', len(volumes) == 1, volumes)
            if len(volumes) != 1:
                continue
            volume = gmsh.model.occ.getMass(3, volumes[0][1])
            check(region + ':volume', volume > 0 and math.isclose(volume, manifest['regions'][region]['volume_m3'], rel_tol=1e-8),
                  {'reimported_m3': volume, 'manifest_m3': manifest['regions'][region]['volume_m3']})
            signed_edges = Counter()
            surfaces = gmsh.model.getBoundary(volumes, oriented=True)
            for _, surface in surfaces:
                for _, edge in gmsh.model.getBoundary([(2, abs(surface))], oriented=True):
                    signed_edges[abs(edge)] += 1 if surface * edge > 0 else -1
            remaining = {edge: count for edge, count in signed_edges.items() if count}
            check(region + ':closed_oriented_shell', not remaining,
                  {'surface_count': len(surfaces), 'edge_count': len(signed_edges), 'unbalanced_edges': remaining})
            geometry_evidence[region] = {'volume_m3': volume, 'surface_count': len(surfaces)}
            if region == 'fluid':
                for role in ('inlet', 'outlet'):
                    boundary = manifest['boundary_map'][role]
                    centre = boundary['centroids_m'][0]
                    n = manifest['port_outward_normals'][role]
                    inside = [centre[j] - 1e-6 * n[j] for j in range(3)]
                    outside = [centre[j] + 1e-6 * n[j] for j in range(3)]
                    probes = [gmsh.model.isInside(3, volumes[0][1], x) for x in (inside, outside)]
                    check('cap_direction:' + role, probes == [1, 0],
                          {'inward_probe': inside, 'outward_probe': outside, 'inside_results': probes})
        gmsh.model.add('audit_coupled')
        gmsh.model.occ.importShapes(str(geometry / 'coupled.brep'))
        gmsh.model.occ.synchronize()
        regions = gmsh.model.getEntities(3)
        check('coupled_two_regions', len(regions) == 2, regions)
        if len(regions) == 2:
            boundaries = [set(t for _, t in gmsh.model.getBoundary([region], oriented=False)) for region in regions]
            common = boundaries[0] & boundaries[1]
            area = sum(gmsh.model.occ.getMass(2, face) for face in common)
            expected = manifest['boundary_map']['interface']['area_m2']
            check('shared_conformal_interface', bool(common) and math.isclose(area, expected, rel_tol=1e-8),
                  {'surface_count': len(common), 'area_m2': area, 'manifest_area_m2': expected})
    finally:
        gmsh.finalize()
    for path, before in list(hashes.items()):
        check('input_unchanged:' + path, digest(path) == before, before)
    return {'scope': 'Independent identity, SI conversion and OCC region audit; not CFD validation',
            'backend_version': version, 'checks': checks, 'geometry': geometry_evidence,
            'heated_area_m2': manifest['heated_area_m2'], 'applied_heat_W': heat_W,
            'input_sha256': hashes, 'geometry_checks_pass': all(c['status'] == 'pass' for c in checks),
            'simulation_ready': False,
            'pending': ['mesh resolution and quality', 'material/phase/turbulence validity',
                        'conservation and convergence', 'mesh sensitivity', 'experimental validation']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--geometry', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.run, args.geometry)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'geometry_checks_pass': result['geometry_checks_pass'],
                      'applied_heat_W': result['applied_heat_W'],
                      'failed_checks': [c for c in result['checks'] if c['status'] != 'pass']}, indent=2))
