"""Simulador de la API local del Double 3 (/tmp/doubleapi).

Emula el protocolo JSON por línea del socket Unix para desarrollar sin el robot: integra navigate.drive
(con watchdog de 500 ms), navigate.target, pole, kickstand, tilt, IMU, pose, ultrasonido, batería,
parlante y pantalla. `d3_agent --profile sim --api <socket>` se conecta a este simulador igual que
al robot real.

Los nombres de comandos/eventos vienen del API pública del SDK. Los CAMPOS de los payloads que el SDK
no documenta (marcados ASSUMED) son supuestos razonables: se reemplazan grabando el robot real
(d3_agent --record) y reproduciendo con --replay.
"""
import argparse
import json
import logging
import math
import os
import socket
import socketserver
import threading
import time

LOG = logging.getLogger("d3_sim")


def now_stamp():
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())


def clamp(value, low, high):
    return max(low, min(high, value))


def wrap_angle(angle):
    return math.atan2(math.sin(angle), math.cos(angle))


class Connection:
    def __init__(self, sock):
        self.sock = sock
        self.subscriptions = set()
        self.lock = threading.Lock()

    def wants(self, name):
        return "*" in self.subscriptions or name in self.subscriptions

    def send(self, event):
        payload = (json.dumps(event, separators=(",", ":")) + "\n").encode()
        with self.lock:
            self.sock.sendall(payload)


