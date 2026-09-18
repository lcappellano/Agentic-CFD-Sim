import unittest
from src.thermal.pump_budget import budget


class PumpBudgetTests(unittest.TestCase):
    def test_reservoir_balance_includes_discharge_head_once(self):
        result=budget(300000,120000,100000,100000,20000)
        self.assertEqual(result['component_total_pressure_loss_Pa'],180000)
        self.assertEqual(result['discharge_to_stationary_tank_loss_Pa'],20000)
        self.assertEqual(result['idealized_required_pump_pressure_rise_Pa'],220000)
        self.assertEqual(sum(result[key] for key in [
            'component_total_pressure_loss_Pa','discharge_to_stationary_tank_loss_Pa',
            'reservoir_pressure_difference_Pa','additional_modeled_loss_Pa']),220000)

    def test_invalid_reference_or_loss_rejected(self):
        for tank, loss in [(0,0),(100000,-1),(float('nan'),0)]:
            with self.assertRaises(ValueError):budget(300000,120000,tank,100000,loss)

if __name__=='__main__':unittest.main()
