"""Conformal tetrahedral mesh of an extracted geometry with reusable size fields.

Settings come from a mesh profile (see ``src/pipeline/profiles/mesh.json``)
resolved by the pipeline, or from explicit CLI sizes. Sizes are SI edge targets;
achieved wall distance and y+ are checked from the solved case, not here.
"""
import argparse
import json
import math
from pathlib import Path

from src.cad.step_preview import backend
from src.foam.hashing import digest

DEFAULTS = {'wall_size_m': None, 'bulk_size_m': None, 'transition_distance_m': None,
            'curvature_points': 24, 'refinement_boxes': [], 'keep_interface_group': False}


def validate_boxes(boxes):
    if not isinstance(boxes, list):
        raise ValueError('refinement_boxes must be a list')
    for box in boxes:
        if not isinstance(box, dict) or set(box) - {'name', 'bounds_m', 'size_m', 'transition_m'}:
            raise ValueError('Unknown refinement box keys')
        bounds = box.get('bounds_m', [])
        if len(bounds) != 6 or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in bounds):
            raise ValueError('Box bounds require six finite SI numbers')
        if any(bounds[i] >= bounds[i + 3] for i in range(3)):
            raise ValueError('Box bounds must have positive extent')
        for key, default in (('size_m', None), ('transition_m', 0)):
            value = box.get(key, default)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) \
                    or (value <= 0 if key == 'size_m' else value < 0):
                raise ValueError('Invalid box ' + key)
    return boxes


def resolve_sizes(profile, diameter_m, overrides=None):
    """Turn a profile (per-diameter or absolute sizes) into absolute SI settings."""
    settings = dict(DEFAULTS)
    merged = {**profile, **(overrides or {})}
    for key in ('wall_size', 'bulk_size', 'transition'):
        absolute = merged.get(key + '_m') if key != 'transition' else merged.get('transition_distance_m')
        relative = merged.get(key + '_per_diameter')
        target = 'transition_distance_m' if key == 'transition' else key + '_m'
        if absolute is not None:
            settings[target] = float(absolute)
        elif relative is not None:
            settings[target] = float(relative) * diameter_m
    settings['curvature_points'] = int(merged.get('curvature_points', 24))
    settings['refinement_boxes'] = validate_boxes(merged.get('refinement_boxes', []))
    settings['keep_interface_group'] = bool(merged.get('keep_interface_group', False))
    return validate_settings(settings)


def validate_settings(settings):
    sizes = [settings['wall_size_m'], settings['bulk_size_m'], settings['transition_distance_m']]
    if any(v is None or not math.isfinite(v) or v <= 0 for v in sizes) or settings['wall_size_m'] > settings['bulk_size_m']:
        raise ValueError('Mesh sizes must be positive with wall_size_m <= bulk_size_m')
    if settings['curvature_points'] < 4:
        raise ValueError('curvature_points must be at least 4')
    if any(box['size_m'] > settings['bulk_size_m'] for box in settings['refinement_boxes']):
        raise ValueError('Refinement box size exceeds bulk size')
    return settings


