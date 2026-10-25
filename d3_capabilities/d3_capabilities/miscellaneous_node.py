"""d3_miscellaneous_node: equivalente de naoqi_miscellaneous_node."""
import rclpy
from naoqi_utilities_msgs.msg import LedParameters
from std_msgs.msg import Float32
from std_srvs.srv import SetBool

from d3_driver.conversions import battery_percent
from d3_sdk_client.ros_base import D3Node


class D3Miscellaneous(D3Node):
    def __init__(self):
        super().__init__("d3_miscellaneous_node", events=["DRBase.status"])
        self.declare_parameter("battery_period", 5.0)
        self.declare_parameter("battery_scale", 1.0)
        self.battery_scale = float(self.get_parameter("battery_scale").value)
        # NAOqi: Autonomous Life, Basic Awareness y blinking no existen en el D3 -> no-op con éxito,
        # para que la secuencia de arranque del bringup (copiada del original) termine igual.
        self.create_service(SetBool, "set_autonomous_state", self.noop("autonomous life"))
        self.create_service(SetBool, "toggle_awareness", self.noop("basic awareness"))
        self.create_service(SetBool, "toggle_blinking", self.noop("autonomous blinking"))
        self.battery_pub = self.create_publisher(Float32, "battery_percentage", 10)
        self.create_subscription(LedParameters, "set_leds", self.on_leds, 10)
        self.create_timer(float(self.get_parameter("battery_period").value), self.publish_battery)
        self._warned_leds = False

    def noop(self, what):
        def callback(request, response):
            response.success = True
            response.message = "no-op on D3 (%s does not exist): data=%s" % (what, request.data)
            return response
        return callback

    def on_d3_connect(self):
        self.d3.send("base.requestStatus")

    def publish_battery(self):
        status = self.d3.latest("DRBase.status")
        if status is None:
            self.d3.send("base.requestStatus")
            return
        value = battery_percent(status, self.battery_scale)
        if value is not None:
            self.battery_pub.publish(Float32(data=float(value)))

    def on_leds(self, msg):
        if not self._warned_leds:
            self._warned_leds = True
            self.get_logger().warn("set_leds: el D3 no tiene LEDs controlables; se ignora (%s)" % msg.name)


def main(args=None):
    rclpy.init(args=args)
    node = D3Miscellaneous()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
