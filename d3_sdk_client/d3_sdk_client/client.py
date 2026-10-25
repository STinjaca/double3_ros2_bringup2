"""Cliente del Double 3 basado en hilos (compatible con rclpy, sin asyncio).

Ejemplo:
    client = D3Client("192.0.2.10", 22022, token)
    client.on("DRBase.status", lambda data: print(data["battery"]))
    client.start()                         # conecta y reconecta solo
    client.subscribe(["DRBase.status"])
    client.send("base.requestStatus")
    client.repeat("drive", "navigate.drive", {"throttle": 0.2, "turn": 0}, period=0.2)
"""
import json
import logging
import socket
import threading
import time
from collections import defaultdict

from .protocol import DEFAULT_PORT, LineBuffer, encode_line, event_name

LOG = logging.getLogger("d3_sdk_client")


class HandshakeError(RuntimeError):
    pass


def open_role(host, port, token, role, timeout=5.0, **options):
    """Abre una conexión TCP con el agente y hace el handshake del rol. Devuelve (socket, sobrante)."""
    sock = socket.create_connection((host, port), timeout=timeout)
    try:
        hello = {"auth": token, "role": role}
        hello.update(options)
        sock.sendall(encode_line(hello))
        buf = b""
        while b"\n" not in buf:
            chunk = sock.recv(4096)
            if not chunk:
                raise HandshakeError("el agente cerró la conexión durante el handshake")
            buf += chunk
        line, rest = buf.split(b"\n", 1)
        reply = json.loads(line.decode("utf-8"))
        if not reply.get("ok"):
            raise HandshakeError(reply.get("error", "handshake rechazado"))
        sock.settimeout(None)
        return sock, rest
    except Exception:
        sock.close()
        raise


