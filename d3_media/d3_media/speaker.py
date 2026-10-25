"""Salida de audio hacia el parlante del D3 (cola serial, como ALTextToSpeech)."""
import threading

from d3_sdk_client import play_audio

from .tts import TextToSpeech


class Speaker:
    def __init__(self, host, port, token, logger=None, tts_backend="auto"):
        self.host, self.port, self.token = host, port, token
        self.logger = logger
        self._tts = None
        self._tts_backend = tts_backend
        self._lock = threading.Lock()   # una sola reproducción a la vez
        self._cancel = threading.Event()
        self.language = "English"

    @property
    def tts(self):
        if self._tts is None:
            self._tts = TextToSpeech(self._tts_backend)
            if self.logger:
                self.logger.info("TTS backend: %s" % self._tts.backend)
        return self._tts

    def say(self, text, language=None, blocking=True):
        """Sintetiza y reproduce. Devuelve (ok, mensaje). Con blocking=False lo hace en un hilo."""
        if not blocking:
            threading.Thread(target=self.say, args=(text, language, True), daemon=True).start()
            return True, "speaking asynchronously"
        try:
            wav = self.tts.synthesize(text, language or self.language)
        except Exception as exc:  # noqa: BLE001
            return False, "TTS falló: %s" % exc
        return self.play(wav, "wav")

    def play(self, data=b"", fmt="wav", url=None):
        with self._lock:
            self._cancel.clear()
            return play_audio(self.host, self.port, self.token, data, fmt=fmt, url=url, cancel_event=self._cancel)

    def cancel(self):
        self._cancel.set()
