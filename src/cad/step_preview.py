#!/usr/bin/env python3
"""Import STEP for face picking. Surface triangles are display data, never CFD data.

Run through tools/workbench.py job. The Gmsh API is process-global: invoke this
module in a dedicated process. Only the output JSON is written; input is immutable.
"""
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

from src.foam.hashing import digest

HERE = Path(__file__).resolve().parent
ADAPTER_VERSION = "1"


def backend():
    spec = importlib.util.spec_from_file_location("gmsh_preview_backend", HERE / "vendor/gmsh.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def add(a, b):
    return [x + y for x, y in zip(a, b)]


def sub(a, b):
    return [x - y for x, y in zip(a, b)]


def mul(a, value):
    return [x * value for x in a]


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def cross(a, b):
    return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]


def norm(a):
    return math.sqrt(dot(a, a))


def bounds(points):
    return [min(p[i] for p in points) for i in range(3)] + [max(p[i] for p in points) for i in range(3)]


def circular_loop(gmsh, curves, tolerance):
    """Fit an entire OCC wire; accept only closed, planar, circular samples."""
    points = []
    lengths = 0.0
    endpoints = []
    for curve in curves:
        tag = abs(int(curve))
        if gmsh.model.getType(1, tag) != "Circle":
            return None
        lo, hi = gmsh.model.getParametrizationBounds(1, tag)
        params = [float(lo[0]) + (float(hi[0])-float(lo[0]))*i/32 for i in range(33)]
        coords = gmsh.model.getValue(1, tag, params)
        samples = [list(map(float, coords[i:i+3])) for i in range(0, len(coords), 3)]
        endpoints.extend([samples[0], samples[-1]])
        points.extend(samples[:-1])
        lengths += gmsh.model.occ.getMass(1, tag)
    if len(points) < 3:
        return None
    # Each endpoint must have a matching endpoint, including a closed single edge.
    if any(not any(i != j and norm(sub(p, q)) < tolerance for j, q in enumerate(endpoints))
           for i, p in enumerate(endpoints)):
        return None
    p = points[0]
    q = max(points, key=lambda x: norm(sub(x, p)))
    a = sub(q, p)
    r = max(points, key=lambda x: norm(cross(a, sub(x, p))))
    b = sub(r, p)
    n = cross(a, b)
    n2 = dot(n, n)
    if n2 < tolerance**4:
        return None
    center = add(p, mul(add(mul(cross(b, n), dot(a, a)), mul(cross(n, a), dot(b, b))), 1/(2*n2)))
    radius = norm(sub(p, center))
    normal = mul(n, 1/math.sqrt(n2))
    if radius <= tolerance:
        return None
    if any(abs(norm(sub(x, center))-radius) > tolerance or abs(dot(sub(x, center), normal)) > tolerance for x in points):
        return None
    if abs(lengths - 2*math.pi*radius) > max(tolerance*len(curves), radius*1e-6):
        return None
    return center, radius, normal


def virtual_ports(gmsh, faces, tolerance, segments):
    result = []
    seen = set()
    for face in faces:
        if face["surface_type"] != "Plane":
            continue
        tag = int(face["id"].split(":")[1])
        _, loops = gmsh.model.occ.getCurveLoops(tag)
        for loop in loops:
            curve_tags = sorted(abs(int(x)) for x in loop)
            key = tuple(curve_tags)
            if key in seen:
                continue
            seen.add(key)
            fitted = circular_loop(gmsh, curve_tags, tolerance)
            if fitted is None:
                continue
            center, radius, normal = fitted
            # A center inside a planar CAD face denotes an existing disk, not a hole.
            if any(gmsh.model.isInside(2, int(f["id"].split(":")[1]), center) > 0
                   for f in faces if f["surface_type"] == "Plane"
                   and abs(dot(sub(f["centroid_mm"], center), normal)) < tolerance):
                continue
            axis = [1., 0., 0.] if abs(normal[0]) < .8 else [0., 1., 0.]
            u = cross(normal, axis)
            u = mul(u, 1/norm(u))
            v = cross(normal, u)
            ring = [add(center, add(mul(u, radius*math.cos(2*math.pi*i/segments)),
                                    mul(v, radius*math.sin(2*math.pi*i/segments)))) for i in range(segments)]
            points = [center] + ring
            result.append({"id": "port:" + "-".join(map(str, curve_tags)),
                           "kind": "virtual_port", "candidate": True,
                           "source_curve_tags": curve_tags, "adjacent_face_id": face["id"],
                           "surface_type": "VirtualDisk", "area_mm2": math.pi*radius**2,
                           "centroid_mm": center, "radius_mm": radius, "normal": normal,
                           "bounds_mm": bounds(points),
                           "positions": [x for p in points for x in p],
                           "triangles": [x for i in range(segments) for x in (0, i+1, (i+1)%segments+1)]})
    return result


