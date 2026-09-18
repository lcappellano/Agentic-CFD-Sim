"""Idealized reservoir-to-part pump budget from saved total pressures.

Total pressure already includes velocity head; do not add inlet velocity twice.
Equal elevations and specified reservoir reference pressures are explicit inputs.
Unknown external pipe/fitting losses remain outside this model.
"""
import argparse
import json
import math
from pathlib import Path

from src.foam.hashing import digest


def budget(inlet_total_Pa, outlet_total_Pa, tank_pressure_Pa,
           suction_reservoir_pressure_Pa, additional_loss_Pa=0.):
    values = [inlet_total_Pa, outlet_total_Pa, tank_pressure_Pa,
              suction_reservoir_pressure_Pa, additional_loss_Pa]
    if not all(math.isfinite(v) for v in values):
        raise ValueError('Pressure inputs must be finite')
    if min(tank_pressure_Pa, suction_reservoir_pressure_Pa) <= 0 or additional_loss_Pa < 0:
        raise ValueError('Reservoir absolute pressures must be positive; added losses nonnegative')
    return {
        'component_total_pressure_loss_Pa': inlet_total_Pa-outlet_total_Pa,
        'discharge_to_stationary_tank_loss_Pa': outlet_total_Pa-tank_pressure_Pa,
        'reservoir_pressure_difference_Pa': tank_pressure_Pa-suction_reservoir_pressure_Pa,
        'additional_modeled_loss_Pa': additional_loss_Pa,
        'idealized_required_pump_pressure_rise_Pa': inlet_total_Pa-suction_reservoir_pressure_Pa+additional_loss_Pa,
        'assumptions': ['Stationary suction and discharge reservoirs at equal elevation.',
                        'No discharge kinetic-energy recovery.',
                        'Only explicitly supplied external losses are included.'],
    }


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--summary',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--tank-pressure-Pa',type=float,required=True)
    parser.add_argument('--suction-reservoir-pressure-Pa',type=float,required=True)
    parser.add_argument('--additional-loss-Pa',type=float,default=0.)
    args=parser.parse_args()
    if args.output.exists():raise FileExistsError('Use a fresh versioned output')
    summary=json.loads(args.summary.read_text())
    ports=summary['mass_weighted_port_total_pressure_Pa']
    result=budget(ports['inlet'],ports['outlet'],args.tank_pressure_Pa,
                  args.suction_reservoir_pressure_Pa,args.additional_loss_Pa)
    result['input_sha256']={str(p):digest(p) for p in [args.summary,Path(__file__)]}
    result['source_iteration']=summary.get('latest_fields')
    args.output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
