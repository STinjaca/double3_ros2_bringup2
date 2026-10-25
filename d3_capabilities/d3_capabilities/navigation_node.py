"""d3_navigation_node: equivalente de naoqi_navigation_node."""
import math

import rclpy
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from naoqi_utilities_msgs.srv import Explore, MoveTo
from std_srvs.srv import Trigger

from d3_sdk_client.ros_base import D3Node


class D3Navigation(D3Node):
    def __init__(self):
        super().__init__("d3_navigation_node", events=["DRNavigateModule.arrive", "DRNavigateModule.cancelTarget",
                                                       "DRBase.status"])
        self.declare_parameter("move_timeout_base", 5.0)
        self.declare_parameter("move_timeout_per_meter", 6.0)
        self.declare_parameter("auto_retract_kickstand", True)
        group = ReentrantCallbackGroup()
        self.create_service(MoveTo, "move_to", self.move_to, callback_group=group)
        self.create_service(MoveTo, "navigate_to", self.navigate_to, callback_group=group)
        self.create_service(Explore, "start_exploring", lambda req, res: self.unsupported(res, "no exploration/SLAM"))
        self.create_service(Trigger, "stop_exploring", lambda req, res: self.unsupported(res, "no exploration/SLAM"))

    def _go(self, x, y, theta, relative):
        if self.get_parameter("auto_retract_kickstand").value:
            self.d3.send("base.kickstand.retract")
        if abs(x) < 1e-3 and abs(y) < 1e-3 and abs(theta) < 1e-3 and relative:
            return True  # movimiento nulo
        timeout = (self.get_parameter("move_timeout_base").value
                   + self.get_parameter("move_timeout_per_meter").value * math.hypot(x, y) + abs(theta) * 2.0)
        data = {"x": float(x), "y": float(y), "relative": relative}
        if abs(theta) > 1e-3 or not relative:
            data["angleRadians"] = float(theta)
        arrived = self.d3.request("navigate.target", data, "DRNavigateModule.arrive", timeout=timeout)
        if arrived is None:
            self.get_logger().warn("navigate.target no llegó en %.1fs; cancelando" % timeout)
            self.d3.send("navigate.cancelTarget")
            return False
        return True

    def move_to(self, request, response):
        # Igual que ALMotion.moveTo: bloqueante, relativo al robot (x adelante, y izquierda, theta rad).
        self._go(request.x_coordinate, request.y_coordinate, request.theta_coordinate, relative=True)
        return response  # MoveTo no tiene campos de respuesta (igual que el original)

    def navigate_to(self, request, response):
        # Sin mapa: coordenadas absolutas en el frame de odometría del D3 (DRPose).
        self._go(request.x_coordinate, request.y_coordinate, 0.0, relative=False)
        return response


def main(args=None):
    rclpy.init(args=args)
    node = D3Navigation()
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
