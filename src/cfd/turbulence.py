"""Named OpenCFD v2412 RANS and near-wall configurations.

``kEpsilon``: standard wall functions (aligned hex baseline).
``kOmegaSST_spalding``: continuous Spalding velocity and blended omega wall
functions (tetrahedral passages). Both use the Jayatilleke thermal wall function.
"""
import math

MODELS = ('kEpsilon', 'kOmegaSST_spalding')


def setup(name, speed, intensity, length):
    if name not in MODELS:
        raise ValueError(f'Unsupported turbulence_model {name}; choose one of {MODELS}')
    if any(not math.isfinite(v) or v <= 0 for v in (speed, intensity, length)):
        raise ValueError('Turbulence input scales must be positive finite values')
    k = 1.5 * (speed * intensity) ** 2
    fields = [('k', k, '[0 2 -2 0 0 0 0]', 'kqRWallFunction')]
    if name == 'kEpsilon':
        fields.append(('epsilon', .09 ** .75 * k ** 1.5 / length, '[0 2 -3 0 0 0 0]', 'epsilonWallFunction'))
        nut_wall, ras = 'nutkWallFunction', 'kEpsilon'
        description = 'standard kEpsilon velocity wall functions'
    else:
        fields.append(('omega', math.sqrt(k) / (.09 ** .25 * length), '[0 0 -1 0 0 0 0]', 'omegaWallFunction; blended true'))
        nut_wall, ras = 'nutUSpaldingWallFunction', 'kOmegaSST'
        description = 'kOmegaSST with continuous Spalding nut and blended omega wall function'
    fields.append(('nut', 0, '[0 2 -1 0 0 0 0]', nut_wall))
    fields.append(('alphat', 0, '[1 -1 -1 0 0 0 0]', 'compressible::alphatJayatillekeWallFunction; Prt 0.85'))
    return {'RASModel': ras, 'fields': fields, 'dissipation': 'epsilon' if name == 'kEpsilon' else 'omega',
            'description': description + ' + Jayatilleke thermal wall function'}
