"""d3_perception_node: equivalente de naoqi_perception_node.

set_tracker_mode: `stop` funciona; los modos de seguimiento (start_head, start_move,
start_body_rotation) se implementarán con un detector de rostros sobre camera/front (fase posterior)
y por ahora responden success=false con un mensaje claro.
"""
import rclpy
from naoqi_utilities_msgs.srv import PointAt, SetTrackerMode

from d3_sdk_client.ros_base import D3Node

TRACKER_MODES = ("stop", "start_head", "start_move", "start_body_rotation")


class D3Perception(D3Node):
    def __init__(self):
        super().__init__("d3_perception_node")
        self.mode = "stop"
        self.create_service(SetTrackerMode, "set_tracker_mode", self.set_tracker_mode)
        self.create_service(PointAt, "point_at", lambda req, res: self.unsupported(res, "no arms to point with"))

    def set_tracker_mode(self, request, response):
        mode = request.mode.strip().lower()
        if mode not in TRACKER_MODES:
            return self.fail(response, "modo desconocido '%s'; opciones: %s" % (request.mode, ", ".join(TRACKER_MODES)))
        if mode == "stop":
            self.mode = "stop"
            self.d3.send("navigate.stop")
            return self.ok(response, "tracker stopped")
        return self.unsupported(response, "face tracking '%s' planned (detector on camera/front)" % mode)


def main(args=None):
    rclpy.init(args=args)
    node = D3Perception()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
