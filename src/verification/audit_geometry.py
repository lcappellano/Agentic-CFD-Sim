"""Independent audit of an extracted geometry against its approved handoff.

Re-imports the region BREPs with OCC (read-only), checks volumes, closed
shells, conformal interface, approved face identities and cap orientation.
"""
import argparse
from collections import Counter
import json
import math
from pathlib import Path

from src.cad.step_preview import backend
from src.foam.hashing import digest, content_hash


def audit(handoff, geometry):
    handoff, geometry = Path(handoff).resolve(), Path(geometry).resolve()
    checks, hashes = [], {}

    def read(path):
        hashes[str(path)] = digest(path)
        return json.loads(path.read_text())

    def check(name, ok, evidence):
        checks.append({'check': name, 'status': 'pass' if ok else 'fail', 'evidence': evidence})

    requirements = read(handoff / 'requirements.json')
    model = read(handoff / 'model.json')
    manifest = read(geometry / 'manifest.json')
    hashes[str(handoff / 'source.step')] = digest(handoff / 'source.step')
    check('source_snapshot', hashes[str(handoff / 'source.step')] == model['source']['sha256'] == manifest['source_sha256'],
          manifest['source_sha256'])
    if (handoff / 'approval.json').is_file():
        approval = read(handoff / 'approval.json')
        check('approved_receipt_binding', approval.get('confirmed') is True
              and approval['draft_sha256'] == content_hash(requirements)
              and requirements['model_fingerprint'] == model['import_fingerprint'], approval)
    else:
        checks.append({'check': 'approved_receipt_binding', 'status': 'not checked', 'evidence': 'No approval.json (synthetic handoff)'})
    check('geometry_requirement_binding', manifest['requirements_sha256'] == hashes[str(handoff / 'requirements.json')],
          manifest['requirements_sha256'])
    for name, expected in manifest['files'].items():
        hashes[str(geometry / name)] = digest(geometry / name)
        check('geometry_file:' + name, hashes[str(geometry / name)] == expected, expected)
    sources = {x['id']: x for x in model['faces'] + model.get('virtual_faces', [])}
    expected_map = {key: role for role, keys in requirements['selections'].items() for key in keys}
    check('boundary_identity_map', manifest['approved_identity_map'] == expected_map, expected_map)
    check('metre_conversion', model['units'] == 'mm' and manifest['units'] == 'm'
          and manifest['transform_from_source'] == {'uniform_scale': .001, 'translation': [0, 0, 0]},
          manifest['transform_from_source'])
    check('fixed_geometry', manifest['geometry_changed'] is False, manifest['geometry_changed'])
    for role, keys in requirements['selections'].items():
        actual = manifest['boundary_map'][role]
        area = sum(sources[k]['area_mm2'] for k in keys) * 1e-6
        wanted = sorted([[v * .001 for v in sources[k]['centroid_mm']] for k in keys])
        found = sorted(actual['centroids_m'])
        check('approved_area:' + role, math.isclose(area, actual['area_m2'], rel_tol=1e-6, abs_tol=1e-12),
              {'approved_area_m2': area, 'geometry_area_m2': actual['area_m2']})
        check('approved_centroid:' + role, len(wanted) == len(found)
              and all(math.dist(a, b) <= 1e-8 for a, b in zip(wanted, found)),
              {'approved_centroids_m': wanted, 'geometry_centroids_m': found})
    gmsh = backend()
    gmsh.initialize()
    evidence = {}
    try:
        gmsh.option.setNumber('General.Terminal', 0)
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
            signed = Counter()
            surfaces = gmsh.model.getBoundary(volumes, oriented=True)
            for _, surface in surfaces:
                for _, edge in gmsh.model.getBoundary([(2, abs(surface))], oriented=True):
                    signed[abs(edge)] += 1 if surface * edge > 0 else -1
            remaining = {e: c for e, c in signed.items() if c}
            check(region + ':closed_oriented_shell', not remaining, {'surface_count': len(surfaces), 'unbalanced_edges': remaining})
            evidence[region] = {'volume_m3': volume, 'surface_count': len(surfaces)}
            if region == 'fluid':
                for role in ('inlet', 'outlet'):
                    centre = manifest['boundary_map'][role]['centroids_m'][0]
                    n = manifest['port_outward_normals'][role]
                    probes = [gmsh.model.isInside(3, volumes[0][1], [centre[j] + s * 1e-6 * n[j] for j in range(3)]) for s in (-1, 1)]
                    check('cap_direction:' + role, probes == [1, 0], {'inside_then_outside': probes})
        gmsh.model.add('audit_coupled')
        gmsh.model.occ.importShapes(str(geometry / 'coupled.brep'))
        gmsh.model.occ.synchronize()
        regions = gmsh.model.getEntities(3)
        check('coupled_two_regions', len(regions) == 2, regions)
        if len(regions) == 2:
            boundaries = [{t for _, t in gmsh.model.getBoundary([r], oriented=False)} for r in regions]
            common = boundaries[0] & boundaries[1]
            area = sum(gmsh.model.occ.getMass(2, f) for f in common)
            expected = manifest['boundary_map']['interface']['area_m2']
            check('shared_conformal_interface', bool(common) and math.isclose(area, expected, rel_tol=1e-8),
                  {'surface_count': len(common), 'area_m2': area, 'manifest_area_m2': expected})
    finally:
        gmsh.finalize()
    for path, before in list(hashes.items()):
        check('input_unchanged:' + Path(path).name, digest(path) == before, before)
    return {'scope': 'independent geometry audit', 'backend_version': version, 'checks': checks, 'geometry': evidence,
            'heated_area_m2': manifest['heated_area_m2'], 'input_sha256': hashes,
            'geometry_checks_pass': not any(c['status'] == 'fail' for c in checks)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('handoff', type=Path)
    parser.add_argument('--geometry', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.handoff, args.geometry)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'geometry_checks_pass': result['geometry_checks_pass'],
                      'failed_checks': [c for c in result['checks'] if c['status'] != 'pass']}, indent=2))


if __name__ == '__main__':
    main()
