"""Reconocimiento de voz en el host (Vosk, offline) sobre el PCM 16 kHz que llega del D3.

Es opcional: si `vosk` o el modelo no están, `available` es False y los servicios responden
sin resultados en vez de fallar. Los modelos se descargan aparte (no se suben al repo) en
D3_VOSK_MODELS_DIR/<código>, por ejemplo /models/vosk/es y /models/vosk/en.
"""
import json
import os
import threading

from .tts import language_code

try:
    import vosk  # type: ignore
    vosk.SetLogLevel(-1)
except ImportError:  # pragma: no cover - depende de la imagen
    vosk = None


class SpeechRecognizer:
    def __init__(self, models_dir=None, sample_rate=16000):
        self.models_dir = models_dir or os.environ.get("D3_VOSK_MODELS_DIR", "/models/vosk")
        self.sample_rate = sample_rate
        self._models = {}
        self._lock = threading.Lock()
        self._recognizer = None
        self._listeners = []
        self.language = "en"
        self.vocabulary = []
        self.enabled = False

    @property
    def available(self):
        return vosk is not None and self._model_path(self.language) is not None

    def _model_path(self, code):
        for candidate in (code, code.split("-")[0]):
            path = os.path.join(self.models_dir, candidate)
            if os.path.isdir(path):
                return path
        return None

    def _model(self, code):
        if code not in self._models:
            path = self._model_path(code)
            if vosk is None or path is None:
                return None
            self._models[code] = vosk.Model(path)
        return self._models[code]

    def configure(self, language=None, vocabulary=None, enabled=None):
        """Equivalente a ALSpeechRecognition: idioma, vocabulario (gramática) y activación."""
        with self._lock:
            if language:
                self.language = language_code(language)
            if vocabulary is not None:
                self.vocabulary = [w for w in vocabulary if w]
            if enabled is not None:
                self.enabled = enabled
            self._recognizer = self._make_recognizer(self.vocabulary) if self.enabled else None
            return self._recognizer is not None or not self.enabled

    def _make_recognizer(self, vocabulary):
        model = self._model(self.language)
        if model is None:
            return None
        if vocabulary:
            grammar = json.dumps([w.lower() for w in vocabulary] + ["[unk]"])
            return vosk.KaldiRecognizer(model, self.sample_rate, grammar)
        return vosk.KaldiRecognizer(model, self.sample_rate)

    def on_words(self, callback):
        """callback(word, confidence) por cada palabra reconocida en modo continuo."""
        self._listeners.append(callback)

    def feed(self, pcm):
        with self._lock:
            recognizer = self._recognizer
        if recognizer is None or not recognizer.AcceptWaveform(pcm):
            return
        result = json.loads(recognizer.Result())
        for item in result.get("result", []):
            word = item.get("word", "")
            if word and word != "[unk]":
                for callback in self._listeners:
                    callback(word, float(item.get("conf", 0.0)))

    def listen_once(self, pcm_source, expected=(), language=None, timeout=8.0, partial=None):
        """Una sola escucha (acción `listen`). pcm_source(timeout) devuelve bytes o None."""
        code = language_code(language) if language else self.language
        model = self._model(code)
        if model is None:
            return []
        if expected:
            rec = vosk.KaldiRecognizer(model, self.sample_rate, json.dumps([w.lower() for w in expected] + ["[unk]"]))
        else:
            rec = vosk.KaldiRecognizer(model, self.sample_rate)
        import time
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            chunk = pcm_source(0.5)
            if not chunk:
                continue
            if rec.AcceptWaveform(chunk):
                text = json.loads(rec.Result()).get("text", "").replace("[unk]", "").strip()
                if text:
                    return [text]
            elif partial is not None:
                text = json.loads(rec.PartialResult()).get("partial", "")
                if text:
                    partial([text])
        text = json.loads(rec.FinalResult()).get("text", "").replace("[unk]", "").strip()
        return [text] if text else []
