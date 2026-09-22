"""Design variants of a reviewed part, built with the gmsh OCC kernel and written as a new STEP.

The input CAD is never modified; every variant is a new file with a provenance JSON beside it.
Two operations the manifold results asked for:

* ``bullnose_rib_ends``: the ribs between the channels end in a V-notch (a mid-height apex with
  two knife-edged prongs); the fine mesh put a cell at -2 bar absolute at that apex. The notch is
  filled and the rib end rounded into a semicircle of the rib half-width, full channel height.
* ``header_guide_vanes``: thin vanes in a wide-angle header split its fan into sectors of equal
  inlet width and equal collector width, so the outer channels are fed like the central ones
  (the manifold's outer channels carried 0.88 of the mean flow behind a 68 degree fan).

Both are booleans on the solid. The pipeline re-extracts the passage from the new STEP after
the user reviews and approves it again; nothing here touches the runs.
"""
import argparse
import json
import math
from pathlib import Path

from src.cad.step_preview import backend
from src.foam.hashing import digest


def _open(step):
    gmsh = backend()
    gmsh.initialize()
    gmsh.option.setNumber('General.Terminal', 0)
    gmsh.option.setNumber('Geometry.OCCImportLabels', 0)
    gmsh.option.setString('Geometry.OCCTargetUnit', 'MM')  # the extractor's 'M' setting survives finalize() in-process
    gmsh.option.setNumber('Geometry.ToleranceBoolean', 1e-5)
    gmsh.model.occ.importShapes(str(step), highestDimOnly=True)
    gmsh.model.occ.synchronize()
    volumes = gmsh.model.getEntities(3)
    if len(volumes) != 1:
        gmsh.finalize()
        raise ValueError(f'Expected one solid in {step}, found {len(volumes)}')
    return gmsh, volumes[0][1]


def _bbox(gmsh, dim, tag):
    return gmsh.model.getBoundingBox(dim, tag)


def find_notched_rib_ends(gmsh, solid, max_rib_width=3.0, tol=1e-3):
    """Rib-end notch apexes: horizontal line edges in a plane x = const, short in z, at the ribs' mid
    height, with fluid just outside the apex. Returns [(x_plane, sign, y_mid, z0, z1, depth), ...]."""
    ends = []
    for _, tag in gmsh.model.getEntities(1):
        if gmsh.model.getType(1, tag) != 'Line':
            continue
        x0, y0, z0, x1, y1, z1 = _bbox(gmsh, 1, tag)
        if abs(x1 - x0) > tol or abs(y1 - y0) > tol or not tol < (z1 - z0) <= max_rib_width:
            continue
        faces = gmsh.model.getAdjacencies(1, tag)[0]
        if len(faces) != 2:
            continue
        depth = max(abs(_bbox(gmsh, 2, f)[3] - _bbox(gmsh, 2, f)[0]) for f in faces)
        if not tol < depth <= max_rib_width:
            continue
        x_plane, y_mid, zc = x0, y0, 0.5 * (z0 + z1)
        sign = 1.0 if x_plane >= 0 else -1.0
        # The notch opens away from the rib body: the point just outside the apex must be fluid.
        if gmsh.model.isInside(3, solid, [x_plane + sign * 0.5 * depth, y_mid, zc]):
            sign = -sign
            if gmsh.model.isInside(3, solid, [x_plane + sign * 0.5 * depth, y_mid, zc]):
                continue
        ends.append((x_plane, sign, y_mid, z0, z1, depth))
    return ends


def _only_volume(gmsh, what):
    """The single volume left in the model after a boolean (the returned lists are unreliable)."""
    gmsh.model.occ.synchronize()
    volumes = gmsh.model.getEntities(3)
    if len(volumes) != 1:
        raise ValueError(f'{what} did not leave one solid: {volumes}')
    return volumes[0][1]


