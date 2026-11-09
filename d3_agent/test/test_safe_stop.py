"""Parada segura por defecto de d3_agent, probada con d3_sim -> d3_agent -> D3Client (sin ROS).

Si se cierra la conexión de control que movía al robot, d3_agent cancela navigate.target y detiene el robot.
Si se cierra una conexión que solo observaba, el movimiento de los demás clientes sigue.
"""
import os
import socket
import subprocess
import sys
import tempfile
import time

import pytest

from d3_sdk_client import D3Client

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
AGENT = os.path.join(ROOT, "d3_agent", "d3_agent.py")
SIM_PKG = os.path.join(ROOT, "d3_sim")
TOKEN = "test-token-123456"  # public-safe: token ficticio solo para pruebas locales
# Destino lejos de los obstáculos del simulador, para que la evasión no frene al robot.
GOAL = {"x": 5.0, "y": -5.0}

sys.path.insert(0, os.path.join(ROOT, "d3_agent"))
import d3_agent  # noqa: E402


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for(predicate, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def port():
    tmp = tempfile.mkdtemp(prefix="d3test")
    sock_path = os.path.join(tmp, "doubleapi")
    agent_port, pages_port = free_port(), free_port()
    env = dict(os.environ, PYTHONPATH=SIM_PKG)
    sim = subprocess.Popen([sys.executable, "-m", "d3_sim.sim", "--socket", sock_path], env=env)
    assert wait_for(lambda: os.path.exists(sock_path))
    agent = subprocess.Popen([sys.executable, AGENT, "--profile", "sim", "--api", sock_path,
                              "--port", str(agent_port), "--listen", "127.0.0.1",
                              "--pages-port", str(pages_port), "--token", TOKEN])

    def agent_up():
        try:
            socket.create_connection(("127.0.0.1", agent_port), timeout=0.2).close()
            return True
        except OSError:
            return False

    assert wait_for(agent_up)
    yield agent_port
    agent.terminate()
    sim.terminate()
    agent.wait(5)
    sim.wait(5)


def client(port):
    c = D3Client("127.0.0.1", port, TOKEN).start()
    assert c.wait_connected(5)
    return c


def speed(observer):
    return float(observer.latest("DRPose.pose", {}).get("base", {}).get("speed", 0.0))


def start_moving(port, observer):
    mover = client(port)
    mover.send("base.kickstand.retract")
    assert observer.wait_event("DRBase.status", 3, predicate=lambda d: d.get("kickstand") == 2)
    mover.send("navigate.target", GOAL)
    assert wait_for(lambda: speed(observer) > 0.1, 5), "el robot simulado no arrancó con navigate.target"
    return mover


def test_motion_commands_are_tracked():
    assert {"navigate.drive", "navigate.target", "base.turnBy"} <= d3_agent.MOTION_COMMANDS
    assert [m["c"] for m in d3_agent.SAFE_STOP_COMMANDS] == ["navigate.cancelTarget", "navigate.drive"]


def test_default_link_timeout_is_enabled():
    args = d3_agent.parse_args(["--token", TOKEN])
    assert args.link_timeout > 0


def test_robot_stops_when_the_moving_client_disconnects(port):
    observer = client(port)
    observer.subscribe(["DRPose.pose", "DRBase.status", "DRNavigateModule.cancelTarget"])
    try:
        mover = start_moving(port, observer)
        mover.stop()   # se cae la conexión de control sin mandar stop
        cut = time.monotonic()
        assert observer.wait_event("DRAgent.safeStop", 2) is not None
        assert observer.wait_event("DRNavigateModule.cancelTarget", 2) is not None
        assert wait_for(lambda: abs(speed(observer)) <= 0.01, 3), \
            "el robot simulado no se detuvo (velocidad %.3f m/s)" % speed(observer)
        elapsed = time.monotonic() - cut
        assert elapsed < 1.5, "se detuvo en %.2f s" % elapsed
    finally:
        observer.stop()


def test_observer_disconnect_does_not_stop_the_robot(port):
    observer = client(port)
    observer.subscribe(["DRPose.pose", "DRBase.status"])
    mover = None
    try:
        mover = start_moving(port, observer)
        bystander = client(port)
        bystander.send("navigate.requestStatus")   # comando que no mueve al robot
        bystander.stop()
        time.sleep(0.8)
        assert observer.latest("DRAgent.safeStop") is None
        assert speed(observer) > 0.1, "una conexión que solo observaba detuvo al robot"
    finally:
        if mover is not None:
            mover.stop()
        observer.stop()
