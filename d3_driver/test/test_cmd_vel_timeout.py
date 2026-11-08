"""cmd_vel_timeout: el driver deja de reenviar navigate.drive y detiene el robot.

- Unitarias: la lógica de on_cmd_vel / check_cmd_vel_timeout / stop_driving con un cliente falso.
- Integración: d3_sim -> d3_agent -> d3_driver_node (rclpy); se corta el publicador de cmd_vel sin mandar
  velocidad cero y el robot simulado debe detenerse en menos de 1 s.
"""
import logging
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import types

import pytest
import rclpy
import yaml
from geometry_msgs.msg import Twist
from rclpy.executors import MultiThreadedExecutor

from d3_driver.driver_node import D3Driver
from d3_sdk_client import D3Client

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
AGENT = os.path.join(ROOT, "d3_agent", "d3_agent.py")
SIM_PKG = os.path.join(ROOT, "d3_sim")
CONFIG = os.path.join(ROOT, "d3_bringup2", "config", "d3.yaml")
TOKEN = "test-token-123456"  # public-safe: token ficticio solo para pruebas locales
STOP = ("navigate.drive", {"throttle": 0.0, "turn": 0.0})


def twist(linear_x=0.0, angular_z=0.0):
    msg = Twist()
    msg.linear.x, msg.angular.z = linear_x, angular_z
    return msg


# ---------------------------------------------------------------------- unitarias (cliente falso)
class FakeD3:
    def __init__(self):
        self.sent = []
        self.repeats = {}

    def send(self, command, data=None):
        self.sent.append((command, data))
        return True

    def repeat(self, key, command, data=None, period=0.2):
        self.repeats[key] = (command, data)

    def stop_repeat(self, key):
        return self.repeats.pop(key, None) is not None


def fake_driver(timeout=0.5):
    drv = types.SimpleNamespace(
        d3=FakeD3(), driving=False, kickstand=2, last_cmd_vel=0.0,
        params={"max_linear_speed": 0.5, "max_angular_speed": 1.6, "invert_turn": False, "drive_period": 0.2,
                "cmd_vel_timeout": timeout, "auto_retract_kickstand": True},
        get_logger=lambda: logging.getLogger("test_cmd_vel_timeout"))
    drv.stop_driving = types.MethodType(D3Driver.stop_driving, drv)
    return drv


def test_default_timeout_in_config_is_half_second():
    with open(CONFIG, encoding="utf-8") as fh:
        params = yaml.safe_load(fh)["d3_driver_node"]["ros__parameters"]
    assert params["cmd_vel_timeout"] == 0.5


def test_zero_velocity_stops_repeating_and_sends_stop_once():
    drv = fake_driver()
    D3Driver.on_cmd_vel(drv, twist(0.2))
    assert "drive" in drv.d3.repeats and drv.d3.sent == []
    D3Driver.on_cmd_vel(drv, twist())
    D3Driver.on_cmd_vel(drv, twist())
    assert drv.d3.repeats == {}
    assert drv.d3.sent == [STOP]


def test_timeout_stops_repeating_and_sends_stop_once():
    drv = fake_driver(timeout=0.5)
    D3Driver.on_cmd_vel(drv, twist(0.2))
    D3Driver.check_cmd_vel_timeout(drv)            # recién llegado: sigue manejando
    assert "drive" in drv.d3.repeats and drv.d3.sent == []
    drv.last_cmd_vel = time.monotonic() - 0.6      # venció el timeout
    D3Driver.check_cmd_vel_timeout(drv)
    D3Driver.check_cmd_vel_timeout(drv)
    assert drv.d3.repeats == {}
    assert drv.d3.sent == [STOP]


def test_timeout_zero_keeps_velocity():
    drv = fake_driver(timeout=0.0)
    D3Driver.on_cmd_vel(drv, twist(0.2))
    drv.last_cmd_vel = time.monotonic() - 10.0
    D3Driver.check_cmd_vel_timeout(drv)
    assert "drive" in drv.d3.repeats and drv.d3.sent == []


# ---------------------------------------------------------------------- integración (d3_sim)
def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for(predicate, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


@pytest.fixture
def stack():
    tmp = tempfile.mkdtemp(prefix="d3test")
    sock_path = os.path.join(tmp, "doubleapi")
    port, pages_port = free_port(), free_port()
    env = dict(os.environ, PYTHONPATH=SIM_PKG)
    sim = subprocess.Popen([sys.executable, "-m", "d3_sim.sim", "--socket", sock_path], env=env)
    assert wait_for(lambda: os.path.exists(sock_path))
    agent = subprocess.Popen([sys.executable, AGENT, "--profile", "sim", "--api", sock_path, "--port", str(port),
                              "--listen", "127.0.0.1", "--pages-port", str(pages_port), "--token", TOKEN])

    def agent_up():
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            return True
        except OSError:
            return False

    assert wait_for(agent_up)
    yield port
    agent.terminate()
    sim.terminate()
    agent.wait(5)
    sim.wait(5)


def test_simulated_robot_stops_within_1s_after_publisher_is_cut(stack):
    port = stack
    observer = D3Client("127.0.0.1", port, TOKEN).start()
    executor = driver = pub_node = None
    try:
        assert observer.wait_connected(5)
        observer.subscribe(["DRPose.pose", "DRBase.status"])
        observer.send("base.kickstand.retract")
        assert observer.wait_event("DRBase.status", 3, predicate=lambda d: d.get("kickstand") == 2)

        # Sin -p cmd_vel_timeout: se prueba el valor por defecto del código.
        rclpy.init(args=["--ros-args", "-p", "robot_ip:=127.0.0.1", "-p", "robot_port:=%d" % port,
                         "-p", "robot_token:=" + TOKEN, "-p", "camera_enabled:=false", "-p", "audio_enabled:=false"])
        driver = D3Driver()
        assert driver.params["cmd_vel_timeout"] == 0.5
        pub_node = rclpy.create_node("test_cmd_vel_publisher")
        pub = pub_node.create_publisher(Twist, "cmd_vel", 10)
        executor = MultiThreadedExecutor(num_threads=4)
        executor.add_node(driver)
        executor.add_node(pub_node)
        threading.Thread(target=executor.spin, daemon=True).start()
        assert driver.d3.wait_connected(5)

        def speed():
            return float(observer.latest("DRPose.pose", {}).get("base", {}).get("speed", 0.0))

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and speed() < 0.1:
            pub.publish(twist(0.15))
            time.sleep(0.1)
        assert speed() >= 0.1, "el robot simulado no arrancó con cmd_vel"

        pub_node.destroy_publisher(pub)   # se corta el publicador sin mandar velocidad cero
        cut = time.monotonic()
        while time.monotonic() - cut < 3.0 and abs(speed()) > 0.01:
            time.sleep(0.02)
        elapsed = time.monotonic() - cut
        assert abs(speed()) <= 0.01, "el robot simulado no se detuvo (velocidad %.3f m/s)" % speed()
        assert elapsed < 1.0, "se detuvo en %.2f s (máximo 1 s)" % elapsed
    finally:
        if executor is not None:
            executor.shutdown()
        for node in (driver, pub_node):
            if node is not None:
                node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        observer.stop()
