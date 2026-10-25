"""d3_manipulation_node: equivalente de naoqi_manipulation_node.

El D3 no tiene brazos ni articulaciones con rigidez: esos servicios existen y responden
"unsupported on D3". Las posturas y animaciones se traducen al pole, el kickstand, el tilt y la base.
"""
import time

import rclpy
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from naoqi_utilities_msgs.srv import (GoToPosture, PlayAnimation, SetBreathing, SetMoveArmsEnabled,
                                      SetOpenCloseHand, SetSecurityDistance, SetStiffnesses)
from std_srvs.srv import SetBool, Trigger

from d3_sdk_client.ros_base import D3Node

# Postura NAOqi -> (pole, kickstand). Stand: robot alto y listo para moverse; Rest/Sit: bajo y apoyado.
POSTURES = {
    "stand": (1.0, "retract"), "standinit": (1.0, "retract"), "standzero": (1.0, "retract"),
    "rest": (0.0, "deploy"), "sit": (0.0, "deploy"), "sitrelax": (0.0, "deploy"), "crouch": (0.0, "deploy"),
    "lyingback": (0.0, "deploy"), "lyingbelly": (0.0, "deploy"), "lyingfront": (0.0, "deploy"),
}

# Animaciones: secuencias (comando, datos, espera en s). Las de NAOqi se mapean por palabra clave.
ANIMATIONS = {
    "nod": [("tilt.target", {"percent": 0.75}, 0.6), ("tilt.target", {"percent": 0.35}, 0.6),
            ("tilt.target", {"percent": 0.7}, 0.6), ("tilt.target", {"percent": 0.5}, 0.6)],
    "shake": [("base.turnBy", {"degrees": 15}, 0.8), ("base.turnBy", {"degrees": -30}, 1.2),
              ("base.turnBy", {"degrees": 15}, 0.8)],
    "greet": [("base.pole.setTarget", {"percent": 1.0}, 0.5), ("tilt.target", {"percent": 0.7}, 0.8),
              ("tilt.target", {"percent": 0.5}, 0.8)],
    "look_up": [("tilt.target", {"percent": 0.1}, 1.0)],
    "look_down": [("tilt.target", {"percent": 0.9}, 1.0)],
    "spin": [("base.turnBy", {"degrees": 360}, 4.0)],
}
ANIMATION_KEYWORDS = [("hey", "greet"), ("hello", "greet"), ("greet", "greet"), ("bow", "nod"), ("yes", "nod"),
                      ("explain", "nod"), ("enthusiastic", "greet"), ("no", "shake"), ("shake", "shake")]


class D3Manipulation(D3Node):
    def __init__(self):
        super().__init__("d3_manipulation_node", events=["DRBase.status"])
        group = ReentrantCallbackGroup()
        self.create_service(GoToPosture, "go_to_posture", self.go_to_posture, callback_group=group)
        self.create_service(PlayAnimation, "play_animation", self.play_animation, callback_group=group)
        self.create_service(SetSecurityDistance, "set_tangential_security_distance", self.set_tangential)
        self.create_service(SetSecurityDistance, "set_orthogonal_security_distance", self.set_orthogonal)
        self.create_service(Trigger, "enable_default_security", self.enable_default_security)
        for srv_type, name, what in (
                (SetStiffnesses, "set_stiffnesses", "no joint stiffness control"),
                (SetBool, "toggle_smart_stiffness", "no joint stiffness control"),
                (SetOpenCloseHand, "set_open_close_hand", "no hands"),
                (SetBreathing, "toggle_breathing", "no idle breathing motion"),
                (SetMoveArmsEnabled, "set_move_arms_enabled", "no arms"),
                (SetBool, "toggle_arms_collision_protection", "no arms")):
            self.create_service(srv_type, name, lambda req, res, w=what: self.unsupported(res, w))

    def go_to_posture(self, request, response):
        key = request.posture_name.replace(" ", "").replace("_", "").replace("-", "").lower()
        if key not in POSTURES:
            return self.fail(response, "postura desconocida '%s'; opciones: Stand, Sit, Rest" % request.posture_name)
        pole, kickstand = POSTURES[key]
        if kickstand == "deploy":
            self.d3.send("navigate.stop")
        ok = self.d3.send("base.pole.setTarget", {"percent": pole}) and self.d3.send("base.kickstand." + kickstand)
        if not ok:
            return self.fail(response, "sin conexión con el D3")
        return self.ok(response, "posture %s -> pole %.0f%%, kickstand %s" % (request.posture_name, pole * 100, kickstand))

    def play_animation(self, request, response):
        name = request.animation_name.split("/")[-1].lower()
        sequence_name = name if name in ANIMATIONS else next(
            (anim for word, anim in ANIMATION_KEYWORDS if word in name), None)
        if sequence_name is None:
            return self.fail(response, "animación '%s' no disponible; opciones D3: %s"
                             % (request.animation_name, ", ".join(sorted(ANIMATIONS))))
        for command, data, wait in ANIMATIONS[sequence_name]:
            if not self.d3.send(command, data):
                return self.fail(response, "sin conexión con el D3")
            time.sleep(wait)
        return self.ok(response, "animation %s -> D3 '%s'" % (request.animation_name, sequence_name))

    def _set_avoidance(self, response, distance, off_below):
        # NAOqi: distancia de seguridad (m). D3: nivel 0 apagado, 1 frena y para, 2 esquiva.
        level = 0 if distance < off_below else (1 if distance < 0.3 else 2)
        return self.send_or_fail(response, "navigate.obstacleAvoidance.setLevel", {"level": level},
                                 "obstacle avoidance level %d (distance %.2f m)" % (level, distance))

    def set_tangential(self, request, response):
        return self._set_avoidance(response, request.distance, 0.1)

    def set_orthogonal(self, request, response):
        return self._set_avoidance(response, request.distance, 0.1)

    def enable_default_security(self, _request, response):
        return self.send_or_fail(response, "navigate.obstacleAvoidance.setLevel", {"level": 2},
                                 "default security: obstacle avoidance level 2")


def main(args=None):
    rclpy.init(args=args)
    node = D3Manipulation()
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
