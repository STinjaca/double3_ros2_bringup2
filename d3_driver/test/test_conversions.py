import math

from d3_driver import conversions as conv


def test_twist_to_drive_scales_and_clamps():
    assert conv.twist_to_drive(0.25, 0.8, 0.5, 1.6) == (0.5, 0.5)
    assert conv.twist_to_drive(2.0, -5.0, 0.5, 1.6) == (1.0, -1.0)
    assert conv.twist_to_drive(0.0, 0.0, 0.5, 1.6) == (0.0, 0.0)


def test_yaw_roundtrip_and_unnormalized_quaternion():
    for yaw in (0.0, 0.5, -2.0, math.pi - 0.01):
        assert abs(conv.yaw_from_quaternion(*conv.quaternion_from_yaw(yaw)) - yaw) < 1e-9
    # el demo de SinfonIA publica orientation.z=yaw, w=1 sin normalizar
    assert abs(conv.yaw_from_quaternion(0, 0, 0.0, 1.0)) < 1e-9


def test_pole_and_tilt_mappings():
    assert conv.pole_percent_to_m(0.5, 0.33) == 0.165
    assert conv.pole_m_to_percent(0.66, 0.33) == 1.0
    assert conv.tilt_percent_to_rad(0.0, -0.35, 0.35) == -0.35
    assert abs(conv.tilt_rad_to_percent(0.0, -0.35, 0.35) - 0.5) < 1e-9


def test_tolerant_parsers():
    assert conv.ultrasonic_distance_m({"sensor": 2, "distance": 1.25}) == 1.25
    assert conv.ultrasonic_distance_m({"cm": 80}) == 0.8
    assert conv.ultrasonic_distance_m({"distance": 150}) == 1.5
    assert conv.ultrasonic_distance_m({}) is None
    assert conv.battery_percent({"battery": 87}) == 87
    assert conv.battery_percent({"battery": 0.5}, scale=100.0) == 50
    assert conv.first_number({"base": {"x": 1}}, ("base.x",)) == 1.0
    assert conv.first_number({"kickstand": True}, ("kickstand",)) is None