class D3Client:
    def __init__(self, host, port=DEFAULT_PORT, token="", reconnect_delay=(0.5, 5.0)):
        self.host = host
        self.port = int(port)
        self.token = token
        self._delay_min, self._delay_max = reconnect_delay
        self._sock = None
        self._send_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._handlers = defaultdict(list)
        self._connect_handlers = []
        self._subscriptions = set()
        self._latest = {}
        self._waiters = defaultdict(list)
        self._repeats = {}
        self._stop = threading.Event()
        self._connected = threading.Event()
        self._threads = []

    # ------------------------------------------------------------------ ciclo de vida
    def start(self):
        for target in (self._reader_loop, self._repeat_loop):
            thread = threading.Thread(target=target, daemon=True, name="d3-%s" % target.__name__)
            thread.start()
            self._threads.append(thread)
        return self

    def stop(self):
        self._stop.set()
        self._close_socket()

    @property
    def connected(self):
        return self._connected.is_set()

    def wait_connected(self, timeout=None):
        return self._connected.wait(timeout)

    # ------------------------------------------------------------------ API pública
    def send(self, command, data=None):
        """Envía un comando D3. Devuelve False si no hay conexión (no lanza excepción)."""
        msg = {"c": command}
        if data is not None:
            msg["d"] = data
        payload = encode_line(msg)
        with self._send_lock:
            sock = self._sock
            if sock is None:
                return False
            try:
                sock.sendall(payload)
                return True
            except OSError as exc:
                LOG.warning("fallo enviando %s: %s", command, exc)
                self._close_socket()
                return False

    def subscribe(self, events):
        # Los eventos DRAgent.* los genera d3_agent: no hace falta suscribirlos en la API del D3.
        events = {e for e in events if not e.startswith("DRAgent.")}
        new = events - self._subscriptions
        self._subscriptions |= events
        if new:
            self.send("events.subscribe", {"events": sorted(new)})

    def on(self, name, callback):
        """Registra callback(data) para `Clase.clave`, o callback(event) completo con "*"."""
        self._handlers[name].append(callback)

    def on_connect(self, callback):
        self._connect_handlers.append(callback)

    def latest(self, name, default=None):
        return self._latest.get(name, default)

    def wait_event(self, name, timeout=5.0, predicate=None):
        """Bloquea hasta recibir `name` (y que cumpla predicate). Devuelve data o None si vence."""
        self.subscribe([name])
        slot = {"event": threading.Event(), "data": None, "predicate": predicate}
        with self._state_lock:
            self._waiters[name].append(slot)
        got = slot["event"].wait(timeout)
        with self._state_lock:
            if slot in self._waiters[name]:
                self._waiters[name].remove(slot)
        return slot["data"] if got else None

    def request(self, command, data, reply_event, timeout=3.0, predicate=None):
        """Patrón petición/respuesta del D3: envía `command` y espera `reply_event` (se suscribe solo)."""
        self.subscribe([reply_event])
        slot = {"event": threading.Event(), "data": None, "predicate": predicate}
        with self._state_lock:
            self._waiters[reply_event].append(slot)
        try:
            if not self.send(command, data):
                return None
            return slot["data"] if slot["event"].wait(timeout) else None
        finally:
            with self._state_lock:
                if slot in self._waiters[reply_event]:
                    self._waiters[reply_event].remove(slot)

    def repeat(self, key, command, data=None, period=0.2):
        """Reenvía un comando periódicamente (watchdog de navigate.drive / tilt.move de 500 ms)."""
        with self._state_lock:
            first = key not in self._repeats
            self._repeats[key] = {"c": command, "d": data, "period": period, "next": 0.0}
        if first:
            self.send(command, data)

    def stop_repeat(self, key):
        with self._state_lock:
            return self._repeats.pop(key, None) is not None

    # ------------------------------------------------------------------ internos
    def _close_socket(self):
        sock, self._sock = self._sock, None
        self._connected.clear()
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()

    def _reader_loop(self):
        delay = self._delay_min
        while not self._stop.is_set():
            try:
                sock, rest = open_role(self.host, self.port, self.token, "control")
            except (OSError, HandshakeError, ValueError) as exc:
                LOG.info("sin conexión con %s:%s (%s); reintento en %.1fs", self.host, self.port, exc, delay)
                self._stop.wait(delay)
                delay = min(delay * 2, self._delay_max)
                continue
            delay = self._delay_min
            self._sock = sock
            self._connected.set()
            LOG.info("conectado a %s:%s", self.host, self.port)
            if self._subscriptions:
                self.send("events.subscribe", {"events": sorted(self._subscriptions)})
            for callback in list(self._connect_handlers):
                self._safe_call(callback)
            lines = LineBuffer()
            pending = lines.feed(rest)
            try:
                while not self._stop.is_set():
                    for line in pending:
                        self._dispatch_line(line)
                    data = sock.recv(65536)
                    if not data:
                        break
                    pending = lines.feed(data)
            except OSError:
                pass
            self._close_socket()
            if not self._stop.is_set():
                LOG.warning("conexión con el agente perdida; reconectando")

    def _dispatch_line(self, line):
        try:
            event = json.loads(line)
        except ValueError:
            LOG.debug("línea no JSON descartada: %r", line[:120])
            return
        if not isinstance(event, dict) or "class" not in event:
            return
        name = event_name(event)
        data = event.get("data")
        if data is None:
            data = {}
        self._latest[name] = data
        with self._state_lock:
            waiters = list(self._waiters.get(name, ()))
        for slot in waiters:
            predicate = slot["predicate"]
            if predicate is None or self._safe_call(predicate, data):
                slot["data"] = data
                slot["event"].set()
        for callback in self._handlers.get(name, ()):
            self._safe_call(callback, data)
        for callback in self._handlers.get("*", ()):
            self._safe_call(callback, event)

    @staticmethod
    def _safe_call(callback, *args):
        try:
            return callback(*args)
        except Exception:  # noqa: BLE001 - un callback roto no debe tumbar el lector
            LOG.exception("error en callback")
            return None

    def _repeat_loop(self):
        while not self._stop.wait(0.02):
            now = time.monotonic()
            with self._state_lock:
                due = []
                for item in self._repeats.values():
                    if now >= item["next"]:
                        item["next"] = now + item["period"]
                        due.append((item["c"], item["d"]))
            for command, data in due:
                self.send(command, data)
