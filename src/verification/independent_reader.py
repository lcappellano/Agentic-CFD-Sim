"""Second, independent ASCII OpenFOAM reader used only by verification.

Kept separate from ``src.foam.fields`` on purpose: a parsing defect in the
shared reader cannot silently agree with itself here. Do not add a third.
"""
import math
from pathlib import Path
import re

from src.foam.hashing import digest


def clean(path):
    text = Path(path).read_text()
    if re.search(r'\bformat\s+binary\s*;', text):
        raise ValueError('Only ASCII fields supported: ' + str(path))
    return re.sub(r'/\*.*?\*/|//[^\n]*', '', text, flags=re.S)


def list_body(path):
    text = re.sub(r'FoamFile\s*\{.*?\}', '', clean(path), flags=re.S)
    found = re.search(r'\b(\d+)\s*\(', text)
    if not found:
        raise ValueError('No mesh list in ' + str(path))
    return int(found.group(1)), text[found.end():text.rindex(')')]


def field_values(text, count):
    nonuniform = re.match(r'\s*nonuniform\s+List<(scalar|vector)>\s+(\d+)\s*\((.*?)\)\s*;', text, re.S)
    if nonuniform:
        if nonuniform.group(1) == 'vector':
            result = [tuple(map(float, item.split())) for item in re.findall(r'\(([^()]+)\)', nonuniform.group(3))]
        else:
            result = list(map(float, nonuniform.group(3).split()))
        if len(result) != int(nonuniform.group(2)) or len(result) != count:
            raise ValueError('Nonuniform field count mismatch')
    else:
        uniform = re.match(r'\s*uniform\s+([^;]+);', text)
        if not uniform:
            raise ValueError('Missing supported uniform/nonuniform field')
        value = uniform.group(1).strip()
        value = tuple(map(float, value.strip('()').split())) if value.startswith('(') else float(value)
        result = [value] * count
    if any(not math.isfinite(x) for value in result for x in (value if isinstance(value, tuple) else (value,))):
        raise ValueError('Nonfinite saved field values')
    return result


def block(text, name):
    found = re.search(r'\b' + re.escape(name) + r'\s*\{', text)
    if not found:
        raise ValueError('Missing block ' + name)
    depth, end = 1, found.end()
    while depth and end < len(text):
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    if depth:
        raise ValueError('Unterminated block ' + name)
    return text[found.end():end - 1]


def vector_area(poly):
    result = [0., 0., 0.]
    origin = poly[0]
    for first, second in zip(poly[1:-1], poly[2:]):
        a = [first[i] - origin[i] for i in range(3)]
        b = [second[i] - origin[i] for i in range(3)]
        for i in range(3):
            result[i] += .5 * (a[(i + 1) % 3] * b[(i + 2) % 3] - a[(i + 2) % 3] * b[(i + 1) % 3])
    return result


class Mesh:
    def __init__(self, folder, hashes):
        self.folder, self.hashes = Path(folder), hashes
        n, raw = list_body(self.folder / 'points')
        self.points = [tuple(map(float, x.split())) for x in re.findall(r'\(([^()]+)\)', raw)]
        if len(self.points) != n:
            raise ValueError('Point count mismatch')
        n, raw = list_body(self.folder / 'faces')
        self.faces = [list(map(int, x.split())) for x in re.findall(r'\d+\s*\(([^()]+)\)', raw)]
        if len(self.faces) != n:
            raise ValueError('Face count mismatch')
        n, raw = list_body(self.folder / 'owner')
        self.owners = list(map(int, raw.split()))
        if len(self.owners) != n:
            raise ValueError('Owner count mismatch')
        n, raw = list_body(self.folder / 'neighbour')
        self.neighbours = list(map(int, raw.split()))
        if len(self.neighbours) != n:
            raise ValueError('Neighbour count mismatch')
        self.cell_count = max(self.owners + self.neighbours) + 1
        self.patches = {}
        for name, raw in re.findall(r'(\w+)\s*\{([^{}]*)\}', clean(self.folder / 'boundary')):
            count, start = re.search(r'\bnFaces\s+(\d+)', raw), re.search(r'\bstartFace\s+(\d+)', raw)
            if count and start:
                indices = range(int(start.group(1)), int(start.group(1)) + int(count.group(1)))
                polygons = [[self.points[x] for x in self.faces[i]] for i in indices]
                vectors = [vector_area(poly) for poly in polygons]
                self.patches[name] = {'indices': indices, 'vectors': vectors,
                                      'areas': [math.sqrt(sum(x * x for x in v)) for v in vectors],
                                      'centres': [[sum(p[j] for p in poly) / len(poly) for j in range(3)] for poly in polygons]}
        for name in ('points', 'faces', 'owner', 'neighbour', 'boundary'):
            self.hashes[str(self.folder / name)] = digest(self.folder / name)

    def cell_location(self, cell):
        nodes = set()
        for index, face in enumerate(self.faces):
            if self.owners[index] == cell or (index < len(self.neighbours) and self.neighbours[index] == cell):
                nodes.update(face)
        return {'coordinate_m': [sum(self.points[n][j] for n in nodes) / len(nodes) for j in range(3)],
                'location_kind': 'exact tetrahedron centroid' if len(nodes) == 4 else 'cell vertex-average location',
                'cell_index': cell, 'vertex_count': len(nodes)}

    def read(self, field, patch=None, expected_dimensions=None):
        text = clean(field)
        self.hashes[str(field)] = digest(field)
        if expected_dimensions is not None:
            dimensions = re.search(r'\bdimensions\s*\[([^]]+)\]', text)
            if not dimensions or list(map(float, dimensions.group(1).split())) != expected_dimensions:
                raise ValueError('Unexpected field units: ' + str(field))
        if patch is None:
            return field_values(re.split(r'\binternalField\s+', text, maxsplit=1)[1], self.cell_count)
        raw = block(block(text, 'boundaryField'), patch)
        indices = self.patches[patch]['indices']
        value = re.search(r'\bvalue\s+', raw)
        if value:
            return field_values(raw[value.end():], len(indices))
        if re.search(r'\btype\s+zeroGradient\s*;', raw):
            internal = field_values(re.split(r'\binternalField\s+', text, maxsplit=1)[1], self.cell_count)
            return [internal[self.owners[i]] for i in indices]
        if re.search(r'\btype\s+noSlip\s*;', raw):
            return [(0., 0., 0.)] * len(indices)
        raise ValueError('No saved boundary value: ' + str(field) + ':' + patch)
