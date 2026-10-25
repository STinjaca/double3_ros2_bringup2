"""Texto a voz en el host. El D3 no tiene TTS: se sintetiza un WAV aquí y d3_agent lo reproduce.

Backends, en orden de preferencia:
  - piper:  voz neural (si existen el binario `piper` y un modelo .onnx en D3_PIPER_MODELS_DIR)
  - espeak-ng: siempre disponible en la imagen Docker (arm64 y amd64)
"""
import glob
import os
import shutil
import subprocess
import tempfile

# Nombres de idioma de NAOqi -> código ISO
LANGUAGES = {
    "english": "en", "spanish": "es", "french": "fr", "german": "de", "italian": "it",
    "portuguese": "pt", "brazilian": "pt-br", "japanese": "ja", "chinese": "zh",
}


def language_code(language, default="en"):
    if not language:
        return default
    lang = language.strip().lower()
    return LANGUAGES.get(lang, lang if len(lang) <= 5 else default)


class TextToSpeech:
    def __init__(self, backend="auto", piper_models_dir=None, espeak_speed=150):
        self.piper_models_dir = piper_models_dir or os.environ.get("D3_PIPER_MODELS_DIR", "/models/piper")
        self.espeak_speed = espeak_speed
        self.backend = self._choose(backend)

    def _choose(self, backend):
        if backend in ("auto", "piper") and shutil.which("piper") and glob.glob(
                os.path.join(self.piper_models_dir, "*.onnx")):
            return "piper"
        if backend == "piper":
            raise RuntimeError("piper no disponible (binario o modelos .onnx en %s)" % self.piper_models_dir)
        if shutil.which("espeak-ng"):
            return "espeak-ng"
        if shutil.which("espeak"):
            return "espeak"
        raise RuntimeError("no hay backend de TTS (instala espeak-ng)")

    def synthesize(self, text, language="en"):
        """Devuelve los bytes de un WAV con el texto hablado."""
        code = language_code(language)
        fd, path = tempfile.mkstemp(suffix=".wav", prefix="d3_tts_")
        os.close(fd)
        try:
            if self.backend == "piper":
                model = self._piper_model(code)
                subprocess.run(["piper", "--model", model, "--output_file", path], input=text.encode("utf-8"),
                               check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
            else:
                subprocess.run([self.backend, "-v", code, "-s", str(self.espeak_speed), "-w", path, text],
                               check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
            with open(path, "rb") as fh:
                return fh.read()
        finally:
            os.remove(path)

    def _piper_model(self, code):
        prefix = code.split("-")[0]
        models = sorted(glob.glob(os.path.join(self.piper_models_dir, "%s*.onnx" % prefix)))
        if not models:
            models = sorted(glob.glob(os.path.join(self.piper_models_dir, "*.onnx")))
        return models[0]
