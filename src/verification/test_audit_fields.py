"""Parser and local phase-screen safeguards; synthetic data only."""
from pathlib import Path
import tempfile
import unittest
from src.thermal.saturation import saturation_pressure
from src.verification.audit_fields import (phase_screen, transport_at, transport_screen, transport_spec,
                                           thermo_declaration_check)
from src.verification.independent_reader import Mesh, field_values, vector_area


class AuditFieldTests(unittest.TestCase):
    def test_saved_value_is_not_value_fraction(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'T'
            path.write_text('FoamFile {format ascii;} dimensions [0 0 0 1 0 0 0]; '
                            'internalField uniform 300; boundaryField { interface { type mixed; '
                            'valueFraction uniform 0.4; refValue uniform 400; value uniform 350; }}')
            mesh = Mesh.__new__(Mesh)
            mesh.hashes = {}
            mesh.patches = {'interface': {'indices': range(2)}}
            self.assertEqual(mesh.read(path, 'interface', [0,0,0,1,0,0,0]), [350,350])

    def test_nonuniform_count_and_nonfinite_values_rejected(self):
        with self.assertRaises(ValueError):
            field_values('nonuniform List<scalar> 2 (1 2);', 3)
        with self.assertRaises(ValueError):
            field_values('uniform nan;', 2)

    def test_uniform_vector_and_nonuniform_scalar(self):
        self.assertEqual(field_values('uniform (1 2 3);', 2), [(1,2,3),(1,2,3)])
        self.assertEqual(field_values('nonuniform List<scalar> 2 (310 320);', 2), [310,320])

    def test_area_orientation_is_not_assumed_from_patch_name(self):
        triangle = [(0,0,0), (0,2,0), (0,0,2)]
        self.assertEqual(vector_area(triangle), [2,0,0])
        self.assertEqual(vector_area(list(reversed(triangle))), [-2,0,0])

    def test_saturation_endpoints_and_normal_boiling_reference(self):
        self.assertAlmostEqual(saturation_pressure(273.16), 611.657, places=2)
        self.assertEqual(saturation_pressure(647.096), 22064000)
        self.assertAlmostEqual(saturation_pressure(373.1243), 101325, delta=1)
        with self.assertRaises(ValueError):
            saturation_pressure(700)

    def test_phase_screen_uses_colocated_temperature_and_pressure(self):
        local = phase_screen([350,400], [101325,1000000], 10)
        self.assertEqual(local['status'], 'pass')
        wrong_pair = phase_screen([400], [101325], 10)
        self.assertEqual(wrong_pair['status'], 'fail')

    def test_missing_out_of_domain_and_overheated_evidence_never_pass(self):
        self.assertEqual(phase_screen([],[])['status'], 'fail')
        self.assertEqual(phase_screen([300],[-1])['status'], 'fail')
        self.assertEqual(phase_screen([700],[101325])['status'], 'fail')
        self.assertEqual(phase_screen([380],[101325])['status'], 'fail')
        with self.assertRaises(ValueError):
            phase_screen([300,310],[101325])

    def test_ten_kelvin_margin_failure_does_not_imply_supersaturation(self):
        # 370 K is below atmospheric saturation but less than 10 K below it.
        self.assertEqual(phase_screen([370],[101325],10)['violations'], 1)
        self.assertEqual(phase_screen([370],[101325],0)['violations'], 0)

    @staticmethod
    def polynomial_settings():
        return {'transport_model': 'polynomial', 'rho_kg_m3': 998., 'cp_J_kg_K': 4200.,
                'mu_Pa_s': .001, 'k_W_m_K': 999., 'transport_polynomials': {
                    'muCoeffs8': [.003, -5e-6] + [0.] * 6,
                    'kappaCoeffs8': [.1, .001, 1e-6] + [0.] * 5,
                    'Tmin_K': 280., 'Tmax_K': 450.}}

    def test_polynomial_uses_ascending_kelvin_coefficients_not_reference_k(self):
        settings = self.polynomial_settings()
        transport_spec(settings)
        mu, kappa = transport_at(settings, 300.)
        self.assertAlmostEqual(mu, .0015)
        self.assertAlmostEqual(kappa, .49)
        self.assertEqual(transport_at({'mu_Pa_s': .002, 'k_W_m_K': .6}, 300.), (.002, .6))

    def test_polynomial_extrapolation_and_nonpositive_values_fail(self):
        settings = self.polynomial_settings()
        screen = transport_screen(settings, {'bulk': [300.], 'wetted': [500.]})
        self.assertEqual(screen['status'], 'fail')
        self.assertEqual(screen['groups']['wetted']['invalid_or_outside_fit_locations'], 1)
        with self.assertRaises(ValueError):
            transport_at(settings, 500.)
        settings['transport_polynomials']['kappaCoeffs8'] = [-1.] + [0.] * 7
        with self.assertRaises(ValueError):
            transport_at(settings, 300.)

    def test_polynomial_model_mismatch_and_malformed_coefficients_reject(self):
        settings = self.polynomial_settings()
        settings['transport_model'] = 'constant'
        with self.assertRaises(ValueError):
            transport_spec(settings)
        settings['transport_model'] = 'polynomial'
        settings['transport_polynomials']['muCoeffs8'][0] = True
        with self.assertRaises(ValueError):
            transport_spec(settings)

    def test_dictionary_requires_constant_cp_rho_and_exact_transport_coefficients(self):
        settings = self.polynomial_settings()
        dictionary = '''thermoType {transport polynomial; thermo hPolynomial; equationOfState icoPolynomial;}
            rhoCoeffs<8> (998 0 0 0 0 0 0 0); CpCoeffs<8> (4200 0 0 0 0 0 0 0);
            muCoeffs<8> (.003 -5e-6 0 0 0 0 0 0); kappaCoeffs<8> (.1 .001 1e-6 0 0 0 0 0);'''
        self.assertEqual(thermo_declaration_check(settings, dictionary)['status'], 'pass')
        wrong_cp = dictionary.replace('(4200 0', '(4200 1')
        self.assertEqual(thermo_declaration_check(settings, wrong_cp)['status'], 'fail')
        wrong_k = dictionary.replace('(.1 .001', '(.2 .001')
        self.assertEqual(thermo_declaration_check(settings, wrong_k)['status'], 'fail')


if __name__ == '__main__':
    unittest.main(verbosity=2)
