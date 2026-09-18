"""ASCII OpenFOAM polyMesh and field readers (standard library only)."""
import math
from pathlib import Path
import re

TIME_PATTERN = re.compile(r'\d+(?:\.\d+)?')


def strip_comments(text):
    return re.sub(r'/\*.*?\*/|//[^\n]*', '', text, flags=re.S)


def list_body(path):
    """Return the raw text inside the top-level list of a polyMesh file."""
    text = strip_comments(Path(path).read_text())
    text = text[text.index('}') + 1:]
    return text[text.index('(') + 1:text.rindex(')')]


def block(text, name):
    """Return the text inside the braces of the named dictionary block."""
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


def parse_values(raw):
    """Parse the payload of a ``value``/``internalField`` entry into a list."""
    match = re.match(r'\s*(?:nonuniform\s+List<\w+>\s+(\d+)\s*\((.*)\)|uniform\s+(.*?))\s*;?\s*$', raw, re.S)
    if not match:
        raise ValueError('Unsupported field encoding')
    payload = match.group(2) if match.group(1) is not None else match.group(3)
    if '(' in payload:
        values = [[float(v) for v in item.split()] for item in re.findall(r'\(([^()]+)\)', payload)]
    else:
        values = [float(v) for v in payload.split()]
    if match.group(1) is not None and len(values) != int(match.group(1)):
        raise ValueError('Field value count does not match its declared size')
    flat = (x for value in values for x in (value if isinstance(value, list) else [value]))
    if any(not math.isfinite(x) for x in flat):
        raise ValueError('Nonfinite field values')
    return values


def patch_values(text, patch):
    """Values of the ``value`` entry inside a boundaryField patch block."""
    body = block(text, patch)
    found = re.search(r'\bvalue\s+(.*?;)', body, re.S)
    if not found:
        raise ValueError('No saved value for patch ' + patch)
    return parse_values(found.group(1))


def internal_values(path):
    text = Path(path).read_text()
    raw = text.split('internalField', 1)[1].split('boundaryField', 1)[0]
    return parse_values(raw)


def field_dimensions(path):
    found = re.search(r'\bdimensions\s*\[([^\]]+)\]', Path(path).read_text())
    return [float(v) for v in found.group(1).split()] if found else None


def latest_time(case):
    """Latest numeric time directory of a case, or None."""
    times = [p for p in Path(case).iterdir() if p.is_dir() and TIME_PATTERN.fullmatch(p.name)]
    if not times:
        return None
    return max(times, key=lambda p: float(p.name))


def solved_times(case):
    return sorted((p for p in Path(case).iterdir() if p.is_dir() and TIME_PATTERN.fullmatch(p.name)
                   and float(p.name) > 0), key=lambda p: float(p.name))


class PolyMesh:
    """Points, faces, owner/neighbour and patch ranges of one region mesh."""

    def __init__(self, folder):
        self.folder = Path(folder)
        self.points = [tuple(float(v) for v in item.split())
                       for item in re.findall(r'\(([^()]+)\)', list_body(self.folder / 'points'))]
        self.faces = [tuple(int(v) for v in item.split())
                      for item in re.findall(r'\d+\s*\(([^()]+)\)', list_body(self.folder / 'faces'))]
        self.owner = [int(v) for v in list_body(self.folder / 'owner').split()]
        self.neighbour = [int(v) for v in list_body(self.folder / 'neighbour').split()]
        if len(self.owner) != len(self.faces):
            raise ValueError('Mesh owner/face count mismatch in ' + str(self.folder))
        self.cell_count = max(self.owner + self.neighbour) + 1
        self.patches = {}
        for name, body in re.findall(r'(\w+)\s*\{([^{}]*)\}', strip_comments((self.folder / 'boundary').read_text())):
            count = re.search(r'\bnFaces\s+(\d+)', body)
            start = re.search(r'\bstartFace\s+(\d+)', body)
            if count and start:
                self.patches[name] = (int(start.group(1)), int(count.group(1)))

    def patch_range(self, patch):
        start, count = self.patches[patch]
        return range(start, start + count)

    def face_area_vector(self, index):
        polygon = [self.points[n] for n in self.faces[index]]
        result = [0., 0., 0.]
        origin = polygon[0]
        for first, second in zip(polygon[1:-1], polygon[2:]):
            a = [first[i] - origin[i] for i in range(3)]
            b = [second[i] - origin[i] for i in range(3)]
            for i in range(3):
                result[i] += .5 * (a[(i + 1) % 3] * b[(i + 2) % 3] - a[(i + 2) % 3] * b[(i + 1) % 3])
        return result

    def face_centre(self, index):
        polygon = [self.points[n] for n in self.faces[index]]
        return [sum(p[i] for p in polygon) / len(polygon) for i in range(3)]

    def patch_area_vectors(self, patch):
        return [self.face_area_vector(i) for i in self.patch_range(patch)]

    def patch_areas(self, patch):
        return [math.sqrt(sum(v * v for v in vector)) for vector in self.patch_area_vectors(patch)]

    def patch_centres(self, patch):
        return [self.face_centre(i) for i in self.patch_range(patch)]

    def cell_nodes(self, cell):
        nodes = set()
        for index, face in enumerate(self.faces):
            if self.owner[index] == cell or (index < len(self.neighbour) and self.neighbour[index] == cell):
                nodes.update(face)
        return nodes

    def cell_location(self, cell):
        nodes = self.cell_nodes(cell)
        return [sum(self.points[n][i] for n in nodes) / len(nodes) for i in range(3)]

    def read_boundary(self, field_path, patch):
        """Saved boundary values, expanding uniform, zeroGradient and noSlip."""
        text = Path(field_path).read_text()
        start, count = self.patches[patch]
        try:
            values = patch_values(text, patch)
        except ValueError:
            body = block(block(text, 'boundaryField'), patch)
            if re.search(r'\btype\s+zeroGradient\s*;', body):
                internal = internal_values(field_path)
                return [internal[self.owner[i]] for i in range(start, start + count)]
            if re.search(r'\btype\s+noSlip\s*;', body):
                return [[0., 0., 0.]] * count
            raise
        if len(values) == 1:
            values = values * count
        if len(values) != count:
            raise ValueError(f'Patch {patch} value count mismatch in {field_path}')
        return values

    def read_internal(self, field_path):
        values = internal_values(field_path)
        if len(values) == 1:
            values = values * self.cell_count
        if len(values) != self.cell_count:
            raise ValueError('Internal field cell count mismatch in ' + str(field_path))
        return values


def read_boundary(field_path, patch, mesh_folder):
    """Convenience wrapper when a PolyMesh has not been built yet."""
    return PolyMesh(mesh_folder).read_boundary(field_path, patch)
