#!/usr/bin/env python3
"""d3_agent: puente entre la red del laboratorio y la API local del Double 3.

Corre en la cabeza del D3 (Ubuntu 18.04, Python 3.6) y solo usa la stdlib. Expone un puerto TCP con token
que el host ROS 2 usa para:
  - control: reenviar comandos/eventos JSON a /tmp/doubleapi (una conexión al socket por cliente),
  - video:   frames JPEG de la cámara (camera.enable template v4l2 -> /dev/video9 -> GStreamer),
  - audio:   PCM S16LE del micrófono (arecord),
  - play:    reproducir WAV/URL en el parlante (aplay / GStreamer).
También sirve las páginas de pantalla (show_text, get_input) en 127.0.0.1 para el accessoryWebView.

Protocolo: ver d3_sdk_client/protocol.py. Uso típico en el robot:
    D3_TOKEN=... python3 d3_agent.py
En simulación (d3_sim) se usan los comandos de prueba: --profile sim
"""
import argparse
import hmac
import json
import logging
import os
import shlex
import signal
import socket
import socketserver
import struct
import subprocess
import sys
import tempfile
import threading
import time
import wave

from http.server import BaseHTTPRequestHandler, HTTPServer  # 3.6 no trae ThreadingHTTPServer

VERSION = "0.1.0"
LOG = logging.getLogger("d3_agent")
HERE = os.path.dirname(os.path.abspath(__file__))

PROFILES = {
    "robot": {
        "video_cmd": ("gst-launch-1.0 -q v4l2src device={device} ! videoconvert ! videoscale ! videorate ! "
                      "video/x-raw,width={width},height={height},framerate={fps}/1 ! "
                      "jpegenc quality={quality} ! fdsink fd=1"),
        "audio_cmd": "arecord -q -D {device} -f S16_LE -r {rate} -c {channels} -t raw",
        "play_wav_cmd": "aplay -q {file}",
        "play_url_cmd": "gst-launch-1.0 -q playbin uri={url}",
        "video_device": "/dev/video9",
        "audio_device": "default",
        "enable_camera": True,
    },
    "sim": {
        "video_cmd": ("gst-launch-1.0 -q videotestsrc is-live=true pattern=ball ! "
                      "video/x-raw,width={width},height={height},framerate={fps}/1 ! "
                      "jpegenc quality={quality} ! fdsink fd=1"),
        "audio_cmd": ("gst-launch-1.0 -q audiotestsrc is-live=true wave=silence ! "
                      "audio/x-raw,format=S16LE,rate={rate},channels={channels},layout=interleaved ! fdsink fd=1"),
        "play_wav_cmd": "null",
        "play_url_cmd": "null",
        "video_device": "",
        "audio_device": "",
        "enable_camera": False,
    },
}


def encode_line(obj):
    return (json.dumps(obj, separators=(",", ":")) + "\n").encode("utf-8")


class LineBuffer(object):
    def __init__(self):
        self._buf = b""

    def feed(self, data):
        self._buf += data
        parts = self._buf.split(b"\n")
        self._buf = parts.pop()
        return [p.strip() for p in parts if p.strip()]


def read_handshake(sock, limit=4096, timeout=5.0):
    sock.settimeout(timeout)
    buf = b""
    while b"\n" not in buf:
        chunk = sock.recv(1024)
        if not chunk:
            raise ConnectionError("cerrado en handshake")
        buf += chunk
        if len(buf) > limit:
            raise ValueError("handshake demasiado largo")
    line, rest = buf.split(b"\n", 1)
    sock.settimeout(None)
    return json.loads(line.decode("utf-8")), rest


def make_event(key, data):
    return {"timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
            "class": "DRAgent", "key": key, "data": data}