def bullnose_rib_ends(gmsh, solid, ends):
    """Fill each notch and round the rib end into a semicircle of the rib half-width."""
    fills = []
    for x_plane, sign, y_mid, z0, z1, depth in ends:
        width, x_start = z1 - z0, min(x_plane, x_plane + sign * depth)
        fills.append((3, gmsh.model.occ.addBox(x_start, y_mid - depth, z0, depth, 2 * depth, width)))
    gmsh.model.occ.fuse([(3, solid)], fills)
    solid = _only_volume(gmsh, 'notch fill')
    tools = []
    for x_plane, sign, y_mid, z0, z1, depth in ends:
        width, x_start = z1 - z0, min(x_plane, x_plane + sign * depth)
        radius, x_end = 0.5 * width, x_plane + sign * depth
        box = gmsh.model.occ.addBox(x_start, y_mid - depth, z0, depth, 2 * depth, width)
        cylinder = gmsh.model.occ.addCylinder(x_end - sign * radius, y_mid - depth, 0.5 * (z0 + z1), 0, 2 * depth, 0, radius)
        gmsh.model.occ.cut([(3, box)], [(3, cylinder)])
    gmsh.model.occ.synchronize()
    tools = [v for v in gmsh.model.getEntities(3) if v[1] != solid]
    gmsh.model.occ.cut([(3, solid)], tools)
    gmsh.model.occ.removeAllDuplicates()
    return _only_volume(gmsh, 'bullnose cut')


def passage_half_width(gmsh, fluid, x, y, step=0.25, tol=0.01):
    """Half-width in z of the fluid passage on the line (x, y): the farthest point still inside the fluid,
    found by marching from z = 0 and bisecting (point classification; no boolean)."""
    if not gmsh.model.isInside(3, fluid, [x, y, 0.0]):
        raise ValueError(f'The passage does not contain the point ({x}, {y}, 0)')
    b = _bbox(gmsh, 3, fluid)
    inside, outside = 0.0, None
    z = step
    while z <= b[5] - b[2]:
        if gmsh.model.isInside(3, fluid, [x, y, z]):
            inside = z
        else:
            outside = z
            break
        z += step
    if outside is None:
        return inside
    while outside - inside > tol:
        mid = 0.5 * (inside + outside)
        if gmsh.model.isInside(3, fluid, [x, y, mid]):
            inside = mid
        else:
            outside = mid
    return 0.5 * (inside + outside)


def vane_layout(w_start, w_end, x_start, x_end, per_side):
    """Vane end points (x, z) dividing a fan of half-width w_start at x_start and w_end at x_end into
    2 * per_side + 1 sectors of equal width at both ends; both signs of z."""
    sectors = 2 * per_side + 1
    vanes = []
    for k in range(1, per_side + 1):
        for sign in (1, -1):
            vanes.append(((x_start, sign * w_start * (2 * k - 1) / sectors), (x_end, sign * w_end * (2 * k - 1) / sectors)))
    return vanes


def header_guide_vanes(gmsh, solid, fluid, layouts, thickness, y_min, y_max):
    """Fuse thin vanes into the solid; each vane is a rotated slab clipped to the fluid volume."""
    for (xa, za), (xb, zb) in layouts:
        dx, dz = xb - xa, zb - za
        length = math.hypot(dx, dz)
        box = gmsh.model.occ.addBox(0, y_min, -0.5 * thickness, length, y_max - y_min, thickness)
        gmsh.model.occ.rotate([(3, box)], 0, 0, 0, 0, 1, 0, math.atan2(-dz, dx))
        gmsh.model.occ.translate([(3, box)], xa, 0, za)
        gmsh.model.occ.intersect([(3, box)], [(3, fluid)], removeObject=True, removeTool=False)
    gmsh.model.occ.synchronize()
    plates = [v for v in gmsh.model.getEntities(3) if v[1] not in (solid, fluid)]
    if len(plates) != len(layouts):
        raise ValueError(f'{len(layouts)} vanes clipped to {len(plates)} bodies inside the passage')
    gmsh.model.occ.remove([(3, fluid)], recursive=True)
    gmsh.model.occ.fuse([(3, solid)], plates)
    gmsh.model.occ.removeAllDuplicates()
    return _only_volume(gmsh, 'vane fuse')


