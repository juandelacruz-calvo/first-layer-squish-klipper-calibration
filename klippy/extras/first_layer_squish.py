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


def generate_wipe_points(center, square_size, line_length, line_count,
                         line_spacing, gap, line_width, bounds):
    """Return a connected purge strip adjacent to a calibration square."""
    if line_length <= 0. or line_count <= 0:
        return []
    x_min, x_max, y_min, y_max = bounds
    bead_radius = line_width * .5
    usable_x_min = x_min + bead_radius
    usable_x_max = x_max - bead_radius
    if line_length > usable_x_max - usable_x_min:
        raise ValueError("wipe line does not fit inside the X travel limits")

    start_x = center[0] - line_length * .5
    start_x = min(max(start_x, usable_x_min),
                  usable_x_max - line_length)
    end_x = start_x + line_length
    square_y_min = center[1] - square_size * .5
    square_y_max = center[1] + square_size * .5
    strip_width = line_spacing * (line_count - 1)

    below_y = square_y_min - gap
    above_y = square_y_max + gap
    if below_y - strip_width - bead_radius >= y_min:
        first_y = below_y
        y_direction = -1.
    elif above_y + strip_width + bead_radius <= y_max:
        first_y = above_y
        y_direction = 1.
    else:
        raise ValueError(
            "wipe line does not fit beside a calibration square; increase "
            "bed_margin or reduce WIPE_LINES, WIPE_SPACING, or WIPE_GAP")

    points = [(start_x, first_y)]
    current_x = start_x
    for line_index in range(line_count):
        current_y = first_y + y_direction * line_spacing * line_index
        target_x = end_x if line_index % 2 == 0 else start_x
        if line_index:
            points.append((current_x, current_y))
        points.append((target_x, current_y))
        current_x = target_x
    return points


def generate_infill_segments(bounds, spacing, angle):
    """Clip evenly-spaced parallel lines to a rectangular boundary."""
    x_min, x_max, y_min, y_max = bounds
    radians = math.radians(angle % 180.)
    direction_x, direction_y = math.cos(radians), math.sin(radians)
    normal_x, normal_y = -direction_y, direction_x
    corners = ((x_min, y_min), (x_min, y_max),
               (x_max, y_min), (x_max, y_max))
    projections = [x_pos * normal_x + y_pos * normal_y
                   for x_pos, y_pos in corners]
    projection_min = min(projections) + spacing * .5
    projection_max = max(projections) - spacing * .5
    if projection_min > projection_max:
        return []

    segments = []
    projection = projection_min
    epsilon = 1.e-8
    while projection <= projection_max + epsilon:
        origin_x = normal_x * projection
        origin_y = normal_y * projection
        intersections = []
        if abs(direction_x) > epsilon:
            for x_pos in (x_min, x_max):
                distance = (x_pos - origin_x) / direction_x
                y_pos = origin_y + distance * direction_y
                if y_min - epsilon <= y_pos <= y_max + epsilon:
                    intersections.append((distance, x_pos, y_pos))
        if abs(direction_y) > epsilon:
            for y_pos in (y_min, y_max):
                distance = (y_pos - origin_y) / direction_y
                x_pos = origin_x + distance * direction_x
                if x_min - epsilon <= x_pos <= x_max + epsilon:
                    intersections.append((distance, x_pos, y_pos))

        intersections.sort()
        unique = []
        for item in intersections:
            if not unique or abs(item[0] - unique[-1][0]) > epsilon:
                unique.append(item)
        if len(unique) >= 2:
            start, end = unique[0], unique[-1]
            segments.append(((start[1], start[2]), (end[1], end[2])))
        projection += spacing
    return segments