class D3Simulator:
    MAX_SPEED = 0.5        # m/s con throttle=1 (ASSUMED, se calibra en el lab)
    MAX_TURN = 1.6         # rad/s con turn=1 (ASSUMED)
    POLE_RATE = 0.25       # fracción por segundo
    TILT_RATE = 0.5
    ULTRASONIC_COUNT = 5

    def __init__(self, rate_hz=50.0, replay=None, obstacles=None):
        self.rate_hz = rate_hz
        self.lock = threading.RLock()
        self.connections = set()
        self.replay = replay
        # Estado del robot
        self.x = self.y = self.yaw = 0.0
        self.speed = self.turn_rate = 0.0
        self.throttle = self.turn = 0.0
        self.drive_deadline = 0.0
        self.target = None
        self.pole = 0.0
        self.pole_target = None
        self.kickstand = 1      # ASSUMED: 1 desplegado, 2 retraído (como en tas-art)
        self.tilt = 0.5
        self.tilt_target = None
        self.tilt_speed = 0.0
        self.tilt_deadline = 0.0
        self.battery = 87.0
        self.charging = False
        self.volume = 0.67
        self.obstacle_level = 2
        self.imu_enabled = False
        self.pose_enabled = True
        self.ultrasonic_running = False
        self.travel_running = False
        self.obstacles = obstacles if obstacles is not None else [(2.0, 0.0), (0.0, 1.5)]
        self._stop = threading.Event()
        self._last_status = None

    # ------------------------------------------------------------------ eventos
    def emit(self, cls, key, data=None):
        name = "%s.%s" % (cls, key)
        event = {"timestamp": now_stamp(), "class": cls, "key": key, "data": data or {}}
        with self.lock:
            conns = [c for c in self.connections if c.wants(name)]
        for conn in conns:
            try:
                conn.send(event)
            except OSError:
                pass

    def base_status(self):
        return {"battery": round(self.battery, 1), "charging": self.charging,
                "kickstand": self.kickstand, "pole": round(self.pole, 3)}

    # ------------------------------------------------------------------ comandos
    def handle_command(self, conn, msg):
        command = msg.get("c", "")
        data = msg.get("d") or {}
        handler = getattr(self, "cmd_" + command.replace(".", "_"), None)
        if handler is None:
            LOG.debug("comando sin simular: %s", command)
            return
        with self.lock:
            handler(conn, data)

    def cmd_events_subscribe(self, conn, data):
        conn.subscriptions |= set(data.get("events", []))

    def cmd_events_unsubscribe(self, conn, data):
        conn.subscriptions -= set(data.get("events", []))

    def cmd_api_requestStatus(self, conn, data):
        self.emit("DRAPI", "status", {"simulated": True})

    def cmd_api_requestLocalConfiguration(self, conn, data):
        self.emit("DRAPI", "localConfiguration", {"APP_VERSION": "sim"})

    def cmd_base_requestStatus(self, conn, data):
        self.emit("DRBase", "status", self.base_status())

    def cmd_base_requestVersion(self, conn, data):
        self.emit("DRBase", "version", {"version": "sim"})

    def cmd_base_kickstand_deploy(self, conn, data):
        self.kickstand = 1
        self.throttle = self.turn = 0.0
        self.target = None

    def cmd_base_kickstand_retract(self, conn, data):
        self.kickstand = 2

    def cmd_base_pole_setTarget(self, conn, data):
        self.pole_target = clamp(float(data.get("percent", self.pole)), 0.0, 1.0)
        self.emit("DRBase", "poleMotionStart", {})

    def cmd_base_pole_sit(self, conn, data):
        self.cmd_base_pole_setTarget(conn, {"percent": 0.0})

    def cmd_base_pole_stand(self, conn, data):
        self.cmd_base_pole_setTarget(conn, {"percent": 1.0})

    def cmd_base_pole_stop(self, conn, data):
        self.pole_target = None
        self.emit("DRBase", "poleMotionStop", {})

    def cmd_base_turnBy(self, conn, data):
        degrees = float(data.get("degrees", 0.0))
        self.target = {"mode": "turn", "yaw": wrap_angle(self.yaw + math.radians(degrees))}

    def cmd_base_travel_start(self, conn, data):
        self.travel_running = True

    def cmd_base_travel_stop(self, conn, data):
        self.travel_running = False

    def cmd_navigate_enable(self, conn, data):
        pass

    def cmd_navigate_drive(self, conn, data):
        if self.kickstand == 1:
            return  # con el kickstand desplegado el robot no maneja
        self.throttle = clamp(float(data.get("throttle", 0.0)), -1.0, 1.0)
        self.turn = clamp(float(data.get("turn", 0.0)), -1.0, 1.0)
        self.drive_deadline = time.monotonic() + 0.5
        self.target = None

    def cmd_navigate_stop(self, conn, data):
        self.throttle = self.turn = 0.0
        if self.target is not None:
            self.emit("DRNavigateModule", "cancelTarget", {})
        self.target = None

    def cmd_navigate_cancelTarget(self, conn, data):
        self.cmd_navigate_stop(conn, data)

    def cmd_navigate_target(self, conn, data):
        x, y = float(data.get("x", 0.0)), float(data.get("y", 0.0))
        angle = data.get("angleRadians")
        if data.get("relative", False):
            gx = self.x + x * math.cos(self.yaw) - y * math.sin(self.yaw)
            gy = self.y + x * math.sin(self.yaw) + y * math.cos(self.yaw)
            gyaw = None if angle is None else wrap_angle(self.yaw + float(angle))
        else:
            gx, gy = x, y
            gyaw = None if angle is None else float(angle)
        self.target = {"mode": "goto", "x": gx, "y": gy, "yaw": gyaw}
        self.emit("DRNavigateModule", "target", {"x": gx, "y": gy, "angleRadians": gyaw})

    def cmd_navigate_requestStatus(self, conn, data):
        self.emit("DRNavigateModule", "status", {"hasTarget": self.target is not None})

    def cmd_navigate_obstacleAvoidance_setLevel(self, conn, data):
        self.obstacle_level = int(data.get("level", 2))
        self.emit("DRObstacleAvoidance", "level", {"level": self.obstacle_level})

    def cmd_tilt_target(self, conn, data):
        self.tilt_target = clamp(float(data.get("percent", self.tilt)), 0.0, 1.0)
        self.emit("DRMotor", "start", {})

    def cmd_tilt_move(self, conn, data):
        self.tilt_speed = clamp(float(data.get("speed", 0.0)), -1.0, 1.0)
        self.tilt_deadline = time.monotonic() + 0.5
        self.tilt_target = None

    def cmd_tilt_stop(self, conn, data):
        self.tilt_target = None
        self.tilt_speed = 0.0
        self.emit("DRMotor", "stop", {"percent": self.tilt})

    def cmd_tilt_default(self, conn, data):
        self.cmd_tilt_target(conn, {"percent": 0.5})

    def cmd_imu_enable(self, conn, data):
        self.imu_enabled = True

    def cmd_imu_disable(self, conn, data):
        self.imu_enabled = False

    def cmd_pose_pause(self, conn, data):
        self.pose_enabled = False

    def cmd_pose_resume(self, conn, data):
        self.pose_enabled = True

    def cmd_pose_resetOrigin(self, conn, data):
        self.x = self.y = self.yaw = 0.0
        self.emit("DRPose", "resetOrigin", {})

    def cmd_ultrasonic_enable(self, conn, data):
        pass

    def cmd_ultrasonic_start(self, conn, data):
        self.ultrasonic_running = True
        self.emit("DRUltrasonic", "startCycle", {})

    def cmd_ultrasonic_stop(self, conn, data):
        self.ultrasonic_running = False
        self.emit("DRUltrasonic", "stopCycle", {})

    def cmd_speaker_enable(self, conn, data):
        pass

    def cmd_speaker_setVolume(self, conn, data):
        self.volume = clamp(float(data.get("percent", self.volume)), 0.0, 1.0)
        self.emit("DRSpeaker", "volume", {"percent": self.volume})

    def cmd_speaker_requestVolume(self, conn, data):
        self.emit("DRSpeaker", "volume", {"percent": self.volume})

    def cmd_camera_enable(self, conn, data):
        self.emit("DRCamera", "enable", {"template": data.get("template", "")})

    def cmd_camera_capturePhoto(self, conn, data):
        self.emit("DRCamera", "photo", {"simulated": True})

    def cmd_gui_accessoryWebView_open(self, conn, data):
        self.emit("DRGUI", "accessoryWebView.open", {"url": data.get("url", "")})

    def cmd_gui_accessoryWebView_close(self, conn, data):
        self.emit("DRGUI", "accessoryWebView.close", {})

    def cmd_gui_show(self, conn, data):
        pass

    def cmd_gui_hide(self, conn, data):
        pass

    def cmd_system_requestInfo(self, conn, data):
        self.emit("DRSystem", "systemInfo", {"simulated": True, "model": "Double 3 (sim)"})

    def cmd_mics_requestStatus(self, conn, data):
        self.emit("DRMics", "status", {"boost": 0.25})

    # ------------------------------------------------------------------ física
    def step(self, dt):
        now = time.monotonic()
        with self.lock:
            if now > self.drive_deadline and (self.throttle or self.turn):
                self.throttle = self.turn = 0.0  # watchdog de navigate.drive
            v_cmd, w_cmd = self.throttle * self.MAX_SPEED, self.turn * self.MAX_TURN
            if self.target is not None:
                v_cmd, w_cmd = self._target_control()
            if self.obstacle_level > 0 and v_cmd > 0 and self._front_distance() < 0.4:
                v_cmd = 0.0  # evasión de obstáculos: frena
            # aceleración limitada
            self.speed += clamp(v_cmd - self.speed, -1.0 * dt, 1.0 * dt)
            self.turn_rate += clamp(w_cmd - self.turn_rate, -4.0 * dt, 4.0 * dt)
            self.yaw = wrap_angle(self.yaw + self.turn_rate * dt)
            self.x += self.speed * math.cos(self.yaw) * dt
            self.y += self.speed * math.sin(self.yaw) * dt
            # pole y tilt
            if self.pole_target is not None:
                delta = self.pole_target - self.pole
                self.pole += clamp(delta, -self.POLE_RATE * dt, self.POLE_RATE * dt)
                if abs(delta) < 1e-3:
                    self.pole, self.pole_target = self.pole_target, None
                    self.emit("DRBase", "poleMotionStop", {})
            if self.tilt_target is not None:
                delta = self.tilt_target - self.tilt
                self.tilt += clamp(delta, -self.TILT_RATE * dt, self.TILT_RATE * dt)
                if abs(delta) < 1e-3:
                    self.tilt, self.tilt_target = self.tilt_target, None
                    self.emit("DRMotor", "arrive", {"percent": self.tilt})
            elif self.tilt_speed:
                if now > self.tilt_deadline:
                    self.tilt_speed = 0.0
                self.tilt = clamp(self.tilt + self.tilt_speed * self.TILT_RATE * dt, 0.0, 1.0)
            # batería
            self.battery = clamp(self.battery - dt * (0.002 + 0.01 * abs(self.speed)), 5.0, 100.0)

    def _target_control(self):
        target = self.target
        if target["mode"] == "turn":
            err = wrap_angle(target["yaw"] - self.yaw)
            if abs(err) < 0.02:
                self.target = None
                self.emit("DRNavigateModule", "arrive", {})
                return 0.0, 0.0
            return 0.0, clamp(2.0 * err, -self.MAX_TURN, self.MAX_TURN)
        dx, dy = target["x"] - self.x, target["y"] - self.y
        dist = math.hypot(dx, dy)
        if dist > 0.03:
            heading = wrap_angle(math.atan2(dy, dx) - self.yaw)
            v = clamp(0.8 * dist, 0.0, self.MAX_SPEED) * max(0.0, math.cos(heading))
            return v, clamp(2.0 * heading, -self.MAX_TURN, self.MAX_TURN)
        if target["yaw"] is not None and abs(wrap_angle(target["yaw"] - self.yaw)) > 0.02:
            return 0.0, clamp(2.0 * wrap_angle(target["yaw"] - self.yaw), -self.MAX_TURN, self.MAX_TURN)
        self.target = None
        self.emit("DRNavigateModule", "arrive", {"x": self.x, "y": self.y})
        return 0.0, 0.0

    def _sensor_distance(self, angle_offset, max_range=4.0):
        best = max_range
        heading = self.yaw + angle_offset
        for ox, oy in self.obstacles:
            dx, dy = ox - self.x, oy - self.y
            along = dx * math.cos(heading) + dy * math.sin(heading)
            across = abs(-dx * math.sin(heading) + dy * math.cos(heading))
            if along > 0 and across < 0.25:
                best = min(best, along)
        return best

    def _front_distance(self):
        return self._sensor_distance(0.0)

    # ------------------------------------------------------------------ bucles
    def run(self):
        dt = 1.0 / self.rate_hz
        tick = 0
        replay_lines = self._load_replay()
        while not self._stop.wait(dt):
            tick += 1
            self.step(dt)
            if self.pose_enabled and tick % max(1, int(self.rate_hz / 15)) == 0:
                self.emit("DRPose", "pose", {"base": {"x": self.x, "y": self.y, "yaw": self.yaw,
                                                      "speed": self.speed}})
            if self.imu_enabled and tick % max(1, int(self.rate_hz / 30)) == 0:
                half = self.yaw / 2.0
                self.emit("DRIMU", "imu", {"converged": True,
                                           "quat": {"x": 0.0, "y": 0.0, "z": math.sin(half), "w": math.cos(half)}})
            if tick % max(1, int(self.rate_hz / 10)) == 0:
                status = self.base_status()
                key = (status["kickstand"], status["pole"], status["charging"], int(status["battery"]))
                if key != self._last_status:
                    self._last_status = key
                    self.emit("DRBase", "status", status)
                self.emit("DRMotor", "position", {"percent": round(self.tilt, 3)})
                if self.ultrasonic_running:
                    # ASSUMED: 5 sensores, de izquierda a derecha, distancia en metros
                    for index, offset in enumerate((1.2, 0.6, 0.0, -0.6, -1.2)):
                        self.emit("DRUltrasonic", "measurement",
                                  {"sensor": index, "distance": round(self._sensor_distance(offset), 3)})
                if self.travel_running and abs(self.speed) > 1e-3:
                    inches = self.speed * 0.1 / 0.0254
                    self.emit("DRBase", "travel", {"leftInches": inches, "rightInches": inches})
            if replay_lines and tick % max(1, int(self.rate_hz / 10)) == 0:
                event = replay_lines[(tick // 5) % len(replay_lines)]
                self.emit(event.get("class", ""), event.get("key", ""), event.get("data", {}))

    def _load_replay(self):
        if not self.replay:
            return []
        with open(self.replay, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def stop(self):
        self._stop.set()


def make_handler(sim):
    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            conn = Connection(self.request)
            with sim.lock:
                sim.connections.add(conn)
            buf = b""
            try:
                while True:
                    data = self.request.recv(65536)
                    if not data:
                        break
                    buf += data
                    *lines, buf = buf.split(b"\n")
                    for line in lines:
                        if not line.strip():
                            continue
                        try:
                            sim.handle_command(conn, json.loads(line))
                        except (ValueError, TypeError) as exc:
                            LOG.debug("comando inválido %r: %s", line[:100], exc)
            except OSError:
                pass
            finally:
                with sim.lock:
                    sim.connections.discard(conn)
    return Handler


class UnixServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


class TCPServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


def main(argv=None):
    parser = argparse.ArgumentParser(description="Simulador de la API local del Double 3")
    parser.add_argument("--socket", default=os.environ.get("D3_SIM_SOCKET", "/tmp/doubleapi_sim"),
                        help="ruta del socket Unix que emula /tmp/doubleapi")
    parser.add_argument("--tcp-port", type=int, default=0, help="además, escucha en TCP (debug con nc)")
    parser.add_argument("--replay", help="fixture JSONL (sanitizado) para reproducir en bucle")
    parser.add_argument("-v", "--verbose", action="store_true")
    args, _ = parser.parse_known_args(argv)  # ignora --ros-args al lanzarse desde ros2 launch
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    sim = D3Simulator(replay=args.replay)
    servers = []
    if os.path.exists(args.socket):
        os.remove(args.socket)
    servers.append(UnixServer(args.socket, make_handler(sim)))
    if args.tcp_port:
        servers.append(TCPServer(("127.0.0.1", args.tcp_port), make_handler(sim)))
    for server in servers:
        threading.Thread(target=server.serve_forever, daemon=True).start()
    LOG.info("d3_sim listo en %s%s", args.socket, " y tcp:%d" % args.tcp_port if args.tcp_port else "")
    try:
        sim.run()
    except KeyboardInterrupt:
        pass
    finally:
        sim.stop()
        for server in servers:
            server.shutdown()
            server.server_close()
        if os.path.exists(args.socket):
            os.remove(args.socket)


if __name__ == "__main__":
    main()
