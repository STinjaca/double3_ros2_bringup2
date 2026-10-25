"""Cliente Python para hablar con el Double 3 a través de `d3_agent` (o `d3_sim`)."""
from .client import D3Client, HandshakeError, open_role
from .media import AudioStream, VideoStream, play_audio
from .protocol import DEFAULT_PORT, LineBuffer, encode_frame, encode_line, event_name

__all__ = [
    "D3Client", "HandshakeError", "open_role", "AudioStream", "VideoStream", "play_audio",
    "DEFAULT_PORT", "LineBuffer", "encode_frame", "encode_line", "event_name",
]
