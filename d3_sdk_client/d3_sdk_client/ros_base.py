"""Base común para los nodos ROS 2 del D3 (driver y capacidades).

Igual que los nodos naoqi_*, aceptan `--ip` / `--port` como argumentos de línea de comandos (así los
lanza el bringup), y además los parámetros ROS `robot_ip`, `robot_port`, `robot_token`. El token se toma
de la variable de entorno D3_TOKEN si no se pasa: nunca se escribe en archivos del repo.
"""
import argparse
import os
import sys

from rclpy.node import Node
from rclpy.utilities import remove_ros_args

from .client import D3Client

UNSUPPORTED = "unsupported on D3"


def parse_robot_args(argv=None):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--ip", default=None)
    parser.add_argument("--port", default=None)
    args, _ = parser.parse_known_args(remove_ros_args(argv if argv is not None else sys.argv)[1:])
    return args


class D3Node(Node):
    """Nodo con un D3Client ya conectado (en segundo plano) y utilidades de respuesta."""

    def __init__(self, name, events=(), cli_args=None, **kwargs):
        super().__init__(name, **kwargs)
        cli = cli_args or parse_robot_args()
        self.declare_parameter("robot_ip", cli.ip or os.environ.get("D3_IP", "127.0.0.1"))
        self.declare_parameter("robot_port", int(cli.port or os.environ.get("D3_PORT", 22022)))
        self.declare_parameter("robot_token", "")
        self.declare_parameter("request_timeout", 3.0)
        ip = self.get_parameter("robot_ip").value
        port = int(self.get_parameter("robot_port").value)
        token = self.get_parameter("robot_token").value or os.environ.get("D3_TOKEN", "")
        self.robot_ip, self.robot_port, self.robot_token = ip, port, token
        self.request_timeout = float(self.get_parameter("request_timeout").value)
        self.d3 = D3Client(ip, port, token)
        self.d3.on_connect(self._on_d3_connect)
        if events:
            self.d3.subscribe(list(events))
        self.d3.start()
        self.get_logger().info("conectando con d3_agent en %s:%d" % (ip, port))

    # Los nodos hijos sobrescriben esto para (re)configurar el robot tras cada conexión.
    def on_d3_connect(self):
        pass

    def _on_d3_connect(self):
        self.get_logger().info("conectado con d3_agent")
        self.on_d3_connect()

    # ------------------------------------------------------------- utilidades de servicios
    def unsupported(self, response, what=""):
        """Responde 'unsupported on D3' manteniendo el contrato (el servicio existe)."""
        if hasattr(response, "success"):
            response.success = False
            response.message = UNSUPPORTED + (": " + what if what else "")
        else:
            self.get_logger().warn("%s (%s)" % (UNSUPPORTED, what))
        return response

    def ok(self, response, message="ok"):
        if hasattr(response, "success"):
            response.success = True
            response.message = message
        return response

    def fail(self, response, message):
        if hasattr(response, "success"):
            response.success = False
            response.message = message
        self.get_logger().warn(message)
        return response

    def send_or_fail(self, response, command, data=None, message="ok"):
        if self.d3.send(command, data):
            return self.ok(response, message)
        return self.fail(response, "sin conexión con el D3 (%s)" % command)

    def destroy_node(self):
        self.d3.stop()
        return super().destroy_node()
