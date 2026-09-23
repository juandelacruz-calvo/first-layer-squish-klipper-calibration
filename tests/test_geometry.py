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

    def test_diagonal_infill_is_clipped_to_square(self):
        segments = MODULE.generate_infill_segments(
            (10., 40., 20., 50.), .48, 45.)
        self.assertGreater(len(segments), 30)
        for start, end in segments:
            for x_pos, y_pos in (start, end):
                self.assertGreaterEqual(x_pos, 10. - 1.e-7)
                self.assertLessEqual(x_pos, 40. + 1.e-7)
                self.assertGreaterEqual(y_pos, 20. - 1.e-7)
                self.assertLessEqual(y_pos, 50. + 1.e-7)
            self.assertAlmostEqual(
                abs(end[0] - start[0]), abs(end[1] - start[1]), places=7)

    def test_square_toolpath_finishes_raised_and_synchronised(self):
        calibration = object.__new__(MODULE.FirstLayerSquish)
        calibration.settings = {
            "size": 30., "layer_height": .25, "line_width": .48,
            "layer_count": 4, "filament_diameter": 1.75, "flow": 1.,
            "infill_angle": 45.,
        }
        calibration.z_hop = 2.
        calibration.z_speed = 10.
        calibration.travel_speed = 120.
        calibration.print_speed = 30.
        calibration.retract_length = .6
        calibration.retract_speed = 30.
        calibration.bounds = (0., 300., 0., 300.)
        calibration.margin = 10.
        calibration.printed_count = 0
        gcode = calibration._square_gcode(
            (100., 100.), next_center=(200., 200.))
        self.assertIn("G1 X85.0000 Y85.0000", gcode)
        self.assertIn("G1 X115.0000 Y115.0000", gcode)
        self.assertIn("G1 Z0.2500 F600.0", gcode)
        self.assertIn("G1 Z1.0000 F600.0", gcode)
        self.assertTrue(gcode.endswith(
            "G1 Z3.0000 F600.0\nG1 X185.0000 Y185.0000 F7200.0\nM400"))

    def test_final_square_parks_at_front_of_bed(self):
        calibration = object.__new__(MODULE.FirstLayerSquish)
        calibration.settings = {"size": 30.}
        calibration.bounds = (0., 300., 0., 300.)
        calibration.margin = 10.
        self.assertEqual(calibration._inspection_position(None), (150., 5.))


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


class _FakeConfigError(Exception):
    pass


class _FakeGCode:
    def __init__(self):
        self.commands = {}

    def register_command(self, name, callback, desc=None):
        if callback is None:
            return self.commands.pop(name, None)
        if name in self.commands:
            raise _FakeConfigError(name)
        self.commands[name] = callback

    def error(self, message):
        return RuntimeError(message)


class _FakeManualProbe:
    def __init__(self):
        self.status = {}

    def reset_status(self):
        self.status = {"is_active": False}


class ManualProbeUiTests(unittest.TestCase):
    def test_activation_publishes_status_and_commands(self):
        calibration = object.__new__(MODULE.FirstLayerSquish)
        calibration.gcode = _FakeGCode()
        calibration.manual_probe = _FakeManualProbe()
        calibration.printer = type(
            "FakePrinter", (), {"config_error": _FakeConfigError})()
        calibration.ui_active = False
        calibration.adjustment = -.02
        calibration.past_adjustments = [0., -.01]
        calibration._activate_manual_probe_ui()
        self.assertEqual(
            set(calibration.gcode.commands),
            {"ACCEPT", "NEXT", "ABORT", "TESTZ"})
        self.assertTrue(calibration.manual_probe.status["is_active"])
        self.assertEqual(calibration.manual_probe.status["z_position"], -.02)
        self.assertEqual(
            calibration.manual_probe.status["z_position_upper"], -.01)
        calibration._deactivate_manual_probe_ui()
        self.assertFalse(calibration.gcode.commands)
        self.assertFalse(calibration.manual_probe.status["is_active"])

    def test_current_adjustment_is_recognised_as_already_printed(self):
        calibration = object.__new__(MODULE.FirstLayerSquish)
        calibration.samples = [
            {"square": 1, "adjustment": 0.},
            {"square": 2, "adjustment": -.02},
        ]
        calibration.adjustment = -.02
        self.assertTrue(calibration._adjustment_has_printed_sample())
        calibration.adjustment = -.03
        self.assertFalse(calibration._adjustment_has_printed_sample())


if __name__ == "__main__":
    unittest.main()
