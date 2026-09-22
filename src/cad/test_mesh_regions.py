"""Configuration guards: no Gmsh import or meshing required."""
import copy
import unittest
from src.cad.mesh_regions import validate_boxes, resolve_sizes


class RefinementConfigTests(unittest.TestCase):
    def setUp(self):
        self.box={'name':'gap','bounds_m':[-.028,.0009,-.0251,.028,.0021,.0251],'size_m':.0002,'transition_m':.0006}

    def test_valid_si_configuration(self):
        self.assertEqual(validate_boxes([self.box]),[self.box])

    def test_reject_reversed_or_flat_extent(self):
        for upper in (-.001,.0009):
            b=copy.deepcopy(self.box);b['bounds_m'][4]=upper
            with self.assertRaises(ValueError):validate_boxes([b])

    def test_reject_nonfinite_and_nonpositive_sizes(self):
        for v in (0,-1,float('nan'),float('inf'),True):
            with self.subTest(v=v):
                b={**self.box,'size_m':v}
                with self.assertRaises(ValueError):validate_boxes([b])

    def test_reject_misspelled_units_or_keys(self):
        for extra in ('size_mm','transition_mm','bounds_mm'):
            with self.assertRaises(ValueError):validate_boxes([{**self.box,extra:1}])

    def test_reject_bad_coordinates_and_transition(self):
        b={**self.box,'bounds_m':[0,0,float('nan'),1,1,1]}
        with self.assertRaises(ValueError):validate_boxes([b])
        with self.assertRaises(ValueError):validate_boxes([{**self.box,'transition_m':-1}])




class ProfileResolutionTests(unittest.TestCase):
    def test_relative_sizes_scale_with_inlet_diameter(self):
        profile = {'wall_size_per_diameter': .05, 'bulk_size_per_diameter': .2, 'transition_per_diameter': .2}
        settings = resolve_sizes(profile, .008)
        self.assertAlmostEqual(settings['wall_size_m'], .0004)
        self.assertAlmostEqual(settings['bulk_size_m'], .0016)
        self.assertAlmostEqual(settings['transition_distance_m'], .0016)

    def test_absolute_override_wins_and_bad_order_rejected(self):
        profile = {'wall_size_per_diameter': .05, 'bulk_size_per_diameter': .2, 'transition_per_diameter': .2}
        settings = resolve_sizes(profile, .008, {'wall_size_m': .0003})
        self.assertAlmostEqual(settings['wall_size_m'], .0003)
        with self.assertRaises(ValueError):
            resolve_sizes(profile, .008, {'wall_size_m': .01})

    def test_mesher_algorithm_threads_and_quality_floor(self):
        profile = {'wall_size_per_diameter': .05, 'bulk_size_per_diameter': .2, 'transition_per_diameter': .2}
        settings = resolve_sizes(profile, .008)
        self.assertEqual((settings['algorithm_3d'], settings['threads'], settings['optimize_netgen']), (1, 1, True))
        self.assertGreater(settings['min_quality'], 0)
        settings = resolve_sizes(profile, .008, {'algorithm_3d': 10, 'threads': 8, 'min_quality': .02, 'optimize_netgen': 0})
        self.assertEqual((settings['algorithm_3d'], settings['threads'], settings['min_quality'], settings['optimize_netgen']), (10, 8, .02, False))
        for bad in ({'algorithm_3d': 3}, {'threads': 0}, {'threads': 2.5}, {'threads': True}, {'min_quality': 1}, {'min_quality': -.1}):
            with self.assertRaises(ValueError):
                resolve_sizes(profile, .008, bad)


if __name__ == '__main__':
    unittest.main()
