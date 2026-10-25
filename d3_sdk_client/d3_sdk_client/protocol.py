"""Protocolo de cable entre el host ROS 2 y `d3_agent` (o `d3_sim`).

Una conexión TCP por "rol". Siempre la abre el host (la regla de conectividad funciona detrás del NAT
de Docker Desktop). La primera línea es el handshake JSON:

    {"auth": "<token>", "role": "control" | "video" | "audio" | "play", ...opciones}\n

y el agente responde con una línea `{"ok": true}` o `{"ok": false, "error": "..."}`.

- control: JSON por línea en ambos sentidos. Del host salen comandos D3 `{"c": ..., "d": {...}}`;
           los que empiezan por `agent.` los atiende el agente y el resto se reenvía a /tmp/doubleapi.
           Del agente llegan eventos D3 `{"class": ..., "key": ..., "data": {...}}`.
- video:   frames JPEG con prefijo de longitud (4 bytes big-endian).
- audio:   PCM S16LE crudo (la tasa y los canales se piden en el handshake).
- play:    el host envía `{"format": "wav", "size": N}\n` + N bytes; el agente responde
           `{"done": true}` cuando termina de reproducir.
"""
import json
import struct

DEFAULT_PORT = 22022
ROLES = ("control", "video", "audio", "play")


def encode_line(obj):
    return (json.dumps(obj, separators=(",", ":")) + "\n").encode("utf-8")


def encode_frame(payload):
    return struct.pack(">I", len(payload)) + payload


class LineBuffer:
    """Acumula bytes y devuelve líneas completas (el SDK oficial no hace framing)."""

    def __init__(self):
        self._buf = b""

    def feed(self, data):
        self._buf += data
        *lines, self._buf = self._buf.split(b"\n")
        return [line.decode("utf-8", "replace").strip() for line in lines if line.strip()]


def event_name(event):
    return "%s.%s" % (event.get("class", ""), event.get("key", ""))