class Agent(object):
    def __init__(self, args):
        self.args = args
        profile = dict(PROFILES[args.profile])
        for key in ("video_cmd", "audio_cmd", "play_wav_cmd", "play_url_cmd", "video_device", "audio_device"):
            value = getattr(args, key, None)
            if value:
                profile[key] = value
        if args.no_enable_camera:
            profile["enable_camera"] = False
        self.profile = profile
        self.control_clients = set()
        self.clients_lock = threading.Lock()
        self.players = set()
        self.players_lock = threading.Lock()
        self.record_lock = threading.Lock()
        self.record_file = open(args.record, "a") if args.record else None

    # ---------------------------------------------------------------- utilidades
    def api_connect(self):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(self.args.api)
        return sock

    def api_command(self, command, data=None):
        """Envía un comando suelto a la API (conexión efímera)."""
        try:
            sock = self.api_connect()
            msg = {"c": command}
            if data is not None:
                msg["d"] = data
            sock.sendall(encode_line(msg))
            time.sleep(0.1)
            sock.close()
            return True
        except OSError as exc:
            LOG.warning("no se pudo enviar %s a la API: %s", command, exc)
            return False

    def broadcast(self, event):
        payload = encode_line(event)
        with self.clients_lock:
            clients = list(self.control_clients)
        for client in clients:
            try:
                client.sendall(payload)
            except OSError:
                pass

    def record(self, line):
        if self.record_file is not None:
            with self.record_lock:
                self.record_file.write(line.decode("utf-8", "replace") + "\n")
                self.record_file.flush()

    def kill_players(self):
        with self.players_lock:
            players = list(self.players)
        for proc in players:
            try:
                proc.terminate()
            except OSError:
                pass
        return len(players)

    # ---------------------------------------------------------------- roles
    def handle(self, sock, addr):
        try:
            hello, rest = read_handshake(sock)
        except (ValueError, OSError, ConnectionError) as exc:
            LOG.info("handshake inválido desde %s: %s", addr, exc)
            sock.close()
            return
        token = str(hello.get("auth", ""))
        if not hmac.compare_digest(token.encode(), self.args.token.encode()):
            LOG.warning("token inválido desde %s", addr[0])
            sock.sendall(encode_line({"ok": False, "error": "token inválido"}))
            sock.close()
            return
        role = hello.get("role")
        handler = getattr(self, "role_%s" % role, None)
        if handler is None:
            sock.sendall(encode_line({"ok": False, "error": "rol desconocido: %s" % role}))
            sock.close()
            return
        LOG.info("cliente %s rol=%s", addr[0], role)
        try:
            handler(sock, hello, rest)
        except Exception:  # noqa: BLE001
            LOG.exception("error en rol %s", role)
        finally:
            try:
                sock.close()
            except OSError:
                pass

    def role_control(self, sock, hello, rest):
        try:
            api = self.api_connect()
        except OSError as exc:
            sock.sendall(encode_line({"ok": False, "error": "API del D3 no disponible: %s" % exc}))
            return
        sock.sendall(encode_line({"ok": True, "version": VERSION, "profile": self.args.profile}))
        with self.clients_lock:
            self.control_clients.add(sock)

        def api_to_client():
            buf = LineBuffer()
            try:
                while True:
                    data = api.recv(65536)
                    if not data:
                        break
                    for line in buf.feed(data):
                        self.record(line)
                        sock.sendall(line + b"\n")
            except OSError:
                pass
            finally:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

        reader = threading.Thread(target=api_to_client, daemon=True)
        reader.start()
        buf = LineBuffer()
        pending = buf.feed(rest)
        try:
            while True:
                for line in pending:
                    self.control_line(line, api, sock)
                data = sock.recv(65536)
                if not data:
                    break
                pending = buf.feed(data)
        except OSError:
            pass
        finally:
            with self.clients_lock:
                self.control_clients.discard(sock)
            api.close()

    def control_line(self, line, api, sock):
        try:
            msg = json.loads(line.decode("utf-8"))
        except ValueError:
            return
        command = msg.get("c", "")
        if not command.startswith("agent."):
            api.sendall(line + b"\n")
            return
        if command == "agent.ping":
            sock.sendall(encode_line(make_event("pong", {"version": VERSION})))
        elif command == "agent.info":
            sock.sendall(encode_line(make_event("info", {
                "version": VERSION, "profile": self.args.profile, "python": sys.version.split()[0],
                "pages_url": "http://127.0.0.1:%d/" % self.args.pages_port,
                "roles": ["control", "video", "audio", "play"]})))
        elif command == "agent.audio.stop":
            count = self.kill_players()
            sock.sendall(encode_line(make_event("audioStopped", {"stopped": count})))

    def role_video(self, sock, hello, rest):
        params = {
            "width": int(hello.get("width", 640)), "height": int(hello.get("height", 400)),
            "fps": int(hello.get("fps", 10)), "quality": int(hello.get("quality", 70)),
            "device": self.profile["video_device"],
        }
        if self.profile["enable_camera"]:
            self.api_command("camera.enable", {"template": "v4l2"})
            time.sleep(1.0)
        cmd = self.profile["video_cmd"].format(**params)
        proc = subprocess.Popen(shlex.split(cmd), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
        sock.sendall(encode_line({"ok": True, "width": params["width"], "height": params["height"]}))
        buf = b""
        try:
            while True:
                chunk = proc.stdout.read(65536)
                if not chunk:
                    break
                buf += chunk
                while True:
                    start = buf.find(b"\xff\xd8")
                    if start < 0:
                        buf = b""
                        break
                    end = buf.find(b"\xff\xd9", start + 2)
                    if end < 0:
                        buf = buf[start:]
                        break
                    frame = buf[start:end + 2]
                    buf = buf[end + 2:]
                    sock.sendall(struct.pack(">I", len(frame)) + frame)
        except OSError:
            pass
        finally:
            proc.terminate()
            proc.wait()

    def role_audio(self, sock, hello, rest):
        params = {"rate": int(hello.get("rate", 16000)), "channels": int(hello.get("channels", 1)),
                  "device": self.profile["audio_device"]}
        cmd = self.profile["audio_cmd"].format(**params)
        proc = subprocess.Popen(shlex.split(cmd), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
        sock.sendall(encode_line({"ok": True, "rate": params["rate"], "channels": params["channels"]}))
        try:
            while True:
                chunk = proc.stdout.read(3200)
                if not chunk:
                    break
                sock.sendall(chunk)
        except OSError:
            pass
        finally:
            proc.terminate()
            proc.wait()

    def role_play(self, sock, hello, rest):
        sock.sendall(encode_line({"ok": True}))
        buf = rest
        while b"\n" not in buf:
            chunk = sock.recv(4096)
            if not chunk:
                return
            buf += chunk
        line, buf = buf.split(b"\n", 1)
        header = json.loads(line.decode("utf-8"))
        fmt = header.get("format", "wav")
        size = int(header.get("size", 0))
        if size > self.args.max_play_bytes:
            sock.sendall(encode_line({"done": False, "error": "audio demasiado grande"}))
            return
        while len(buf) < size:
            chunk = sock.recv(min(65536, size - len(buf)))
            if not chunk:
                return
            buf += chunk
        tmp_path = None
        try:
            if fmt == "url":
                cmd_tpl, values = self.profile["play_url_cmd"], {"url": shlex.quote(header.get("url", ""))}
            else:
                fd, tmp_path = tempfile.mkstemp(suffix=".wav", prefix="d3_agent_")
                with os.fdopen(fd, "wb") as fh:
                    fh.write(buf[:size])
                cmd_tpl, values = self.profile["play_wav_cmd"], {"file": shlex.quote(tmp_path)}
            ok, error = self.run_player(cmd_tpl, values, tmp_path)
            sock.sendall(encode_line({"done": ok, "error": error}))
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)

    def run_player(self, cmd_tpl, values, wav_path):
        if cmd_tpl == "null":  # simulación: espera la duración del WAV
            duration = 0.2
            if wav_path:
                try:
                    with wave.open(wav_path) as wav:
                        duration = wav.getnframes() / float(wav.getframerate() or 1)
                except (wave.Error, EOFError):
                    pass
            time.sleep(min(duration, 30.0))
            return True, "ok"
        proc = subprocess.Popen(shlex.split(cmd_tpl.format(**values)),
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        with self.players_lock:
            self.players.add(proc)
        try:
            _, err = proc.communicate()
        finally:
            with self.players_lock:
                self.players.discard(proc)
        if proc.returncode == 0:
            return True, "ok"
        if proc.returncode in (-signal.SIGTERM, 143):
            return False, "detenido"
        return False, (err or b"").decode("utf-8", "replace").strip()[:200] or "código %d" % proc.returncode


class ScreenPagesHandler(BaseHTTPRequestHandler):
    """Sirve d3_agent/pages y recibe respuestas de get_input (POST /event)."""
    agent = None
    pages_dir = os.path.join(HERE, "pages")

    def log_message(self, fmt, *args):  # silencia el log por request
        LOG.debug("pages: " + fmt, *args)

    def do_GET(self):
        path = self.path.split("?", 1)[0].lstrip("/") or "index.html"
        full = os.path.normpath(os.path.join(self.pages_dir, path))
        if not full.startswith(self.pages_dir) or not os.path.isfile(full):
            self.send_error(404)
            return
        ctype = "text/html; charset=utf-8" if full.endswith(".html") else "application/octet-stream"
        with open(full, "rb") as fh:
            body = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/event":
            self.send_error(404)
            return
        length = min(int(self.headers.get("Content-Length", 0)), 65536)
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except ValueError:
            self.send_error(400)
            return
        self.agent.broadcast(make_event(str(data.get("key", "input")), data))
        self.send_response(204)
        self.end_headers()


class ThreadingHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True


class AgentTCPServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--listen", default=os.environ.get("D3_AGENT_LISTEN", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("D3_PORT", 22022)))
    parser.add_argument("--token", default=os.environ.get("D3_TOKEN", ""))
    parser.add_argument("--token-file", default="/etc/d3_agent/token")
    parser.add_argument("--api", default=os.environ.get("D3_API_SOCKET", "/tmp/doubleapi"))
    parser.add_argument("--profile", choices=sorted(PROFILES), default="robot")
    parser.add_argument("--video-cmd", dest="video_cmd")
    parser.add_argument("--audio-cmd", dest="audio_cmd")
    parser.add_argument("--play-wav-cmd", dest="play_wav_cmd")
    parser.add_argument("--play-url-cmd", dest="play_url_cmd")
    parser.add_argument("--video-device", dest="video_device")
    parser.add_argument("--audio-device", dest="audio_device")
    parser.add_argument("--no-enable-camera", action="store_true")
    parser.add_argument("--pages-port", type=int, default=8081)
    parser.add_argument("--pages-listen", default="127.0.0.1")
    parser.add_argument("--pages-dir", default=os.path.join(HERE, "pages"))
    parser.add_argument("--max-play-bytes", type=int, default=20 * 1024 * 1024)
    parser.add_argument("--record", help="guarda todos los eventos recibidos (JSONL crudo, NO subir al repo)")
    parser.add_argument("--allow-insecure-token", action="store_true", help="solo para simulación local")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    if not args.token and os.path.isfile(args.token_file):
        with open(args.token_file) as fh:
            args.token = fh.read().strip()
    if (not args.token or args.token == "changeme") and not args.allow_insecure_token:
        parser.error("define un token propio (D3_TOKEN o --token-file); 'changeme' y vacío no se aceptan")
    return args


def main(argv=None):
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    agent = Agent(args)

    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            agent.handle(self.request, self.client_address)

    ScreenPagesHandler.agent = agent
    ScreenPagesHandler.pages_dir = os.path.abspath(args.pages_dir)
    pages = ThreadingHTTPServer((args.pages_listen, args.pages_port), ScreenPagesHandler)
    threading.Thread(target=pages.serve_forever, daemon=True).start()
    server = AgentTCPServer((args.listen, args.port), Handler)
    LOG.info("d3_agent %s escuchando en %s:%d (perfil %s, API %s, páginas %s:%d)", VERSION, args.listen,
             args.port, args.profile, args.api, args.pages_listen, args.pages_port)
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=server.shutdown).start())
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        pages.shutdown()
        agent.kill_players()


if __name__ == "__main__":
    main()
