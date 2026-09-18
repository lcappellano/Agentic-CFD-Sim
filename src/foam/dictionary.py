"""Minimal OpenFOAM dictionary and field writers."""
from pathlib import Path


def write_dictionary(path, body, cls='dictionary', obj=None):
    """Write an OpenFOAM file with a FoamFile header followed by ``body``."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    header = f'FoamFile {{ version 2.0; format ascii; class {cls}; object {obj or path.name}; }}\n'
    path.write_text(header + body + '\n')


def write_field(case, region, name, dimensions, internal_value, boundaries, vector=False):
    """Write a uniform initial field with one boundary entry per patch."""
    lines = [f'dimensions {dimensions};', f'internalField uniform {internal_value};', 'boundaryField', '{']
    for patch, entry in boundaries.items():
        lines.append(f'    {patch} {{ {entry} }}')
    lines.append('}')
    write_dictionary(Path(case) / '0' / region / name, '\n'.join(lines),
                     'volVectorField' if vector else 'volScalarField')


def vector_text(values):
    return '(' + ' '.join(str(v) for v in values) + ')'


def coefficient_array(values):
    """Format an eight-coefficient polynomial array with full precision."""
    return '(' + ' '.join(format(v, '.17g') for v in values) + ')'
