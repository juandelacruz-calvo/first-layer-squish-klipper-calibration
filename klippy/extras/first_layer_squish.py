# Interactive first-layer squish calibration for Klipper
#
# Copyright (C) 2026  First Layer Squish contributors
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import math


STATE_NAME = "FIRST_LAYER_SQUISH_STATE"
SUPPORTED_KINEMATICS = ("cartesian", "corexy")


def _linspace(start, end, count):
    if count <= 1:
        return [(start + end) * .5]
    step = (end - start) / float(count - 1)
    return [start + step * index for index in range(count)]


def generate_square_centers(count, size, margin, bounds):
    """Return a compact serpentine grid of square center coordinates."""
    x_min, x_max, y_min, y_max = bounds
    columns = int(math.ceil(math.sqrt(count)))
    rows = int(math.ceil(float(count) / columns))
    center_x_min = x_min + margin + size * .5
    center_x_max = x_max - margin - size * .5
    center_y_min = y_min + margin + size * .5
    center_y_max = y_max - margin - size * .5
    if center_x_min > center_x_max or center_y_min > center_y_max:
        raise ValueError("squares and margins do not fit inside the bed")
    xs = _linspace(center_x_min, center_x_max, columns)
    ys = _linspace(center_y_min, center_y_max, rows)
    result = []
    for row, y_pos in enumerate(ys):
        row_xs = xs if row % 2 == 0 else list(reversed(xs))
        for x_pos in row_xs:
            if len(result) == count:
                return result
            result.append((x_pos, y_pos))
    return result


def extrusion_for_distance(distance, line_width, layer_height,
                           filament_diameter, flow):
    filament_area = math.pi * (filament_diameter * .5) ** 2
    volume = distance * line_width * layer_height
    return volume / filament_area * flow


