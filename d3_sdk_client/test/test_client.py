"""Pruebas del cliente: framing, y cadena completa d3_sim -> d3_agent -> D3Client (sin ROS)."""
import math
import os
import socket
import subprocess
import sys
import tempfile
import time

import pytest

from d3_sdk_client import D3Client, HandshakeError, LineBuffer, open_role

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
AGENT = os.path.join(ROOT, "d3_agent", "d3_agent.py")
SIM_PKG = os.path.join(ROOT, "d3_sim")
TOKEN = "test-token-123456"  # public-safe: token ficticio solo para pruebas locales


def test_line_buffer_splits_partial_lines():
    buf = LineBuffer()
    assert buf.feed(b'{"a":1}\n{"b"') == ['{"a":1}']
    assert buf.feed(b':2}\n\n') == ['{"b":2}']
    assert buf.feed(b"") == []


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


@pytest.fixture(scope="module")
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
    yield {"port": port, "pages_port": pages_port}
    agent.terminate()
    sim.terminate()
    agent.wait(5)
    sim.wait(5)


def test_bad_token_is_rejected(stack):
    with pytest.raises(HandshakeError):
        open_role("127.0.0.1", stack["port"], "wrong", "control")


def test_drive_moves_simulated_robot(stack):
    client = D3Client("127.0.0.1", stack["port"], TOKEN).start()
    try:
        assert client.wait_connected(5)
        client.subscribe(["DRPose.pose", "DRBase.status"])
        status = client.request("base.requestStatus", None, "DRBase.status", timeout=3)
        assert status is not None and "battery" in status
        client.send("base.kickstand.retract")
        start = client.wait_event("DRPose.pose", 3)["base"]["x"]
        client.repeat("drive", "navigate.drive", {"throttle": 1.0, "turn": 0.0}, period=0.2)
        time.sleep(1.5)
        client.stop_repeat("drive")
        moved = client.latest("DRPose.pose")["base"]["x"] - start
        assert moved > 0.2
        # watchdog: al dejar de reenviar, el robot se detiene
        time.sleep(1.5)
        assert abs(client.latest("DRPose.pose")["base"]["speed"]) < 0.05
    finally:
        client.stop()


def test_navigate_target_arrives(stack):
    client = D3Client("127.0.0.1", stack["port"], TOKEN).start()
    try:
        assert client.wait_connected(5)
        client.subscribe(["DRNavigateModule.arrive", "DRPose.pose"])
        client.send("base.kickstand.retract")
        arrive = client.request("navigate.target", {"x": 0.0, "y": 0.0, "angleRadians": math.pi / 2,
                                                     "relative": True}, "DRNavigateModule.arrive", timeout=8)
        assert arrive is not None
    finally:
        client.stop()


def test_agent_ping(stack):
    client = D3Client("127.0.0.1", stack["port"], TOKEN).start()
    try:
        assert client.wait_connected(5)
        pong = client.request("agent.ping", None, "DRAgent.pong", timeout=3)
        assert pong and "version" in pong
    finally:
        client.stop()
