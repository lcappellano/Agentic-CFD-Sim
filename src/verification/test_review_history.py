"""Synthetic SST history requires complete finite equation evidence."""
import json
from pathlib import Path
import tempfile
import unittest
from src.verification.review_history import review


class HistoryTests(unittest.TestCase):
    def run_fixture(self, omit=None, nan=False):
        with tempfile.TemporaryDirectory() as directory:
            case=Path(directory)
            (case/'settings.json').write_text(json.dumps({'turbulence_model':'kOmegaSST_spalding'}))
            audit={'time':'600','heated':{'maximum_K':300},'wetted_maximum_K':300,
                   'ports':{'inlet':{'signed_outward_mass_kg_s':-1},'outlet':{'signed_outward_mass_kg_s':1}}}
            criteria={'final_window_iterations':100,'temperature_range_K':.1,'pressure_drop_range_relative':.01,
                      'initial_residual_max':1e-5,'linear_final_residual_max':1e-7}
            for name,content in [('audit.json',audit),('criteria.json',criteria)]:
                (case/name).write_text(json.dumps(content))
            values={'heatedMax':300,'wettedMax':300,'inletPressure':2,'outletPressure':1,'inletMass':-1,
                    'outletMass':1,'heatedPower':1,'interfacePower':-1,'fluidPower':1}
            for name,value in values.items():
                path=case/'postProcessing'/'fluid'/name/'0'/'surfaceFieldValue.dat'
                path.parent.mkdir(parents=True)
                path.write_text(''.join(f'{t} {value}\n' for t in range(500,601,10)))
            lines=[]
            for t in range(500,601):
                lines.extend([f'Time = {t}','Solving for fluid region fluid'])
                for name in ['Ux','Uy','Uz','p_rgh','h','k','omega']:
                    if name=='omega' and t==omit:continue
                    initial='nan' if nan and name=='omega' and t==550 else '1e-8'
                    lines.append(f'Solver: Solving for {name}, Initial residual = {initial}, Final residual = 1e-10, No Iterations 1')
                lines.extend(['Solving for solid region solid','Solver: Solving for h, Initial residual = 1e-8, Final residual = 1e-10, No Iterations 1'])
            (case/'log.solver').write_text('Time = 10\n')
            (case/'log.solver.resume-600').write_text('\n'.join(lines))
            return review(case,case/'audit.json',case/'criteria.json')

    def test_complete_sst_uses_omega_not_epsilon(self):
        result=self.run_fixture()
        self.assertTrue(result['convergence_checks_pass'])
        self.assertIn('fluid:omega',result['final_window_residual_maxima'])
        self.assertNotIn('fluid:epsilon',result['final_window_residual_maxima'])

    def test_missing_iteration_and_nan_do_not_pass(self):
        for kwargs in ({'omit':550},{'nan':True}):
            result=self.run_fixture(**kwargs)
            self.assertFalse(result['convergence_checks_pass'])
            check=next(v for v in result['checks'] if v['check']=='residual_window:fluid:omega')
            self.assertEqual(check['status'],'fail')
