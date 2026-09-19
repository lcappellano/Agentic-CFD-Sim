"""Native transport selection and field-level property accounting."""
import copy
import json
import re
import unittest
from pathlib import Path

from src.cfd.transport import fluid_dictionary, solid_dictionary, conductivity_values, validate_polynomials
from src.cfd.cht_case import solid_solution, fluid_solution


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.basis = {'fluid_properties': {'density_kg_m3': 999.7, 'cp_J_kg_K': 4195., 'dynamic_viscosity_Pa_s': .0013,
                                           'conductivity_W_m_K': .58, 'molecular_weight': 18.015},
                      'solid_properties': {'density_kg_m3': 8920, 'cp_J_kg_K': 394, 'conductivity_W_m_K': 394, 'molecular_weight': 63.546}}
        self.spec = {'Tmin_K': 280., 'Tmax_K': 380., 'muCoeffs8': [.0013, 0, 0, 0, 0, 0, 0, 0], 'kappaCoeffs8': [.3, .001, 0, 0, 0, 0, 0, 0]}

    def test_constant_model_retained(self):
        text = fluid_dictionary(self.basis, 283.15)
        self.assertIn('transport const;', text)
        self.assertIn('rho 999.7;', text)
        self.assertNotIn('Coeffs', text)
        self.assertIn('kappa 394;', solid_dictionary(self.basis))

    def test_solid_enthalpy_is_solved_to_absolute_tolerance(self):
        text = solid_solution({'solid_nonorthogonal_correctors': 2, 'solid_enthalpy_relaxation': 1.0})
        self.assertIn('relTol 0;', text)
        self.assertIn('h 1.0;', text)
        fluid = fluid_solution({'pressure_relaxation': .3, 'velocity_relaxation': .5, 'fluid_enthalpy_relaxation': 1.0})
        self.assertIn('h 1.0;', fluid)

    def test_laminar_profile_uses_unlimited_solid_gradient(self):
        # cellLimited feeds the non-orthogonal correction a clipped gradient and floors the solid
        # h initial residual near 2e-3 on tet meshes; Gauss linear converged the same field to 1e-10.
        profiles = json.loads(Path(__file__).resolve().parents[1].joinpath('pipeline/profiles/numerics.json').read_text())
        self.assertEqual(profiles['profiles']['laminar']['solid_gradient'], 'Gauss linear')

    def test_transport_changes_without_density_or_cp_change(self):
        self.basis['transport_polynomials'] = self.spec
        text = fluid_dictionary(self.basis, 283.15)
        self.assertIn('transport polynomial;', text)
        self.assertIn('thermo hPolynomial;', text)
        self.assertIn('CpCoeffs<8> (4195 0 0 0 0 0 0 0);', text)
        density = [float(v) for v in re.search(r'rhoCoeffs<8>\s*\(([^)]+)\)', text).group(1).split()]
        self.assertEqual(density, [999.7] + [0.] * 7)

    def test_negative_transport_inside_fit_is_rejected(self):
        spec = copy.deepcopy(self.spec)
        spec['muCoeffs8'] = [.003, -.00001, 0, 0, 0, 0, 0, 0]
        with self.assertRaises(ValueError):
            validate_polynomials(spec)

    def test_bad_range_and_nonfinite_coefficient_rejected(self):
        spec = copy.deepcopy(self.spec)
        spec['Tmin_K'] = 400
        with self.assertRaises(ValueError):
            validate_polynomials(spec)
        spec = copy.deepcopy(self.spec)
        spec['muCoeffs8'][0] = float('nan')
        with self.assertRaises(ValueError):
            validate_polynomials(spec)
        with self.assertRaises(ValueError):
            validate_polynomials(self.spec, 500)

    def test_port_conductivity_uses_saved_face_temperature(self):
        values = conductivity_values({'transport_polynomials': self.spec}, [280, 380])
        self.assertAlmostEqual(values[0], .58)
        self.assertAlmostEqual(values[1], .68)
        with self.assertRaises(ValueError):
            conductivity_values({'transport_polynomials': self.spec}, [400])
        self.assertEqual(conductivity_values({'k_W_m_K': .58}, [280, 400]), [.58, .58])


if __name__ == '__main__':
    unittest.main()
