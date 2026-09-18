"""Analytic section geometry and constant-vector flux reference tests."""
import unittest
from src.verification.channel_flows import tetra_cut, area, clip_bin, integrate


class ChannelFlowsTests(unittest.TestCase):
    def test_triangle_cut_and_constant_vector_flux(self):
        vertices=[(0,0,0),(1,0,0),(0,1,0),(0,0,1)]
        self.assertAlmostEqual(area(tetra_cut(vertices,.5)),.125)
        channel={'id':'a','x_m':.5,'y_bounds_m':[0,1],'z_bounds_m':[0,1],'positive_flow_normal':[-1,0,0]}
        result=integrate([vertices],[(-2,7,8)],[channel],1000.)
        self.assertAlmostEqual(result['sum_mass_flow_kg_s'],250.)
        self.assertAlmostEqual(result['channels'][0]['area_m2'],.125)
        self.assertEqual(result['channels'][0]['reversed_mass_flow_kg_s'],0.)
        self.assertAlmostEqual(result['unclassified_cut_area_m2'],0.)

    def test_quadrilateral_cut_and_bin_partition(self):
        vertices=[(-1,0,0),(-1,1,1),(1,0,1),(1,1,0)]
        cut=tetra_cut(vertices,0)
        self.assertEqual(len(cut),4)
        self.assertAlmostEqual(area(cut),.5)
        self.assertAlmostEqual(area(clip_bin(cut,[0,.5],[0,1])),.25)
        self.assertAlmostEqual(area(clip_bin(cut,[.5,1],[0,1])),.25)
        self.assertEqual(area(clip_bin(cut,[2,3],[0,1])),0.)

    def test_coincident_shared_face_counted_once(self):
        face=[(0,0,0),(0,1,0),(0,0,1)]
        self.assertAlmostEqual(area(tetra_cut(face+[(-1,0,0)],0)),.5)
        self.assertEqual(area(tetra_cut(face+[(1,0,0)],0)),0.)
        self.assertEqual(area(tetra_cut([(0,0,0),(-1,0,0),(-1,1,0),(-1,0,1)],0)),0.)

    def test_reverse_flow_missing_coverage_and_overlap(self):
        vertices=[(-1,0,0),(-1,1,1),(1,0,1),(1,1,0)]
        c={'id':'a','x_m':0,'y_bounds_m':[0,.5],'z_bounds_m':[0,1],'positive_flow_normal':[-1,0,0]}
        result=integrate([vertices],[(2,0,0)],[c],1000.)
        self.assertAlmostEqual(result['sum_mass_flow_kg_s'],-500.)
        self.assertAlmostEqual(result['channels'][0]['reversed_mass_flow_kg_s'],500.)
        self.assertAlmostEqual(result['unclassified_cut_area_m2'],.25)
        with self.assertRaises(ValueError):integrate([vertices],[(2,0,0)],[c,dict(c,id='b')],1000.)


if __name__=='__main__':unittest.main()
