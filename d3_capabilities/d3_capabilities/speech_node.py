"""d3_speech_node: equivalente de naoqi_speech_node.

El D3 no tiene TTS ni ASR: la voz se sintetiza en el host (espeak-ng / Piper) y se reproduce en el
parlante del robot vía d3_agent; el reconocimiento usa Vosk sobre el topic `mic` del driver.
"""
import os

import rclpy
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from audio_common_msgs.msg import AudioData
from naoqi_utilities_msgs.msg import WordConfidence
from naoqi_utilities_msgs.srv import ConfigureSpeech, GetVolume, PlaySound, PlayWebStream, Say, SetVolume
from std_srvs.srv import Trigger

from d3_media.asr import SpeechRecognizer
from d3_media.speaker import Speaker
from d3_sdk_client.ros_base import D3Node


class D3Speech(D3Node):
    def __init__(self):
        super().__init__("d3_speech_node", events=["DRSpeaker.volume"])
        self.declare_parameter("language", "English")
        self.declare_parameter("tts_backend", "auto")
        self.declare_parameter("sounds_dir", "/workspace/sounds")
        self.language = self.get_parameter("language").value
        self.sounds_dir = self.get_parameter("sounds_dir").value
        self.speaker = Speaker(self.robot_ip, self.robot_port, self.robot_token, self.get_logger(),
                               self.get_parameter("tts_backend").value)
        self.speaker.language = self.language
        self.asr = SpeechRecognizer()
        self.asr.configure(language=self.language)
        self.asr.on_words(self.on_word)

        reentrant = ReentrantCallbackGroup()
        self.word_pub = self.create_publisher(WordConfidence, "word_recognized", 10)
        self.create_service(Say, "say", self.say, callback_group=reentrant)
        self.create_service(Trigger, "shut_up", self.shut_up, callback_group=reentrant)
        self.create_service(SetVolume, "set_volume", self.set_volume)
        self.create_service(GetVolume, "get_volume", self.get_volume, callback_group=reentrant)
        self.create_service(ConfigureSpeech, "configure_speech", self.configure_speech)
        self.create_service(PlaySound, "play_sound", self.play_sound, callback_group=reentrant)
        self.create_service(PlayWebStream, "play_web_stream", self.play_web_stream, callback_group=reentrant)
        self.create_service(Trigger, "stop_all_sounds", self.shut_up, callback_group=reentrant)
        self.create_subscription(AudioData, "mic", self.on_mic, 50)

    def on_d3_connect(self):
        self.d3.send("speaker.enable")

    # ------------------------------------------------------------------ voz
    def say(self, request, response):
        language = request.language or self.language
        ok, message = self.speaker.say(request.text, language, blocking=not request.asynchronous)
        response.success, response.message = ok, message
        return response

    def shut_up(self, _request, response):
        self.speaker.cancel()
        return self.send_or_fail(response, "agent.audio.stop", None, "audio stopped")

    # ------------------------------------------------------------------ volumen (0-100 <-> 0..1)
    def set_volume(self, request, response):
        volume = max(0, min(100, request.volume))
        return self.send_or_fail(response, "speaker.setVolume", {"percent": volume / 100.0}, "volume %d" % volume)

    def get_volume(self, _request, response):
        data = self.d3.request("speaker.requestVolume", None, "DRSpeaker.volume", timeout=self.request_timeout)
        data = data or self.d3.latest("DRSpeaker.volume") or {}
        percent = data.get("percent", data.get("volume", -1))
        response.volume = int(round(percent * 100)) if 0 <= percent <= 1 else int(percent)
        return response

    # ------------------------------------------------------------------ reconocimiento
    def configure_speech(self, request, response):
        if request.language:
            self.language = request.language
            self.speaker.language = request.language
        if not request.update_recognition_settings:
            return self.ok(response, "language set to %s" % self.language)
        ready = self.asr.configure(language=self.language, vocabulary=list(request.vocabulary),
                                   enabled=request.recognition_enabled)
        if request.recognition_enabled and not ready:
            return self.fail(response, "ASR no disponible: instala vosk y un modelo en %s/%s"
                             % (self.asr.models_dir, self.asr.language))
        state = "enabled" if request.recognition_enabled else "disabled"
        return self.ok(response, "recognition %s (%s, %d words)" % (state, self.language, len(request.vocabulary)))

    def on_mic(self, msg):
        if self.asr.enabled:
            self.asr.feed(bytes(msg.data))

    def on_word(self, word, confidence):
        self.word_pub.publish(WordConfidence(word=word, confidence=confidence))

    # ------------------------------------------------------------------ reproducción
    def play_sound(self, request, response):
        # En Pepper la ruta era del robot; aquí es un WAV del host (contenedor), relativo a sounds_dir.
        path = request.file_path
        if not os.path.isabs(path):
            path = os.path.join(self.sounds_dir, path)
        if not os.path.isfile(path):
            return self.fail(response, "no existe el archivo en el host: %s" % path)
        with open(path, "rb") as fh:
            ok, message = self.speaker.play(fh.read(), "wav")
        response.success, response.message = ok, message
        return response

    def play_web_stream(self, request, response):
        # Asíncrono como ALAudioPlayer.playWebStream
        import threading
        threading.Thread(target=self.speaker.play, kwargs={"fmt": "url", "url": request.url}, daemon=True).start()
        return self.ok(response, "streaming %s" % request.url)


def main(args=None):
    rclpy.init(args=args)
    node = D3Speech()
    executor = MultiThreadedExecutor(num_threads=3)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