class FirstLayerSquish:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.gcode = self.printer.lookup_object("gcode")
        gcode_macro = self.printer.load_object(config, "gcode_macro")
        self.gcode_macro = gcode_macro
        self.manual_probe = self.printer.load_object(config, "manual_probe")

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
        self.default_size = config.getfloat("square_size", 20., above=0.)
        self.default_layer_count = config.getint(
            "layer_count", 4, minval=3, maxval=20)
        self.default_height = config.getfloat("layer_height", .25, above=0.)
        self.default_width = config.getfloat(
            "line_width", nozzle_diameter * 1.2, above=0.)
        self.default_flow = config.getfloat("flow", 1., above=0.)
        self.default_infill_angle = config.getfloat("infill_angle", 45.)
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
        self.default_wipe_length = config.getfloat(
            "wipe_line_length", 40., minval=0.)
        self.default_wipe_lines = config.getint(
            "wipe_line_count", 2, minval=1, maxval=10)
        self.default_wipe_spacing = config.getfloat(
            "wipe_line_spacing", .6, above=0.)
        self.default_wipe_gap = config.getfloat(
            "wipe_line_gap", 2., minval=0.)
        self.default_wipe_tail = config.getfloat(
            "wipe_tail_length", 5., minval=0.)
        self.z_hop = config.getfloat("z_hop", 2., minval=0.)
        self.max_adjustment = config.getfloat("max_adjustment", .5, above=0.)
        self.ui_fine_step = config.getfloat("ui_fine_step", .01, above=0.)
        self.ui_coarse_step = config.getfloat("ui_coarse_step", .05, above=0.)
        self.bed_temp = config.getfloat("bed_temp", 60., minval=0.)
        self.extruder_temp = config.getfloat("extruder_temp", 200., minval=0.)
        self.filament_profiles = {
            "PLA": {"bed_temp": self.bed_temp,
                    "hotend_temp": self.extruder_temp},
            "TPU": {"bed_temp": 50., "hotend_temp": 225.},
            "ABS": {"bed_temp": 110., "hotend_temp": 250.},
        }
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
        self.ui_active = False
        self.past_adjustments = []
        self.settings = {}

        commands = (
            ("_FIRST_LAYER_SQUISH_START", self.cmd_start,
             "Start interactive first-layer squish calibration"),
            ("_FIRST_LAYER_SQUISH_SELECT", self.cmd_select,
             "Select the Z adjustment used for a printed square"),
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
            "filament": self.settings.get("filament"),
            "filament_profiles": sorted(self.filament_profiles),
            "samples": [dict(sample) for sample in self.samples],
        }

    def add_filament_profile(self, config):
        profile_name = config.get_name().split()[-1].strip().upper()
        if not profile_name:
            raise config.error("A filament profile name is required")
        current = self.filament_profiles.get(profile_name, {
            "bed_temp": self.bed_temp,
            "hotend_temp": self.extruder_temp,
        })
        self.filament_profiles[profile_name] = {
            "bed_temp": config.getfloat(
                "bed_temp", current["bed_temp"], minval=0.),
            "hotend_temp": config.getfloat(
                "hotend_temp", current["hotend_temp"], minval=0.),
        }

    def _require_active(self, gcmd):
        if self.state == "inactive":
            raise gcmd.error("No first-layer squish calibration is active")

    def _activate_manual_probe_ui(self):
        try:
            self.gcode.register_command("ACCEPT", "dummy")
        except self.printer.config_error:
            raise self.gcode.error(
                "Another manual Z calibration is active; use ABORT first")
        self.gcode.register_command("ACCEPT", None)
        commands = (
            ("ACCEPT", self.cmd_ui_accept,
             "Print next squish square or accept the final offset"),
            ("NEXT", self.cmd_ui_next,
             "Print the next first-layer squish square"),
            ("ABORT", self.cmd_abort,
             "Abort first-layer squish calibration"),
            ("TESTZ", self.cmd_testz,
             "Adjust Z for first-layer squish calibration"),
        )
        registered = []
        try:
            for name, callback, description in commands:
                self.gcode.register_command(
                    name, callback, desc=description)
                registered.append(name)
            self.ui_active = True
            self._update_manual_probe_status()
        except Exception:
            for name in registered:
                self.gcode.register_command(name, None)
            self.ui_active = False
            raise

    def _deactivate_manual_probe_ui(self):
        if not self.ui_active:
            return
        self.manual_probe.reset_status()
        for command in ("ACCEPT", "NEXT", "ABORT", "TESTZ"):
            self.gcode.register_command(command, None)
        self.ui_active = False

    def _update_manual_probe_status(self):
        lower_values = [value for value in self.past_adjustments
                        if value < self.adjustment]
        upper_values = [value for value in self.past_adjustments
                        if value > self.adjustment]
        self.manual_probe.status = {
            "is_active": True,
            "z_position": self.adjustment,
            "z_position_lower": max(lower_values) if lower_values else None,
            "z_position_upper": min(upper_values) if upper_values else None,
        }

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

        filament = gcmd.get("FILAMENT").strip().upper()
        if filament not in self.filament_profiles:
            raise gcmd.error(
                "Unknown FILAMENT '%s'; configured profiles: %s" % (
                    filament, ", ".join(sorted(self.filament_profiles))))
        profile = self.filament_profiles[filament]
        command_parameters = gcmd.get_command_parameters()
        if "HOTEND_TEMP" in command_parameters:
            hotend_temp = gcmd.get_float("HOTEND_TEMP", minval=0.)
        else:
            hotend_temp = gcmd.get_float(
                "EXTRUDER_TEMP", profile["hotend_temp"], minval=0.)

        settings = {
            "filament": filament,
            "count": gcmd.get_int("COUNT", self.default_count,
                                  minval=1, maxval=25),
            "size": gcmd.get_float("SIZE", self.default_size, above=0.),
            "layer_count": gcmd.get_int(
                "LAYERS", self.default_layer_count, minval=3, maxval=20),
            "layer_height": gcmd.get_float(
                "LAYER_HEIGHT", self.default_height, above=0.),
            "line_width": gcmd.get_float(
                "LINE_WIDTH", self.default_width, above=0.),
            "flow": gcmd.get_float("FLOW", self.default_flow, above=0.),
            "infill_angle": gcmd.get_float(
                "INFILL_ANGLE", self.default_infill_angle) % 180.,
            "filament_diameter": gcmd.get_float(
                "FILAMENT_DIAMETER", self.filament_diameter, above=0.),
            "bed_temp": gcmd.get_float(
                "BED_TEMP", profile["bed_temp"], minval=0.),
            "extruder_temp": hotend_temp,
            "hotend_temp": hotend_temp,
            "wipe_length": gcmd.get_float(
                "WIPE_LENGTH", self.default_wipe_length, minval=0.),
            "wipe_lines": gcmd.get_int(
                "WIPE_LINES", self.default_wipe_lines, minval=1, maxval=10),
            "wipe_spacing": gcmd.get_float(
                "WIPE_SPACING", self.default_wipe_spacing, above=0.),
            "wipe_gap": gcmd.get_float(
                "WIPE_GAP", self.default_wipe_gap, minval=0.),
            "wipe_tail": gcmd.get_float(
                "WIPE_TAIL", self.default_wipe_tail, minval=0.),
        }
        try:
            centers = generate_square_centers(
                settings["count"], settings["size"], self.margin, self.bounds)
        except ValueError as error:
            raise gcmd.error(str(error))
        if settings["size"] <= 2. * settings["line_width"]:
            raise gcmd.error(
                "SIZE must be greater than twice LINE_WIDTH")
        try:
            for center in centers:
                generate_wipe_points(
                    center, settings["size"], settings["wipe_length"],
                    settings["wipe_lines"], settings["wipe_spacing"],
                    settings["wipe_gap"], settings["line_width"], self.bounds)
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
            self._activate_manual_probe_ui()
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

    def _inspection_position(self, next_center):
        if next_center is not None:
            half_size = self.settings["size"] * .5
            return (next_center[0] - half_size,
                    next_center[1] - half_size)
        x_min, x_max, y_min, y_max = self.bounds
        park_x = (x_min + x_max) * .5
        park_y = min(y_max, y_min + max(2., self.margin * .5))
        return park_x, park_y

    def _append_layer_gcode(self, commands, bounds, infill_angle):
        settings = self.settings
        x0, x1, y0, y1 = bounds

        self._move_line(commands, x1, y0, settings["size"])
        self._move_line(commands, x1, y1, settings["size"])
        self._move_line(commands, x0, y1, settings["size"])
        self._move_line(commands, x0, y0, settings["size"])

        inset = settings["line_width"]
        infill_x0, infill_x1 = x0 + inset, x1 - inset
        infill_y0, infill_y1 = y0 + inset, y1 - inset
        segments = generate_infill_segments(
            (infill_x0, infill_x1, infill_y0, infill_y1),
            settings["line_width"], infill_angle)
        for index, segment in enumerate(segments):
            start, end = segment
            if index % 2:
                start, end = end, start
            start_x, start_y = start
            end_x, end_y = end
            commands.append("G1 X%.4f Y%.4f F%.1f" % (
                start_x, start_y, self.print_speed * 60.))
            self._move_line(
                commands, end_x, end_y,
                math.hypot(end_x - start_x, end_y - start_y))

    def _square_gcode(self, center, next_center=None):
        settings = self.settings
        half_size = settings["size"] * .5
        x0, x1 = center[0] - half_size, center[0] + half_size
        y0, y1 = center[1] - half_size, center[1] + half_size
        final_z = settings["layer_height"] * settings["layer_count"]
        safe_z = final_z + self.z_hop
        wipe_points = generate_wipe_points(
            center, settings["size"], settings["wipe_length"],
            settings["wipe_lines"], settings["wipe_spacing"],
            settings["wipe_gap"], settings["line_width"], self.bounds)
        commands = [
            "G90", "M83", "G1 Z%.4f F%.1f" % (safe_z, self.z_speed * 60.),
        ]

        if wipe_points:
            wipe_x, wipe_y = wipe_points[0]
            commands.extend((
                "G1 X%.4f Y%.4f F%.1f" % (
                    wipe_x, wipe_y, self.travel_speed * 60.),
                "G1 Z%.4f F%.1f" % (
                    settings["layer_height"], self.z_speed * 60.),
            ))
            if self.printed_count and self.retract_length:
                commands.append("G1 E%.5f F%.1f" % (
                    self.retract_length, self.retract_speed * 60.))
            previous = wipe_points[0]
            for point in wipe_points[1:]:
                self._move_line(
                    commands, point[0], point[1],
                    math.hypot(point[0] - previous[0],
                               point[1] - previous[1]))
                previous = point
            if self.retract_length:
                commands.append("G1 E-%.5f F%.1f" % (
                    self.retract_length, self.retract_speed * 60.))
            if settings["wipe_tail"] and len(wipe_points) > 1:
                wipe_end = wipe_points[-1]
                wipe_previous = wipe_points[-2]
                final_segment = math.hypot(
                    wipe_previous[0] - wipe_end[0],
                    wipe_previous[1] - wipe_end[1])
                if final_segment:
                    tail_length = min(settings["wipe_tail"], final_segment)
                    tail_scale = tail_length / final_segment
                    tail_x = (wipe_end[0]
                              + (wipe_previous[0] - wipe_end[0]) * tail_scale)
                    tail_y = (wipe_end[1]
                              + (wipe_previous[1] - wipe_end[1]) * tail_scale)
                    commands.append("G1 X%.4f Y%.4f F%.1f" % (
                        tail_x, tail_y, self.travel_speed * 60.))
            commands.append("G1 Z%.4f F%.1f" % (
                safe_z, self.z_speed * 60.))

        commands.append("G1 X%.4f Y%.4f F%.1f" % (
            x0, y0, self.travel_speed * 60.))

        for layer_index in range(settings["layer_count"]):
            layer_z = settings["layer_height"] * (layer_index + 1)
            commands.append("G1 Z%.4f F%.1f" % (
                layer_z, self.z_speed * 60.))
            if layer_index:
                commands.append("G1 X%.4f Y%.4f F%.1f" % (
                    x0, y0, self.travel_speed * 60.))
            if ((wipe_points or self.printed_count or layer_index)
                    and self.retract_length):
                commands.append("G1 E%.5f F%.1f" % (
                    self.retract_length, self.retract_speed * 60.))

            angle = (settings["infill_angle"]
                     + (90. if layer_index % 2 else 0.)) % 180.
            self._append_layer_gcode(
                commands, (x0, x1, y0, y1), angle)
            if self.retract_length:
                commands.append("G1 E-%.5f F%.1f" % (
                    self.retract_length, self.retract_speed * 60.))

        inspect_x, inspect_y = self._inspection_position(next_center)
        commands.extend((
            "G1 Z%.4f F%.1f" % (safe_z, self.z_speed * 60.),
            "G1 X%.4f Y%.4f F%.1f" % (
                inspect_x, inspect_y, self.travel_speed * 60.),
            "M400"))
        return "\n".join(commands)

    def _print_next_square(self, gcmd):
        if self.printed_count >= len(self.centers):
            raise gcmd.error("All first-layer squares have been printed")
        square_number = self.printed_count + 1
        next_index = self.printed_count + 1
        next_center = (self.centers[next_index]
                       if next_index < len(self.centers) else None)
        self.state = "printing"
        self.gcode.run_script_from_command(
            self._square_gcode(
                self.centers[self.printed_count], next_center=next_center))
        self.samples.append({"square": square_number,
                             "adjustment": self.adjustment})
        self.printed_count = square_number
        self.state = ("complete" if self.printed_count == len(self.centers)
                      else "waiting")
        self._update_manual_probe_status()
        if self.state == "complete":
            gcmd.respond_info(
                "Square %d/%d printed at Z adjustment %+.3f. Adjust Z if "
                "needed, then press Accept to stage the offset, or Abort."
                % (square_number, len(self.centers), self.adjustment))
        else:
            gcmd.respond_info(
                "Square %d/%d printed at Z adjustment %+.3f. Press Accept "
                "to stage this result, or adjust Z and press Accept to print "
                "the next square." % (
                    square_number, len(self.centers), self.adjustment))

    def _apply_adjustment(self, gcmd, delta):
        if self.state == "printing":
            raise gcmd.error("Wait for the square to finish before adjusting Z")
        new_adjustment = self.adjustment + delta
        if abs(new_adjustment) > self.max_adjustment + 1.e-9:
            raise gcmd.error(
                "Requested adjustment exceeds max_adjustment (%.3f)"
                % (self.max_adjustment,))
        if self.adjustment not in self.past_adjustments:
            self.past_adjustments.append(self.adjustment)
        self.gcode.run_script_from_command(
            "SET_GCODE_OFFSET Z_ADJUST=%.6f MOVE=1 MOVE_SPEED=%.3f"
            % (delta, self.z_speed))
        self.adjustment = new_adjustment
        self._update_manual_probe_status()
        gcmd.respond_info(
            "First-layer Z adjustment: %+.3f (negative is more squish)"
            % (self.adjustment,))

    def cmd_testz(self, gcmd):
        self._require_active(gcmd)
        requested = gcmd.get("Z")
        symbolic_steps = {
            "+": self.ui_fine_step,
            "++": self.ui_coarse_step,
            "-": -self.ui_fine_step,
            "--": -self.ui_coarse_step,
        }
        if requested in symbolic_steps:
            delta = symbolic_steps[requested]
        else:
            delta = gcmd.get_float("Z")
        self._apply_adjustment(gcmd, delta)

    def cmd_ui_accept(self, gcmd):
        self._require_active(gcmd)
        if self.state == "waiting":
            if self._adjustment_has_printed_sample():
                self.cmd_accept(gcmd)
                return
            self._print_next_square(gcmd)
            return
        if self.state == "complete":
            self.cmd_accept(gcmd)
            return
        raise gcmd.error("Wait for the current squish operation to finish")

    def _adjustment_has_printed_sample(self):
        return any(abs(sample["adjustment"] - self.adjustment) <= 1.e-9
                   for sample in self.samples)

    def cmd_ui_next(self, gcmd):
        self._require_active(gcmd)
        if self.state != "waiting":
            raise gcmd.error("The calibration is not ready for the next square")
        self._print_next_square(gcmd)

    def cmd_select(self, gcmd):
        self._require_active(gcmd)
        square_number = gcmd.get_int("SQUARE", minval=1)
        if square_number > len(self.samples):
            raise gcmd.error("That square has not been printed")
        selected = self.samples[square_number - 1]["adjustment"]
        delta = selected - self.adjustment
        if self.adjustment not in self.past_adjustments:
            self.past_adjustments.append(self.adjustment)
        if abs(delta) > 1.e-9:
            self.gcode.run_script_from_command(
                "SET_GCODE_OFFSET Z_ADJUST=%.6f MOVE=1 MOVE_SPEED=%.3f"
                % (delta, self.z_speed))
        self.adjustment = selected
        self._update_manual_probe_status()
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
        self.state = "applying"
        parameters = dict(self.settings)
        parameters["adjustment"] = self.adjustment
        accepted_adjustment = self.adjustment
        try:
            self._deactivate_manual_probe_ui()
            self._restore_gcode_state(True)
            self._run_template(self.end_template, parameters)
            method = self._resolve_apply_method()
            apply_command = ("Z_OFFSET_APPLY_PROBE" if method == "probe"
                             else "Z_OFFSET_APPLY_ENDSTOP")
            self.gcode.run_script_from_command(apply_command)
            gcmd.respond_info(
                "First-layer Z adjustment %+.3f staged using %s. Klipper "
                "was not restarted. Run SAVE_CONFIG when you are ready to "
                "write the pending change and restart Klipper."
                % (accepted_adjustment, apply_command))
            self._reset_state()
        except Exception:
            self.state = "complete"
            self._activate_manual_probe_ui()
            raise

    def cmd_abort(self, gcmd):
        self._require_active(gcmd)
        parameters = dict(self.settings)
        parameters["adjustment"] = self.adjustment
        try:
            self._deactivate_manual_probe_ui()
            self._restore_gcode_state(False)
            self._run_template(self.end_template, parameters)
        finally:
            self._reset_state()
        gcmd.respond_info(
            "First-layer squish calibration aborted; Z offset restored")

    def _reset_state(self):
        self._deactivate_manual_probe_ui()
        self.state = "inactive"
        self.centers = []
        self.samples = []
        self.printed_count = 0
        self.adjustment = 0.
        self.initial_offset = 0.
        self.state_saved = False
        self.past_adjustments = []
        self.settings = {}


def load_config(config):
    return FirstLayerSquish(config)


def load_config_prefix(config):
    printer = config.get_printer()
    calibration = printer.lookup_object("first_layer_squish", None)
    if calibration is None:
        raise config.error(
            "[first_layer_squish] must appear before filament profiles")
    calibration.add_filament_profile(config)
    return calibration