def build(step_in, step_out, fluid_brep=None, bullnose=True, vanes_per_side=0, vane_thickness=0.4,
          vane_x_start=None, vane_x_end=None):
    """Write ``step_out`` (mm, one solid) with the requested operations and a provenance JSON beside it."""
    step_in, step_out = Path(step_in).resolve(), Path(step_out).resolve()
    if step_out.exists():
        raise ValueError('Refusing to overwrite an existing file: ' + str(step_out))
    gmsh, solid = _open(step_in)
    try:
        report = {'source': str(step_in), 'source_sha256': digest(step_in), 'units': 'mm',
                  'volume_before_mm3': gmsh.model.occ.getMass(3, solid), 'operations': []}
        if bullnose:
            ends = find_notched_rib_ends(gmsh, solid)
            if not ends:
                raise ValueError('No notched rib ends found')
            solid = bullnose_rib_ends(gmsh, solid, ends)
            report['operations'].append({'bullnose_rib_ends': {'count': len(ends), 'planes_x': sorted({e[0] for e in ends}),
                                                               'radius_mm': sorted({0.5 * (e[4] - e[3]) for e in ends}),
                                                               'depth_mm': sorted({e[5] for e in ends})}})
        if vanes_per_side:
            if fluid_brep is None or vane_x_start is None or vane_x_end is None:
                raise ValueError('Vanes need the extracted fluid passage (fluid.brep, metres) and vane_x_start / vane_x_end (mm, '
                                 'positive: just downstream of the pipe transition, and a few mm before the collector)')
            imported = gmsh.model.occ.importShapes(str(Path(fluid_brep).resolve()), highestDimOnly=True)
            gmsh.model.occ.dilate(imported, 0, 0, 0, 1000, 1000, 1000)
            gmsh.model.occ.synchronize()
            fluid = imported[0][1]
            fb = _bbox(gmsh, 3, fluid)
            layouts, placed = [], {}
            for sign, key in ((1, 'plus'), (-1, 'minus')):
                if not (fb[0] <= sign * vane_x_start <= fb[3]):
                    continue  # a part with one header only
                y_mid = 0.5 * (fb[1] + fb[4])
                w_start = passage_half_width(gmsh, fluid, sign * vane_x_start, y_mid)
                w_end = passage_half_width(gmsh, fluid, sign * vane_x_end, y_mid)
                rows = [((sign * xa, za), (sign * xb, zb)) for (xa, za), (xb, zb)
                        in vane_layout(w_start, w_end, vane_x_start, vane_x_end, vanes_per_side)]
                layouts.extend(rows)
                placed[key] = {'x_start': sign * vane_x_start, 'x_end': sign * vane_x_end,
                               'half_width_start_mm': w_start, 'half_width_end_mm': w_end, 'vanes': rows}
            solid = header_guide_vanes(gmsh, solid, fluid, layouts, vane_thickness, fb[1] - 1, fb[4] + 1)
            for (xa, za), (xb, zb) in layouts:  # every vane must be present at its mid-length
                if not gmsh.model.isInside(3, solid, [0.5 * (xa + xb), y_mid, 0.5 * (za + zb)]):
                    raise ValueError(f'Vane from ({xa}, {za}) to ({xb}, {zb}) is missing at its midpoint')
            report['operations'].append({'header_guide_vanes': {'per_side': vanes_per_side, 'thickness_mm': vane_thickness,
                                                                'sectors': 2 * vanes_per_side + 1, 'headers': placed,
                                                                'fluid_brep': str(Path(fluid_brep).resolve())}})
        volumes = gmsh.model.getEntities(3)
        if len(volumes) != 1:
            raise ValueError(f'Variant has {len(volumes)} solids')
        report['volume_after_mm3'] = gmsh.model.occ.getMass(3, volumes[0][1])
        report['faces_after'] = len(gmsh.model.getEntities(2))
        step_out.parent.mkdir(parents=True, exist_ok=True)
        scratch = step_out.with_name(step_out.stem + '.variant-export.step')  # gmsh only knows lowercase .step/.stp
        gmsh.write(str(scratch))
        scratch.replace(step_out)
    finally:
        gmsh.finalize()
    report['output'] = str(step_out)
    report['output_sha256'] = digest(step_out)
    step_out.with_suffix('.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('step_in', type=Path)
    parser.add_argument('step_out', type=Path)
    parser.add_argument('--fluid', type=Path, help='extracted fluid.brep of the source part (needed for vanes)')
    parser.add_argument('--no-bullnose', action='store_true')
    parser.add_argument('--vanes-per-side', type=int, default=0)
    parser.add_argument('--vane-thickness', type=float, default=0.4)
    parser.add_argument('--vane-x-start', type=float)
    parser.add_argument('--vane-x-end', type=float)
    args = parser.parse_args()
    print(json.dumps(build(args.step_in, args.step_out, args.fluid, not args.no_bullnose, args.vanes_per_side,
                           args.vane_thickness, args.vane_x_start, args.vane_x_end), indent=2))


if __name__ == '__main__':
    main()


def plan_section_svg(steps, y, x_range, z_range, out_svg, labels=None, width_px=900):
    """Plan-view sections (plane y = const, looking down the y axis) of one or more STEP files, side by
    side in one SVG, for reviewing a variant against its source without a CAD viewer."""
    panels = []
    for step in steps:
        gmsh, solid = _open(step)
        try:
            slab = gmsh.model.occ.addBox(x_range[0], y - 0.05, z_range[0], x_range[1] - x_range[0], 0.1, z_range[1] - z_range[0])
            gmsh.model.occ.intersect([(3, slab)], [(3, solid)])
            gmsh.model.occ.synchronize()
            lines = []
            for _, tag in gmsh.model.getEntities(1):
                b = _bbox(gmsh, 1, tag)
                if abs(b[1] - (y + 0.05)) > 1e-3 or abs(b[4] - (y + 0.05)) > 1e-3:
                    continue
                t0, t1 = gmsh.model.getParametrizationBounds(1, tag)
                n = 2 if gmsh.model.getType(1, tag) == 'Line' else 24
                pts = [gmsh.model.getValue(1, tag, [t0[0] + (t1[0] - t0[0]) * i / (n - 1)]) for i in range(n)]
                lines.append([(p[0], p[2]) for p in pts])
            panels.append(lines)
        finally:
            gmsh.finalize()
    scale = width_px / (x_range[1] - x_range[0])
    height = (z_range[1] - z_range[0]) * scale
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width_px}" height="{(height + 30) * len(panels)}" '
             f'viewBox="0 0 {width_px} {(height + 30) * len(panels)}" font-family="sans-serif" font-size="14">']
    for k, lines in enumerate(panels):
        oy = k * (height + 30) + 30
        label = (labels or [Path(s).name for s in steps])[k]
        parts.append(f'<text x="8" y="{oy - 10}">{label}: section y = {y} mm, x {x_range[0]}..{x_range[1]} mm (right is +x), '
                     f'z {z_range[0]}..{z_range[1]} mm (down is +z); black = solid outline</text>')
        parts.append(f'<rect x="0" y="{oy}" width="{width_px}" height="{height}" fill="#f4f6f8"/>')
        for pts in lines:
            d = ' '.join(f'{(px - x_range[0]) * scale:.1f},{(pz - z_range[0]) * scale + oy:.1f}' for px, pz in pts)
            parts.append(f'<polyline points="{d}" fill="none" stroke="#111" stroke-width="1.2"/>')
    parts.append('</svg>')
    Path(out_svg).write_text('\n'.join(parts))
    return out_svg