def preview(source, output, relative_size=.035, circle_segments=64):
    source, output = Path(source).resolve(), Path(output).resolve()
    if source == output or output.exists():
        raise ValueError("Output must be a new path distinct from input CAD")
    if source.suffix.lower() not in (".step", ".stp"):
        raise ValueError("Only STEP (.step/.stp) display import is supported")
    if not .002 <= relative_size <= .2 or not 16 <= circle_segments <= 256:
        raise ValueError("Display size must be .002.. .2 and circle segments 16..256")
    source_hash = digest(source)
    gmsh = backend()
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 1)
        version = gmsh.option.getString("General.Version")
        if not version.startswith("4.14.0"):
            raise RuntimeError("This display adapter is pinned to Gmsh 4.14.0; found " + version)
        gmsh.option.setString("Geometry.OCCTargetUnit", "MM")
        gmsh.model.add("step_display_review")
        gmsh.model.occ.importShapes(str(source), highestDimOnly=False)
        gmsh.model.occ.synchronize()
        entities = gmsh.model.getEntities(2)
        if not entities:
            raise ValueError("STEP contains no displayable CAD faces")
        bbox = list(map(float, gmsh.model.getBoundingBox(-1, -1)))
        diagonal = norm(sub(bbox[3:], bbox[:3]))
        if not math.isfinite(diagonal) or diagonal <= 0:
            raise ValueError("STEP has invalid extent")
        size = diagonal*relative_size
        settings = {"relative_size": relative_size, "target_edge_mm": size,
                    "circle_segments": circle_segments, "surface_algorithm": 6,
                    "element_order": 1, "threads": 1}
        gmsh.option.setNumber("General.NumThreads", 1)
        gmsh.option.setNumber("Mesh.MeshSizeMin", size/4)
        gmsh.option.setNumber("Mesh.MeshSizeMax", size)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 20)
        gmsh.option.setNumber("Mesh.Algorithm", 6)
        gmsh.option.setNumber("Mesh.ElementOrder", 1)
        gmsh.option.setNumber("Mesh.RecombineAll", 0)
        gmsh.model.mesh.generate(2)  # DISPLAY surface tessellation, never volume/CFD meshing.
        node_tags, coords, _ = gmsh.model.mesh.getNodes()
        nodes = {int(tag): list(map(float, coords[3*i:3*i+3])) for i, tag in enumerate(node_tags)}
        faces = []
        for _, tag in entities:
            types, _, connectivity = gmsh.model.mesh.getElements(2, tag)
            node_ids = []
            for kind, element_nodes in zip(types, connectivity):
                if int(kind) != 2:
                    raise RuntimeError("Unexpected non-linear/non-triangle display elements")
                node_ids.extend(map(int, element_nodes))
            if not node_ids:
                raise RuntimeError(f"CAD face {tag} failed display tessellation")
            unique = sorted(set(node_ids))
            index = {node: i for i, node in enumerate(unique)}
            faces.append({"id": f"face:{tag}", "kind": "cad_face",
                          "surface_type": gmsh.model.getType(2, tag),
                          "area_mm2": float(gmsh.model.occ.getMass(2, tag)),
                          "centroid_mm": list(map(float, gmsh.model.occ.getCenterOfMass(2, tag))),
                          "bounds_mm": list(map(float, gmsh.model.getBoundingBox(2, tag))),
                          "positions": [x for node in unique for x in nodes[node]],
                          "triangles": [index[node] for node in node_ids]})
        ports = virtual_ports(gmsh, faces, max(1e-6, diagonal*1e-7), circle_segments)
        importer = {"name": "gmsh", "version": version, "api_version": gmsh.__version__,
                    "adapter_version": ADAPTER_VERSION,
                    "adapter_sha256": digest(__file__),
                    "wrapper_sha256": digest(HERE / "vendor/gmsh.py"),
                    "display_settings": settings}
        identity = {"source_sha256": source_hash, "importer": importer, "units": "mm"}
        fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        result = {"schema_version": 1, "scope": "display_only", "units": "mm",
                  "source": {"name": source.name, "sha256": source_hash},
                  "importer": importer, "import_fingerprint": fingerprint,
                  "bounds": bbox, "solid_count": len(gmsh.model.getEntities(3)),
                  "faces": faces, "virtual_faces": ports,
                  "warnings": ["Surface triangles are for display and face picking only; no CFD mesh or simulation was created.",
                               "Face IDs are valid only with this exact import fingerprint; re-imported or changed CAD requires review.",
                               "Virtual disks are unconfirmed circular-opening candidates; blind holes and fillets can also produce candidates. They do not alter or cap source CAD.",
                               "Only planar circular boundary loops are supported as virtual openings. Verify units, scale, connectivity and boundary choices before simulation."]}
        if digest(source) != source_hash:
            raise RuntimeError("Input STEP changed during import")
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x") as stream:
            json.dump(result, stream, allow_nan=False, separators=(",", ":"))
            stream.write("\n")
        return result
    finally:
        gmsh.finalize()


def preview_step(source_path, output_path):
    """Manager entry point; creates a new JSON and returns its decoded content."""
    return preview(source_path, output_path)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "demo":
        parser = argparse.ArgumentParser(description="Create synthetic display STEP fixture; no simulation")
        parser.add_argument("demo")
        parser.add_argument("--output", required=True)
        args = parser.parse_args()
        import runpy
        sys.argv = [str(HERE / "fixtures/make_cooling_block.py"), args.output]
        runpy.run_path(sys.argv[0], run_name="__main__")
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("output")
    parser.add_argument("--relative-size", type=float, default=.035)
    args = parser.parse_args()
    result = preview(args.source, args.output, args.relative_size)
    print(json.dumps({"output": str(args.output), "source_sha256": result["source"]["sha256"],
                      "faces": len(result["faces"]), "virtual_faces": len(result["virtual_faces"]),
                      "solid_count": result["solid_count"], "scope": result["scope"]}))


if __name__ == "__main__":
    main()