class FirstLayerSquish:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.gcode = self.printer.lookup_object("gcode")
        gcode_macro = self.printer.load_object(config, "gcode_macro")
        self.gcode_macro = gcode_macro

        printer_config = config.getsection("printer")
        self.kinematics = printer_config.get("kinematics").lower()
        if self.kinematics not in SUPPORTED_KINEMATICS:
            raise config.error(
                "first_layer_squish currently supports only cartesian and "
                "corexy kinematics")

        x_config = config.getsection("stepper_x")
        y_config = config.getsection("stepper_y")
        self.bounds = (
            x_config.getfloat("position_min", 0., note_valid=False),
            x_config.getfloat("position_max", note_valid=False),
            y_config.getfloat("position_min", 0., note_valid=False),
            y_config.getfloat("position_max", note_valid=False),
        )
        if self.bounds[0] >= self.bounds[1] or self.bounds[2] >= self.bounds[3]:
            raise config.error("Invalid X/Y travel limits for first_layer_squish")

        extruder_config = config.getsection("extruder")
        nozzle_diameter = extruder_config.getfloat(
            "nozzle_diameter", .4, above=0., note_valid=False)
        self.default_count = config.getint("square_count", 9, minval=1,
                                           maxval=25)
        self.default_size = config.getfloat("square_size", 30., above=0.)
        self.default_height = config.getfloat("layer_height", .25, above=0.)
        self.default_width = config.getfloat(
            "line_width", nozzle_diameter * 1.2, above=0.)
        self.default_flow = config.getfloat("flow", 1., above=0.)
        self.filament_diameter = config.getfloat(
            "filament_diameter",
            extruder_config.getfloat("filament_diameter", 1.75, above=0.,
                                     note_valid=False), above=0.)
        self.margin = config.getfloat("bed_margin", 10., minval=0.)
        self.print_speed = config.getfloat("print_speed", 30., above=0.)
        self.travel_speed = config.getfloat("travel_speed", 120., above=0.)
        self.z_speed = config.getfloat("z_speed", 10., above=0.)
        self.retract_length = config.getfloat("retract_length", .6, minval=0.)
        self.retract_speed = config.getfloat("retract_speed", 30., above=0.)
        self.z_hop = config.getfloat("z_hop", 2., minval=0.)
        self.max_adjustment = config.getfloat("max_adjustment", .5, above=0.)
        self.bed_temp = config.getfloat("bed_temp", 60., minval=0.)
        self.extruder_temp = config.getfloat("extruder_temp", 200., minval=0.)
        self.apply_method = config.getchoice(
            "apply_method", {"auto": "auto", "probe": "probe",
                             "endstop": "endstop"}, default="auto")

        default_start = """
M140 S{bed_temp}
M104 S{extruder_temp}
G28
M190 S{bed_temp}
M109 S{extruder_temp}
"""
        self.start_template = gcode_macro.load_template(
            config, "start_gcode", default_start)
        self.end_template = gcode_macro.load_template(
            config, "end_gcode", "TURN_OFF_HEATERS")

        self.state = "inactive"
        self.centers = []
        self.samples = []
        self.printed_count = 0
        self.adjustment = 0.
        self.initial_offset = 0.
        self.state_saved = False
        self.settings = {}

        commands = (
            ("_FIRST_LAYER_SQUISH_START", self.cmd_start,
             "Start interactive first-layer squish calibration"),
            ("_FIRST_LAYER_SQUISH_ADJUST", self.cmd_adjust,
             "Adjust Z for the next first-layer square"),
            ("_FIRST_LAYER_SQUISH_NEXT", self.cmd_next,
             "Print the next first-layer square"),
            ("_FIRST_LAYER_SQUISH_SELECT", self.cmd_select,
             "Select the Z adjustment used for a printed square"),
            ("_FIRST_LAYER_SQUISH_ACCEPT", self.cmd_accept,
             "Apply and save the selected first-layer Z offset"),
            ("_FIRST_LAYER_SQUISH_ABORT", self.cmd_abort,
             "Abort first-layer squish calibration"),
        )
        for name, callback, description in commands:
            self.gcode.register_command(name, callback, desc=description)

    def get_status(self, eventtime):
        return {
            "is_active": self.state != "inactive",
            "state": self.state,
            "printed_count": self.printed_count,
            "square_count": len(self.centers),
            "adjustment": self.adjustment,
            "initial_offset": self.initial_offset,
            "samples": [dict(sample) for sample in self.samples],
        }

    def _require_active(self, gcmd):
        if self.state == "inactive":
            raise gcmd.error("No first-layer squish calibration is active")

    def _template_context(self, parameters):
        context = self.gcode_macro.create_template_context()
        context.update(parameters)
        context["params"] = dict(parameters)
        return context

    def _run_template(self, template, parameters):
        script = template.render(self._template_context(parameters))
        if script.strip():
            self.gcode.run_script_from_command(script)

    def _current_offset(self):
        gcode_move = self.printer.lookup_object("gcode_move")
        return gcode_move.get_status()["homing_origin"].z

    def _resolve_apply_method(self):
        if self.apply_method != "auto":
            return self.apply_method
        configfile = self.printer.lookup_object("configfile")
        status = configfile.get_status(None)["config"]
        stepper_z = status.get("stepper_z", {})
        if "position_endstop" in stepper_z:
            return "endstop"
        if "probe" in status or "bltouch" in status:
            return "probe"
        raise self.printer.command_error(
            "Unable to select an offset apply method; set apply_method to "
            "probe or endstop")

    def _validate_not_printing(self, gcmd):
        print_stats = self.printer.lookup_object("print_stats", None)
        if print_stats is None:
            return
        eventtime = self.printer.get_reactor().monotonic()
        print_state = print_stats.get_status(eventtime).get("state", "standby")
        if print_state in ("printing", "paused"):
            raise gcmd.error(
                "First-layer squish calibration cannot start during a print")

    def cmd_start(self, gcmd):
        if self.state != "inactive":
            raise gcmd.error("A first-layer squish calibration is active")
        self._validate_not_printing(gcmd)

        settings = {
            "count": gcmd.get_int("COUNT", self.default_count,
                                  minval=1, maxval=25),
            "size": gcmd.get_float("SIZE", self.default_size, above=0.),
            "layer_height": gcmd.get_float(
                "LAYER_HEIGHT", self.default_height, above=0.),
            "line_width": gcmd.get_float(
                "LINE_WIDTH", self.default_width, above=0.),
            "flow": gcmd.get_float("FLOW", self.default_flow, above=0.),
            "filament_diameter": gcmd.get_float(
                "FILAMENT_DIAMETER", self.filament_diameter, above=0.),
            "bed_temp": gcmd.get_float("BED_TEMP", self.bed_temp, minval=0.),
            "extruder_temp": gcmd.get_float(
                "EXTRUDER_TEMP", self.extruder_temp, minval=0.),
        }
        try:
            centers = generate_square_centers(
                settings["count"], settings["size"], self.margin, self.bounds)
        except ValueError as error:
            raise gcmd.error(str(error))

        self.state = "starting"
        self.settings = settings
        self.centers = centers
        self.samples = []
        self.printed_count = 0
        self.adjustment = 0.
        try:
            self._run_template(self.start_template, settings)
            toolhead = self.printer.lookup_object("toolhead")
            eventtime = self.printer.get_reactor().monotonic()
            homed_axes = toolhead.get_status(eventtime).get("homed_axes", "")
            if not all(axis in homed_axes for axis in "xyz"):
                raise gcmd.error(
                    "The start_gcode must home X, Y, and Z before calibration")
            self.initial_offset = self._current_offset()
            self.gcode.run_script_from_command(
                "SAVE_GCODE_STATE NAME=%s" % (STATE_NAME,))
            self.state_saved = True
            self.state = "waiting"
            self._print_next_square(gcmd)
        except Exception:
            if self.state_saved:
                try:
                    self._restore_gcode_state(False)
                except Exception:
                    pass
            self._reset_state()
            raise

    def _move_line(self, commands, x_pos, y_pos, distance):
        settings = self.settings
        extrusion = extrusion_for_distance(
            distance, settings["line_width"], settings["layer_height"],
            settings["filament_diameter"], settings["flow"])
        commands.append("G1 X%.4f Y%.4f E%.5f F%.1f" % (
            x_pos, y_pos, extrusion, self.print_speed * 60.))

    def _square_gcode(self, center):
        settings = self.settings
        half_size = settings["size"] * .5
        x0, x1 = center[0] - half_size, center[0] + half_size
        y0, y1 = center[1] - half_size, center[1] + half_size
        safe_z = settings["layer_height"] + self.z_hop
        commands = [
            "G90", "M83", "G1 Z%.4f F%.1f" % (safe_z, self.z_speed * 60.),
            "G1 X%.4f Y%.4f F%.1f" % (x0, y0, self.travel_speed * 60.),
            "G1 Z%.4f F%.1f" % (
                settings["layer_height"], self.z_speed * 60.),
        ]
        if self.printed_count:
            commands.append("G1 E%.5f F%.1f" % (
                self.retract_length, self.retract_speed * 60.))

        self._move_line(commands, x1, y0, settings["size"])
        self._move_line(commands, x1, y1, settings["size"])
        self._move_line(commands, x0, y1, settings["size"])
        self._move_line(commands, x0, y0, settings["size"])

        inset = settings["line_width"]
        infill_x0, infill_x1 = x0 + inset, x1 - inset
        usable_height = max(0., settings["size"] - 2. * inset)
        line_count = max(1, int(math.floor(
            usable_height / settings["line_width"])) + 1)
        y_positions = _linspace(y0 + inset, y1 - inset, line_count)
        for index, y_pos in enumerate(y_positions):
            if index % 2 == 0:
                start_x, end_x = infill_x0, infill_x1
            else:
                start_x, end_x = infill_x1, infill_x0
            commands.append("G1 X%.4f Y%.4f F%.1f" % (
                start_x, y_pos, self.print_speed * 60.))
            self._move_line(commands, end_x, y_pos,
                            max(0., infill_x1 - infill_x0))

        if self.retract_length:
            commands.append("G1 E-%.5f F%.1f" % (
                self.retract_length, self.retract_speed * 60.))
        commands.extend((
            "G1 Z%.4f F%.1f" % (safe_z, self.z_speed * 60.), "M400"))
        return "\n".join(commands)

    def _print_next_square(self, gcmd):
        if self.printed_count >= len(self.centers):
            raise gcmd.error("All first-layer squares have been printed")
        square_number = self.printed_count + 1
        self.state = "printing"
        self.gcode.run_script_from_command(
            self._square_gcode(self.centers[self.printed_count]))
        self.samples.append({"square": square_number,
                             "adjustment": self.adjustment})
        self.printed_count = square_number
        self.state = ("complete" if self.printed_count == len(self.centers)
                      else "waiting")
        if self.state == "complete":
            gcmd.respond_info(
                "Square %d/%d printed at Z adjustment %+.3f. Select a "
                "square if needed, then run SQUISH_ACCEPT or SQUISH_ABORT."
                % (square_number, len(self.centers), self.adjustment))
        else:
            gcmd.respond_info(
                "Square %d/%d printed at Z adjustment %+.3f. Adjust Z, then "
                "run SQUISH_NEXT." % (
                    square_number, len(self.centers), self.adjustment))

    def cmd_adjust(self, gcmd):
        self._require_active(gcmd)
        if self.state == "printing":
            raise gcmd.error("Wait for the square to finish before adjusting Z")
        delta = gcmd.get_float("Z")
        new_adjustment = self.adjustment + delta
        if abs(new_adjustment) > self.max_adjustment + 1.e-9:
            raise gcmd.error(
                "Requested adjustment exceeds max_adjustment (%.3f)"
                % (self.max_adjustment,))
        self.gcode.run_script_from_command(
            "SET_GCODE_OFFSET Z_ADJUST=%.6f MOVE=1 MOVE_SPEED=%.3f"
            % (delta, self.z_speed))
        self.adjustment = new_adjustment
        gcmd.respond_info(
            "First-layer Z adjustment: %+.3f (negative is more squish)"
            % (self.adjustment,))

    def cmd_next(self, gcmd):
        self._require_active(gcmd)
        if self.state != "waiting":
            if self.state == "complete":
                raise gcmd.error(
                    "All squares are printed; select, accept, or abort")
            raise gcmd.error("The calibration is not ready for the next square")
        self._print_next_square(gcmd)

    def cmd_select(self, gcmd):
        self._require_active(gcmd)
        square_number = gcmd.get_int("SQUARE", minval=1)
        if square_number > len(self.samples):
            raise gcmd.error("That square has not been printed")
        selected = self.samples[square_number - 1]["adjustment"]
        delta = selected - self.adjustment
        if abs(delta) > 1.e-9:
            self.gcode.run_script_from_command(
                "SET_GCODE_OFFSET Z_ADJUST=%.6f MOVE=1 MOVE_SPEED=%.3f"
                % (delta, self.z_speed))
        self.adjustment = selected
        gcmd.respond_info(
            "Selected square %d with Z adjustment %+.3f"
            % (square_number, self.adjustment))

    def _restore_gcode_state(self, keep_adjustment):
        self.gcode.run_script_from_command(
            "RESTORE_GCODE_STATE NAME=%s" % (STATE_NAME,))
        if keep_adjustment and abs(self.adjustment) > 1.e-9:
            self.gcode.run_script_from_command(
                "SET_GCODE_OFFSET Z_ADJUST=%.6f MOVE=0" % (self.adjustment,))

    def cmd_accept(self, gcmd):
        self._require_active(gcmd)
        if not self.samples:
            raise gcmd.error("No first-layer square has been printed")
        self.state = "saving"
        parameters = dict(self.settings)
        parameters["adjustment"] = self.adjustment
        try:
            self._restore_gcode_state(True)
            self._run_template(self.end_template, parameters)
            method = self._resolve_apply_method()
            apply_command = ("Z_OFFSET_APPLY_PROBE" if method == "probe"
                             else "Z_OFFSET_APPLY_ENDSTOP")
            gcmd.respond_info(
                "Accepting first-layer Z adjustment %+.3f using %s. "
                "Klipper will restart after SAVE_CONFIG."
                % (self.adjustment, apply_command))
            self.gcode.run_script_from_command(
                "%s\nSAVE_CONFIG" % (apply_command,))
        except Exception:
            self.state = "complete"
            raise

    def cmd_abort(self, gcmd):
        self._require_active(gcmd)
        parameters = dict(self.settings)
        parameters["adjustment"] = self.adjustment
        try:
            self._restore_gcode_state(False)
            self._run_template(self.end_template, parameters)
        finally:
            self._reset_state()
        gcmd.respond_info(
            "First-layer squish calibration aborted; Z offset restored")

    def _reset_state(self):
        self.state = "inactive"
        self.centers = []
        self.samples = []
        self.printed_count = 0
        self.adjustment = 0.
        self.initial_offset = 0.
        self.state_saved = False
        self.settings = {}


def load_config(config):
    return FirstLayerSquish(config)