def mesh(geometry, output, settings):
    """Generate MSH2 with physical volumes ``fluid``/``solid`` and named patches."""
    geometry, output = Path(geometry).resolve(), Path(output).resolve()
    settings = validate_settings({**DEFAULTS, **settings})
    if output.exists():
        raise ValueError('Refusing to overwrite an existing mesh')
    manifest = json.loads((geometry / 'manifest.json').read_text())
    for name, expected in manifest['files'].items():
        if digest(geometry / name) != expected:
            raise ValueError(f'Geometry changed since extraction: {name}')
    gmsh = backend()
    gmsh.initialize()
    try:
        gmsh.option.setNumber('General.Terminal', 0)
        gmsh.option.setNumber('General.NumThreads', 1)
        gmsh.open(str(geometry / 'coupled.geo'))
        if not settings['keep_interface_group']:
            groups = [(d, t) for d, t in gmsh.model.getPhysicalGroups(2) if gmsh.model.getPhysicalName(d, t) == 'interface']
            gmsh.model.removePhysicalGroups(groups)
        distance = gmsh.model.mesh.field.add('Distance')
        gmsh.model.mesh.field.setNumbers(distance, 'SurfacesList', manifest['boundary_map']['interface']['occ_surface_tags'])
        gmsh.model.mesh.field.setNumber(distance, 'Sampling', 100)
        threshold = gmsh.model.mesh.field.add('Threshold')
        for key, value in {'InField': distance, 'SizeMin': settings['wall_size_m'], 'SizeMax': settings['bulk_size_m'],
                           'DistMin': 0, 'DistMax': settings['transition_distance_m']}.items():
            gmsh.model.mesh.field.setNumber(threshold, key, value)
        fields = [threshold]
        bounds = gmsh.model.getBoundingBox(-1, -1)
        for box in settings['refinement_boxes']:
            b = box['bounds_m']
            if any(b[i + 3] < bounds[i] or b[i] > bounds[i + 3] for i in range(3)):
                raise ValueError('Refinement box does not intersect the geometry')
            field = gmsh.model.mesh.field.add('Box')
            values = dict(zip(('XMin', 'YMin', 'ZMin', 'XMax', 'YMax', 'ZMax'), b))
            values.update(VIn=box['size_m'], VOut=settings['bulk_size_m'], Thickness=box.get('transition_m', 0))
            for key, value in values.items():
                gmsh.model.mesh.field.setNumber(field, key, value)
            fields.append(field)
        background = threshold
        if len(fields) > 1:
            background = gmsh.model.mesh.field.add('Min')
            gmsh.model.mesh.field.setNumbers(background, 'FieldsList', fields)
        gmsh.model.mesh.field.setAsBackgroundMesh(background)
        gmsh.option.setNumber('Mesh.MeshSizeMin', min([settings['wall_size_m']] + [b['size_m'] for b in settings['refinement_boxes']]))
        gmsh.option.setNumber('Mesh.MeshSizeMax', settings['bulk_size_m'])
        gmsh.option.setNumber('Mesh.MeshSizeFromCurvature', settings['curvature_points'])
        gmsh.option.setNumber('Mesh.MeshSizeExtendFromBoundary', 0)
        gmsh.option.setNumber('Mesh.Algorithm3D', 1)
        gmsh.option.setNumber('Mesh.Optimize', 1)
        gmsh.option.setNumber('Mesh.MshFileVersion', 2.2)
        gmsh.model.mesh.generate(3)
        output.parent.mkdir(parents=True, exist_ok=True)
        gmsh.write(str(output))
        counts = {name: sum(len(tags) for tags in gmsh.model.mesh.getElements(3, region['occ_volume_tag'])[1])
                  for name, region in manifest['regions'].items()}
        report = {'geometry_manifest_sha256': digest(geometry / 'manifest.json'), 'mesh_sha256': digest(output),
                  'adapter_sha256': digest(__file__), 'gmsh_runtime': gmsh.option.getString('General.Version'),
                  'units': 'm', 'element_counts': counts, 'sizing': settings,
                  'boundary_layers': 'isotropic tetrahedra; no prismatic layers',
                  'interface_group_exported': settings['keep_interface_group']}
        output.with_suffix('.json').write_text(json.dumps(report, indent=2) + '\n')
        return report
    finally:
        gmsh.finalize()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('geometry')
    parser.add_argument('output')
    parser.add_argument('--wall-size', type=float, required=True, help='SI wall edge target')
    parser.add_argument('--bulk-size', type=float, required=True)
    parser.add_argument('--transition-distance', type=float)
    parser.add_argument('--curvature-points', type=int, default=24)
    parser.add_argument('--keep-interface-group', action='store_true')
    parser.add_argument('--refinement-config', type=Path, help='JSON with refinement_boxes in SI units')
    args = parser.parse_args(argv)
    boxes = []
    if args.refinement_config:
        config = json.loads(args.refinement_config.read_text())
        boxes = validate_boxes(config.get('refinement_boxes', []))
    settings = {'wall_size_m': args.wall_size, 'bulk_size_m': args.bulk_size,
                'transition_distance_m': args.transition_distance or 4 * args.wall_size,
                'curvature_points': args.curvature_points, 'refinement_boxes': boxes,
                'keep_interface_group': args.keep_interface_group}
    print(json.dumps(mesh(args.geometry, args.output, settings), indent=2))


if __name__ == '__main__':
    main()
