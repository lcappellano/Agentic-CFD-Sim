"""Plot actual fixed-demo fields with ParaView's bundled matplotlib runtime.

Invoke pvpython --no-mpi --disable-registry through the workbench job recorder.
This is a plotting adapter; it does not calculate or validate a CFD solution.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cfd.summarize_demo import numbers, read_boundary
from verification.audit_demo_mesh import body
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
import numpy as np


def plot(run, coarse, fine):
    output = run / 'report'
    output.mkdir(exist_ok=True)
    cases = [(coarse, 'Coarse mesh'), (fine, 'Fine mesh')]
    fig, axes = plt.subplots(2, 1, figsize=(9, 7), sharex=True, layout='constrained')
    for case, label in cases:
        temperature = numbers(case, 'heatedMax')
        inlet = dict(numbers(case, 'inletPressure'))
        outlet = dict(numbers(case, 'outletPressure'))
        times = sorted(set(inlet) & set(outlet))
        axes[0].plot([t for t, _ in temperature], [v[0] - 273.15 for _, v in temperature], label=label)
        axes[1].plot(times, [(inlet[t][0] - outlet[t][0]) / 1e5 for t in times], label=label)
    axes[0].set_ylabel('Maximum heated-face temperature (°C)')
    axes[1].set_ylabel('Inlet-to-outlet pressure drop (bar)')
    axes[1].set_xlabel('Steady solver iteration (not physical seconds)')
    for ax in axes:
        ax.grid(alpha=.25)
        ax.legend()
    fig.suptitle('Fixed demo baseline: convergence on two meshes')
    fig.savefig(output / 'convergence.png', dpi=180)
    plt.close(fig)

    latest = max((p for p in fine.iterdir() if p.is_dir() and re.fullmatch(r'\d+(\.\d+)?', p.name)), key=lambda p: float(p.name))
    mesh = fine / 'constant/solid/polyMesh'
    point_count, point_text = body(mesh / 'points')
    points = np.array([list(map(float, p.split())) for p in re.findall(r'\(([^()]*)\)', point_text)]) * 1000
    face_count, face_text = body(mesh / 'faces')
    faces = [list(map(int, f.split())) for f in re.findall(r'\d+\(([^()]*)\)', face_text)]
    if len(points) != point_count or len(faces) != face_count:
        raise ValueError('Mesh array lengths do not match headers')
    boundary_text = (mesh / 'boundary').read_text()
    polygons, values = [], []
    for name, content in re.findall(r'(\w+)\s*\{([^{}]*)\}', boundary_text):
        if name not in ('heated', 'outerWalls', 'solid_to_fluid'):
            continue
        count = int(re.search(r'\bnFaces\s+(\d+)', content).group(1))
        start = int(re.search(r'\bstartFace\s+(\d+)', content).group(1))
        temperature = read_boundary(latest / 'solid/T', name, mesh)
        if len(temperature) == 1:
            temperature *= count
        if len(temperature) != count:
            raise ValueError('Temperature values do not match boundary faces')
        for face, value in zip(faces[start:start + count], temperature):
            polygons.append(points[face])
            values.append(value - 273.15)
    values = np.array(values)
    fig = plt.figure(figsize=(10, 7), layout='constrained')
    ax = fig.add_subplot(projection='3d')
    norm = Normalize(vmin=float(values.min()), vmax=float(values.max()))
    cmap = matplotlib.colormaps['inferno']
    collection = Poly3DCollection(polygons, facecolors=cmap(norm(values)), edgecolors='none', linewidths=0)
    ax.add_collection3d(collection)
    ax.set(xlim=(0, 60), ylim=(0, 40), zlim=(0, 20), xlabel='x (mm)', ylabel='y (mm)', zlabel='z (mm)')
    ax.set_box_aspect((60, 40, 20))
    ax.view_init(elev=27, azim=-135)
    fig.colorbar(matplotlib.cm.ScalarMappable(norm=norm, cmap=cmap), ax=ax, shrink=.65, label='Copper surface temperature (°C)')
    ax.set_title('Fine-mesh copper surface temperature\n240 W top heating · 0.5 kg/s water at 300 K')
    fig.savefig(output / 'surface-temperature.png', dpi=180)
    plt.close(fig)
    provenance = {'runtime': 'ParaView embedded Python / matplotlib', 'matplotlib_version': matplotlib.__version__,
                  'cases': [str(coarse), str(fine)], 'field_iteration': latest.name,
                  'surface_range_C': [float(values.min()), float(values.max())],
                  'field_sha256': hashlib.sha256((latest / 'solid/T').read_bytes()).hexdigest(),
                  'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (output / 'plot-provenance.json').write_text(json.dumps(provenance, indent=2) + '\n')
    print(json.dumps(provenance, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('coarse', type=Path)
    parser.add_argument('fine', type=Path)
    args = parser.parse_args()
    plot(args.run, args.coarse, args.fine)
