"""d3_interface_node: equivalente de naoqi_interface_node (la tablet de Pepper -> la pantalla del D3).

Todo se muestra con gui.accessoryWebView.open. Las páginas de texto y de entrada las sirve d3_agent en
el propio robot (http://127.0.0.1:<pages_port>), así que no dependen de la red del host. Solo
show_topic_stream y take_and_show_picture necesitan que el D3 llegue a web_video_server del host
(parámetro video_server_ip = HOST_IP).
"""
import os
import socket
import uuid
from urllib.parse import quote, urlencode

import rclpy
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from naoqi_utilities_msgs.srv import GetInput, SendURL, ShowText
from std_srvs.srv import SetBool, Trigger

from d3_sdk_client.ros_base import D3Node

# ms por palabra según el idioma (como show_words.html de Pepper)
WORD_MS = {"english": 330, "spanish": 380}


def detect_host_ip():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("192.0.2.1", 80))  # no envía nada; solo resuelve la interfaz de salida
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


class D3Interface(D3Node):
    def __init__(self):
        super().__init__("d3_interface_node", events=["DRAgent.input", "DRGUI.accessoryWebView.open"])
        self.declare_parameter("video_server_ip", os.environ.get("HOST_IP", "") or detect_host_ip())
        self.declare_parameter("video_server_port", 8080)
        self.declare_parameter("pages_base_url", "http://127.0.0.1:8081")
        self.declare_parameter("input_timeout", 30.0)
        self.declare_parameter("camera_topic", "camera/front/image_raw")
        self.video_base = "http://%s:%d" % (self.get_parameter("video_server_ip").value,
                                            self.get_parameter("video_server_port").value)
        self.pages = self.get_parameter("pages_base_url").value.rstrip("/")
        group = ReentrantCallbackGroup()
        self.create_service(SendURL, "show_image", self.show_url)
        self.create_service(SendURL, "show_webview", self.show_url)
        self.create_service(SendURL, "play_video", self.show_url)
        self.create_service(Trigger, "hide_tablet", self.hide)
        self.create_service(SendURL, "show_topic_stream", self.show_topic_stream)
        self.create_service(ShowText, "show_text", self.show_text)
        self.create_service(GetInput, "get_input", self.get_input, callback_group=group)
        self.create_service(Trigger, "take_and_show_picture", self.take_and_show_picture)
        self.create_service(SetBool, "toggle_app_launcher", self.toggle_app_launcher)
        self.get_logger().info("web_video_server para la pantalla: %s" % self.video_base)

    def open_url(self, response, url, message):
        return self.send_or_fail(response, "gui.accessoryWebView.open",
                                 {"url": url, "trusted": False, "transparent": False}, message)

    def show_url(self, request, response):
        return self.open_url(response, request.url, "showing %s" % request.url)

    def hide(self, _request, response):
        return self.send_or_fail(response, "gui.accessoryWebView.close", None, "screen content hidden")

    def _absolute_topic(self, topic):
        if topic.startswith("/"):
            return topic
        ns = self.get_namespace().rstrip("/")
        return "%s/%s" % (ns, topic)

    def show_topic_stream(self, request, response):
        url = "%s/stream?topic=%s" % (self.video_base, quote(self._absolute_topic(request.url), safe="/"))
        return self.open_url(response, url, "showing topic stream %s" % request.url)

    def show_text(self, request, response):
        ms = WORD_MS.get((request.language or "english").lower(), 350)
        url = "%s/text.html?%s" % (self.pages, urlencode({"text": request.text, "ms": ms}))
        return self.open_url(response, url, "showing text")

    def get_input(self, request, response):
        if request.type not in ("text", "bool", "list"):
            response.input = "ERROR"
            return response
        request_id = uuid.uuid4().hex[:12]
        url = "%s/input.html?%s" % (self.pages, urlencode({"type": request.type, "content": request.content,
                                                            "id": request_id}))
        if not self.d3.send("gui.accessoryWebView.open", {"url": url, "trusted": False}):
            response.input = "ERROR"
            return response
        timeout = float(self.get_parameter("input_timeout").value)
        data = self.d3.wait_event("DRAgent.input", timeout=timeout,
                                  predicate=lambda d: d.get("id") == request_id)
        response.input = str(data.get("value", "")) if data else "TIMEOUT"
        return response

    def take_and_show_picture(self, _request, response):
        # web_video_server /snapshot devuelve un único frame: equivale a tomar y mostrar la foto.
        url = "%s/snapshot?topic=%s" % (self.video_base, quote(self._absolute_topic(
            self.get_parameter("camera_topic").value), safe="/"))
        return self.open_url(response, url, "showing picture")

    def toggle_app_launcher(self, request, response):
        # En el D3 lo más parecido al AppLauncher es la interfaz propia de Double (gui.show / gui.hide).
        return self.send_or_fail(response, "gui.show" if request.data else "gui.hide", None,
                                 "Double GUI %s" % ("shown" if request.data else "hidden"))


def main(args=None):
    rclpy.init(args=args)
    node = D3Interface()
    executor = MultiThreadedExecutor(num_threads=2)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
