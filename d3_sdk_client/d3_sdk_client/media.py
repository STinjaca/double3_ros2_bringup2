"""Streams de media del agente: video (JPEG), audio (PCM) y reproducción de WAV."""
import json
import logging
import struct
import threading

from .client import HandshakeError, open_role
from .protocol import LineBuffer, encode_line

LOG = logging.getLogger("d3_sdk_client.media")


def _recv_exact(sock, size, buf):
    while len(buf) < size:
        chunk = sock.recv(max(65536, size - len(buf)))
        if not chunk:
            raise ConnectionError("stream cerrado")
        buf += chunk
    return buf[:size], buf[size:]


class _StreamThread:
    role = None

    def __init__(self, host, port, token, callback, retry_delay=2.0, **options):
        self.host, self.port, self.token = host, int(port), token
        self.callback = callback
        self.options = options
        self.retry_delay = retry_delay
        self._stop = threading.Event()
        self._sock = None
        self._thread = threading.Thread(target=self._loop, daemon=True, name="d3-%s" % self.role)

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        sock = self._sock
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def _loop(self):
        while not self._stop.is_set():
            try:
                self._sock, rest = open_role(self.host, self.port, self.token, self.role, **self.options)
                self._consume(self._sock, rest)
            except (OSError, HandshakeError, ConnectionError, ValueError) as exc:
                if not self._stop.is_set():
                    LOG.info("stream %s caído (%s); reintento en %.1fs", self.role, exc, self.retry_delay)
            finally:
                if self._sock is not None:
                    self._sock.close()
                    self._sock = None
            self._stop.wait(self.retry_delay)

    def _consume(self, sock, rest):
        raise NotImplementedError


class VideoStream(_StreamThread):
    """callback(jpeg_bytes) por cada frame. Opciones: width, height, fps, quality."""
    role = "video"

    def _consume(self, sock, buf):
        while not self._stop.is_set():
            header, buf = _recv_exact(sock, 4, buf)
            (size,) = struct.unpack(">I", header)
            frame, buf = _recv_exact(sock, size, buf)
            self.callback(frame)


class AudioStream(_StreamThread):
    """callback(pcm_bytes) con PCM S16LE. Opciones: rate, channels, chunk_ms."""
    role = "audio"

    def _consume(self, sock, buf):
        if buf:
            self.callback(buf)
        while not self._stop.is_set():
            chunk = sock.recv(8192)
            if not chunk:
                raise ConnectionError("stream de audio cerrado")
            self.callback(chunk)


def play_audio(host, port, token, data=b"", fmt="wav", url=None, timeout=600.0, cancel_event=None):
    """Sube audio (o una URL con fmt="url") al agente y espera a que termine. Devuelve (ok, mensaje)."""
    try:
        sock, rest = open_role(host, port, token, "play", timeout=5.0)
    except (OSError, HandshakeError, ValueError) as exc:
        return False, "agente no disponible: %s" % exc
    try:
        header = {"format": fmt, "size": len(data)}
        if url:
            header["url"] = url
        sock.sendall(encode_line(header))
        if data:
            sock.sendall(data)
        sock.settimeout(0.5)
        lines = LineBuffer()
        pending = lines.feed(rest)
        waited = 0.0
        while waited < timeout:
            for line in pending:
                reply = json.loads(line)
                return bool(reply.get("done")), reply.get("error", "ok")
            if cancel_event is not None and cancel_event.is_set():
                return False, "cancelado"
            try:
                chunk = sock.recv(4096)
            except OSError:
                waited += 0.5
                pending = []
                continue
            if not chunk:
                return False, "el agente cerró la conexión"
            pending = lines.feed(chunk)
        return False, "timeout reproduciendo audio"
    finally:
        sock.close()
