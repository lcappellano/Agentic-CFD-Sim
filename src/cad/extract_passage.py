"""Extract the coolant passage and solid region from an approved STEP handoff.

The user's approved port loops (circular openings found by ``step_preview``)
are capped with plane faces built from the actual CAD edges. An enclosing box
is fragmented with the solid and the caps; the fluid is the void that carries
every cap and never touches the enclosure. Ports may have any orientation and
position. Geometry is imported directly in metres and never modified.
"""
import argparse
import json
import math
from pathlib import Path

from src.cad.step_preview import backend
from src.foam.hashing import digest

MM = .001


def near(a, b, rel=1e-6, abs_tol=1e-10):
    return abs(a - b) <= max(abs_tol, rel * max(abs(a), abs(b)))


def surface_matches(gmsh, tag, record, abs_tol=1e-8):
    """True when an OCC surface has the recorded area and centroid (mm records)."""
    area_ok = near(gmsh.model.occ.getMass(2, tag), record['area_mm2'] * MM * MM)
    centre = gmsh.model.occ.getCenterOfMass(2, tag)
    return area_ok and all(near(x, y * MM, abs_tol=abs_tol) for x, y in zip(centre, record['centroid_mm']))


def boundary_tags(gmsh, volume):
    return {tag for _, tag in gmsh.model.getBoundary([(3, volume)], oriented=False)}


def shell_is_closed(gmsh, volume):
    counts = {}
    for _, face in gmsh.model.getBoundary([(3, volume)], oriented=True):
        for _, edge in gmsh.model.getBoundary([(2, abs(face))], oriented=True):
            counts[abs(edge)] = counts.get(abs(edge), 0) + (1 if face * edge > 0 else -1)
    return not any(counts.values())


def strictly_inside(inner, outer, tolerance):
    return all(inner[i] > outer[i] + tolerance and inner[i + 3] < outer[i + 3] - tolerance for i in range(3))


def load_handoff(handoff):
    handoff = Path(handoff).resolve()
    source = handoff / 'source.step'
    model = json.loads((handoff / 'model.json').read_text())
    requirements = json.loads((handoff / 'requirements.json').read_text())
    if model['source']['sha256'] != digest(source):
        raise ValueError('STEP hash changed since the approved import')
    if model.get('units') != 'mm':
        raise ValueError('Display model must be in millimetres')
    return handoff, source, model, requirements


