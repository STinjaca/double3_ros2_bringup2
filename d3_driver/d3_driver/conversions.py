"""Conversiones puras (sin ROS) entre unidades ROS y la API del D3. Se prueban con pytest."""
import math


def clamp(value, low, high):
    return max(low, min(high, value))


def twist_to_drive(linear_x, angular_z, max_linear, max_angular, deadband=1e-3):
    """m/s y rad/s -> (throttle, turn) en -1..1. turn>0 gira a la izquierda (convención REP-103).

    ASSUMED: el signo de `turn` en navigate.drive se valida en el laboratorio (param invert_turn).
    """
    throttle = clamp(linear_x / max_linear, -1.0, 1.0) if max_linear > 0 else 0.0
    turn = clamp(angular_z / max_angular, -1.0, 1.0) if max_angular > 0 else 0.0
    if abs(throttle) < deadband:
        throttle = 0.0
    if abs(turn) < deadband:
        turn = 0.0
    return throttle, turn


def yaw_from_quaternion(x, y, z, w):
    norm = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / norm, y / norm, z / norm, w / norm
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


def quaternion_from_yaw(yaw):
    return 0.0, 0.0, math.sin(yaw / 2.0), math.cos(yaw / 2.0)


def pole_percent_to_m(percent, travel_m):
    return clamp(float(percent), 0.0, 1.0) * travel_m


def pole_m_to_percent(meters, travel_m):
    return clamp(meters / travel_m, 0.0, 1.0) if travel_m > 0 else 0.0


def tilt_percent_to_rad(percent, up_rad, down_rad):
    """tilt del D3: 0 = arriba, 1 = abajo. En ROS, pitch positivo = mirar hacia abajo."""
    return up_rad + clamp(float(percent), 0.0, 1.0) * (down_rad - up_rad)


def tilt_rad_to_percent(rad, up_rad, down_rad):
    span = down_rad - up_rad
    return clamp((rad - up_rad) / span, 0.0, 1.0) if span else 0.5


def first_number(data, keys, default=None):
    """Lee el primer campo numérico presente: el SDK no documenta los payloads (parser tolerante)."""
    for key in keys:
        node = data
        for part in key.split("."):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                node = None
                break
        if isinstance(node, (int, float)) and not isinstance(node, bool):
            return float(node)
    return default


def ultrasonic_distance_m(data):
    """DRUltrasonic.measurement -> metros. Acepta distance/range/value (m), cm o mm."""
    meters = first_number(data, ("distance", "range", "value", "meters", "m"))
    if meters is not None:
        return meters / 100.0 if meters > 20 else meters  # valores grandes probablemente en cm
    cm = first_number(data, ("cm", "distanceCm"))
    if cm is not None:
        return cm / 100.0
    mm = first_number(data, ("mm", "distanceMm"))
    return mm / 1000.0 if mm is not None else None


def battery_percent(data, scale=1.0):
    """DRBase.status.battery -> 0..100. `scale`=100 si el robot reporta fracción 0..1 (validar en el lab)."""
    value = first_number(data, ("battery", "batteryPercent", "percent"))
    return None if value is None else clamp(value * scale, 0.0, 100.0)
