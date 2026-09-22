import importlib.util
import math
import unittest
from pathlib import Path


MODULE_PATH = (Path(__file__).parents[1] / "klippy" / "extras" /
               "first_layer_squish.py")
SPEC = importlib.util.spec_from_file_location("first_layer_squish", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class GeometryTests(unittest.TestCase):
    def test_nine_squares_form_serpentine_three_by_three_grid(self):
        centers = MODULE.generate_square_centers(
            9, 30., 10., (0., 300., 0., 300.))
        self.assertEqual(centers, [
            (25., 25.), (150., 25.), (275., 25.),
            (275., 150.), (150., 150.), (25., 150.),
            (25., 275.), (150., 275.), (275., 275.),
        ])

    def test_partial_grid_returns_requested_count(self):
        centers = MODULE.generate_square_centers(
            5, 20., 5., (0., 200., 0., 200.))
        self.assertEqual(len(centers), 5)
        self.assertEqual(len(set(centers)), 5)

    def test_rejects_geometry_that_does_not_fit(self):
        with self.assertRaisesRegex(ValueError, "do not fit"):
            MODULE.generate_square_centers(
                9, 100., 10., (0., 100., 0., 100.))

    def test_extrusion_uses_requested_bead_volume_and_flow(self):
        value = MODULE.extrusion_for_distance(100., .48, .25, 1.75, 1.)
        expected = 100. * .48 * .25 / (math.pi * (.875 ** 2))
        self.assertTrue(math.isclose(value, expected))
        self.assertTrue(math.isclose(
            MODULE.extrusion_for_distance(100., .48, .25, 1.75, .9),
            expected * .9))

    def test_square_toolpath_finishes_raised_and_synchronised(self):
        calibration = object.__new__(MODULE.FirstLayerSquish)
        calibration.settings = {
            "size": 30., "layer_height": .25, "line_width": .48,
            "filament_diameter": 1.75, "flow": 1.,
        }
        calibration.z_hop = 2.
        calibration.z_speed = 10.
        calibration.travel_speed = 120.
        calibration.print_speed = 30.
        calibration.retract_length = .6
        calibration.retract_speed = 30.
        calibration.printed_count = 0
        gcode = calibration._square_gcode((100., 100.))
        self.assertIn("G1 X85.0000 Y85.0000", gcode)
        self.assertIn("G1 X115.0000 Y115.0000", gcode)
        self.assertTrue(gcode.endswith("G1 Z2.2500 F600.0\nM400"))


class _FakeReactor:
    def monotonic(self):
        return 123.456


class _FakePrintStats:
    def __init__(self):
        self.eventtime = None

    def get_status(self, eventtime):
        self.eventtime = eventtime
        return {"state": "standby"}


class _FakePrinter:
    def __init__(self, print_stats):
        self.print_stats = print_stats
        self.reactor = _FakeReactor()

    def lookup_object(self, name, default=None):
        if name == "print_stats":
            return self.print_stats
        return default

    def get_reactor(self):
        return self.reactor


class StatusCompatibilityTests(unittest.TestCase):
    def test_print_status_receives_a_real_eventtime(self):
        print_stats = _FakePrintStats()
        calibration = object.__new__(MODULE.FirstLayerSquish)
        calibration.printer = _FakePrinter(print_stats)
        calibration._validate_not_printing(None)
        self.assertEqual(print_stats.eventtime, 123.456)


if __name__ == "__main__":
    unittest.main()