def extract(handoff, output):
    handoff, source, model, requirements = load_handoff(handoff)
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('Use a new output directory')
    faces = {f['id']: f for f in model['faces']}
    ports = {f['id']: f for f in model['virtual_faces']}
    selections = requirements['selections']
    for role in ('inlet', 'outlet'):
        if not selections[role] or any(key not in ports for key in selections[role]):
            raise ValueError(f'{role} must select at least one candidate port opening')
    if not selections['heated'] or any(key not in faces for key in selections['heated']):
        raise ValueError('heated must select at least one CAD face')
    port_roles = {key: role for role in ('inlet', 'outlet') for key in selections[role]}
    gmsh = backend()
    gmsh.initialize()
    try:
        gmsh.option.setNumber('General.Terminal', 0)
        gmsh.option.setNumber('General.NumThreads', 1)
        gmsh.option.setString('Geometry.OCCTargetUnit', 'M')
        gmsh.model.add('extract')
        solids = gmsh.model.occ.importShapes(str(source))
        gmsh.model.occ.synchronize()
        if len(solids) != 1 or solids[0][0] != 3:
            raise ValueError(f'Exactly one solid is supported; found {solids}')
        solid = solids[0][1]
        for record in faces.values():
            if not surface_matches(gmsh, int(record['id'].split(':')[1]), record):
                raise ValueError('Approved face no longer matches the import: ' + record['id'])
        source_volume = gmsh.model.occ.getMass(3, solid)
        caps = {}
        for key in port_roles:
            loop = gmsh.model.occ.addCurveLoop(list(ports[key]['source_curve_tags']))
            caps[key] = gmsh.model.occ.addPlaneSurface([loop])
        bounds = gmsh.model.getBoundingBox(3, solid)
        diagonal = math.dist(bounds[:3], bounds[3:])
        pad = max(.005, .1 * diagonal)
        box = gmsh.model.occ.addBox(bounds[0] - pad, bounds[1] - pad, bounds[2] - pad,
                                    bounds[3] - bounds[0] + 2 * pad, bounds[4] - bounds[1] + 2 * pad,
                                    bounds[5] - bounds[2] + 2 * pad)
        gmsh.model.occ.fragment([(3, box)], [(3, solid)] + [(2, tag) for tag in caps.values()])
        gmsh.model.occ.synchronize()
        outer = gmsh.model.getBoundingBox(-1, -1)
        volumes = [tag for _, tag in gmsh.model.getEntities(3)]
        solid_tags = [tag for tag in volumes if near(gmsh.model.occ.getMass(3, tag), source_volume, rel=1e-9)]
        if len(solid_tags) != 1:
            raise ValueError('Could not identify the solid after fragmentation')
        solid = solid_tags[0]
        candidates = []
        for tag in volumes:
            if tag == solid:
                continue
            surfaces = boundary_tags(gmsh, tag)
            has_caps = all(any(surface_matches(gmsh, s, ports[key]) for s in surfaces) for key in port_roles)
            if has_caps and strictly_inside(gmsh.model.getBoundingBox(3, tag), outer, 1e-9):
                candidates.append(tag)
        if len(candidates) != 1:
            raise ValueError(f'Expected exactly one connected passage carrying all selected ports; found {len(candidates)}')
        fluid = candidates[0]
        gmsh.model.occ.remove([(3, tag) for tag in volumes if tag not in (solid, fluid)], recursive=True)
        gmsh.model.occ.synchronize()
        if not shell_is_closed(gmsh, fluid) or not shell_is_closed(gmsh, solid):
            raise ValueError('Extracted region is not a closed oriented shell')
        fluid_volume = gmsh.model.occ.getMass(3, fluid)
        output.mkdir(parents=True)
        gmsh.write(str(output / 'coupled.brep'))
        # Re-import so manifest tags match what a later Merge of coupled.brep sees.
        gmsh.model.add('coupled')
        gmsh.model.occ.importShapes(str(output / 'coupled.brep'))
        gmsh.model.occ.synchronize()
        volumes = [tag for _, tag in gmsh.model.getEntities(3)]
        if len(volumes) != 2:
            raise ValueError('Coupled geometry must contain exactly two regions')
        by_volume = {tag: gmsh.model.occ.getMass(3, tag) for tag in volumes}
        solid = min(by_volume, key=lambda t: abs(by_volume[t] - source_volume))
        fluid = next(t for t in volumes if t != solid)
        if not near(by_volume[solid], source_volume, rel=1e-9) or not near(by_volume[fluid], fluid_volume, rel=1e-9):
            raise ValueError('Region volumes changed on re-import')
        solid_faces, fluid_faces = boundary_tags(gmsh, solid), boundary_tags(gmsh, fluid)
        interface = solid_faces & fluid_faces
        if not interface:
            raise ValueError('No shared solid-fluid interface')
        groups = {'inlet': [], 'outlet': []}
        exposed = fluid_faces - interface
        for key, role in port_roles.items():
            found = [f for f in exposed if surface_matches(gmsh, f, ports[key])]
            if len(found) != 1:
                raise ValueError('Port cap identity ambiguous: ' + key)
            groups[role].append(found[0])
        if exposed != set(groups['inlet'] + groups['outlet']):
            raise ValueError('Fluid region has exposed faces beyond the selected ports')
        groups['heated'] = []
        for key in selections['heated']:
            found = [f for f in solid_faces - interface if surface_matches(gmsh, f, faces[key])]
            if len(found) != 1:
                raise ValueError('Heated face identity ambiguous: ' + key)
            groups['heated'].append(found[0])
        groups['outerWalls'] = sorted(solid_faces - interface - set(groups['heated']))
        groups['interface'] = sorted(interface)
        normals, diameters, port_records = {}, {}, {}
        for key, role in port_roles.items():
            record = ports[key]
            normal = list(record['normal'])
            face = groups[role][port_roles_index(port_roles, role, key)]
            centre = gmsh.model.occ.getCenterOfMass(2, face)
            probe = lambda sign: gmsh.model.isInside(3, fluid, [centre[i] + sign * normal[i] * 1e-6 for i in range(3)])
            inward, outward = probe(-1), probe(1)
            if inward == outward:
                raise ValueError('Cannot orient port normal for ' + key)
            if inward == 0:
                normal = [-v for v in normal]
            perimeter = sum(gmsh.model.occ.getMass(1, abs(e)) for _, e in gmsh.model.getBoundary([(2, face)], oriented=False))
            area = gmsh.model.occ.getMass(2, face)
            port_records.setdefault(role, []).append({'id': key, 'occ_surface_tag': face, 'area_m2': area,
                                                      'centroid_m': list(centre), 'outward_normal': normal,
                                                      'hydraulic_diameter_m': 4 * area / perimeter})
        for role in ('inlet', 'outlet'):
            normals[role] = port_records[role][0]['outward_normal']
            diameters[role] = port_records[role][0]['hydraulic_diameter_m']
        ligament = min(gmsh.model.occ.getDistance(2, heated_face, 2, wall)[0]
                       for heated_face in groups['heated'] for wall in interface)
        geo = ['SetFactory("OpenCASCADE");', 'Merge "coupled.brep";']
        for index, (name, tags) in enumerate(groups.items(), 1):
            geo.append(f'Physical Surface("{name}", {index}) = {{{", ".join(map(str, tags))}}};')
        for index, (name, tag) in enumerate([('fluid', fluid), ('solid', solid)], 101):
            geo.append(f'Physical Volume("{name}", {index}) = {{{tag}}};')
        (output / 'coupled.geo').write_text('\n'.join(geo) + '\n')
        for region, tag in (('solid', solid), ('fluid', fluid)):
            write_single_region(gmsh, output, region, tag, by_volume[tag])
        manifest = {
            'schema_version': 2,
            'source_sha256': digest(source), 'requirements_sha256': digest(handoff / 'requirements.json'),
            'adapter_sha256': digest(__file__),
            'backend': {'api': gmsh.__version__, 'runtime': gmsh.option.getString('General.Version')},
            'scope': 'one solid; ports are user-approved planar circular openings at any orientation',
            'units': 'm', 'coordinate_frame': 'original Cartesian axes and origin',
            'transform_from_source': {'uniform_scale': MM, 'translation': [0, 0, 0]},
            'geometry_changed': False,
            'regions': {name: {'material': requirements['requirements']['solid_material' if name == 'solid' else 'coolant_material'],
                               'volume_m3': by_volume[tag], 'occ_volume_tag': tag, 'file': name + '.brep'}
                        for name, tag in (('solid', solid), ('fluid', fluid))},
            'heated_area_m2': sum(gmsh.model.occ.getMass(2, t) for t in groups['heated']),
            'heated_to_passage_distance_m': ligament,
            'boundary_map': {name: {'occ_surface_tags': tags,
                                    'area_m2': sum(gmsh.model.occ.getMass(2, t) for t in tags),
                                    'centroids_m': [list(gmsh.model.occ.getCenterOfMass(2, t)) for t in tags]}
                             for name, tags in groups.items()},
            'ports': port_records,
            'port_outward_normals': normals,
            'port_hydraulic_diameter_m': diameters,
            'approved_identity_map': {key: role for role, keys in selections.items() for key in keys},
            'checks': {'positive_volumes': 'pass', 'fluid_connectivity': 'pass: one enclosed void carries every selected port',
                       'watertightness': 'pass: signed shell edge cancellation in both regions',
                       'interface': 'pass: shared OCC surfaces after conformal fragmentation',
                       'source_solid_volume_conservation': 'pass', 'original_face_identity': 'pass',
                       'heated_identity': 'pass', 'ports': 'pass: cap areas/centroids, exposed-face completeness, inside/outside probes',
                       'source_immutable': 'pass' if digest(source) == model['source']['sha256'] else 'fail'},
            'files': {},
        }
        manifest['files'] = {p.name: digest(p) for p in output.iterdir() if p.is_file()}
        (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        return manifest
    finally:
        gmsh.finalize()


def port_roles_index(port_roles, role, key):
    return [k for k, r in port_roles.items() if r == role].index(key)


def write_single_region(gmsh, output, region, keep_tag, expected_volume):
    """Write one region as its own BREP for independent audits and viewers."""
    gmsh.model.add('single_' + region)
    gmsh.model.occ.importShapes(str(output / 'coupled.brep'))
    gmsh.model.occ.synchronize()
    volumes = [tag for _, tag in gmsh.model.getEntities(3)]
    keep = min(volumes, key=lambda t: abs(gmsh.model.occ.getMass(3, t) - expected_volume))
    gmsh.model.occ.remove([(3, t) for t in volumes if t != keep], recursive=True)
    gmsh.model.occ.synchronize()
    gmsh.write(str(output / f'{region}.brep'))
    gmsh.model.setCurrent('coupled')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('handoff', help='approved handoff directory (source.step, model.json, requirements.json)')
    parser.add_argument('output')
    args = parser.parse_args()
    manifest = extract(args.handoff, args.output)
    print(json.dumps({'output': args.output, 'volumes_m3': {k: v['volume_m3'] for k, v in manifest['regions'].items()},
                      'heated_area_m2': manifest['heated_area_m2'],
                      'interface_faces': len(manifest['boundary_map']['interface']['occ_surface_tags'])}, indent=2))


if __name__ == '__main__':
    main()
