"""d3_driver_node: equivalente de naoqi_driver para el Double 3.

Mismos nombres y tipos de topics/servicios/acción que naoqi_driver (relativos al namespace):
  sub: cmd_vel, joint_trajectory, goal_pose, speech
  pub: joint_states, odom, /tf, info, camera/front/image_raw (+camera_info, +compressed), imu/torso,
       sonar/{left,front_left,front,front_right,right}, mic, mic_stamped, mic_info
  srv: get_robot_config, set_language, get_language       action: listen
Ver contract/contract.yaml para el detalle de cada mapeo.
"""
import json
import math
import queue
import threading
import time

import rclpy
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy

from audio_common_msgs.msg import AudioData, AudioDataStamped, AudioInfo
from geometry_msgs.msg import PoseStamped, TransformStamped, Twist
from naoqi_bridge_msgs.action import Listen
from naoqi_bridge_msgs.msg import RobotInfo
from naoqi_bridge_msgs.srv import GetRobotInfo, GetString, SetString
from nav_msgs.msg import Odometry
from sensor_msgs.msg import CameraInfo, CompressedImage, Image, Imu, JointState, Range
from std_msgs.msg import String
from tf2_ros import TransformBroadcaster
from trajectory_msgs.msg import JointTrajectory

from d3_sdk_client import AudioStream, VideoStream
from d3_sdk_client.ros_base import D3Node
from d3_driver import conversions as conv

EVENTS = ["DRPose.pose", "DRBase.status", "DRMotor.position", "DRIMU.imu", "DRUltrasonic.measurement",
          "DRSystem.systemInfo", "DRAgent.info", "DRNavigateModule.arrive"]


class D3Driver(D3Node):
    def __init__(self):
        super().__init__("d3_driver_node", events=EVENTS)
        p = self.declare_parameter
        # Movimiento
        p("max_linear_speed", 0.5)       # m/s que equivalen a throttle=1 (calibrar en el lab)
        p("max_angular_speed", 1.6)      # rad/s que equivalen a turn=1
        p("invert_turn", False)
        p("drive_period", 0.2)           # reenvío de navigate.drive (watchdog del D3: 500 ms)
        p("cmd_vel_timeout", 0.0)        # 0 = velocidad retenida como ALMotion.move (contrato NAOqi)
        p("auto_retract_kickstand", True)
        # Frames
        p("odom_frame", "odom")
        p("base_frame", "base_footprint")
        p("camera_frame", "camera_front_optical_frame")
        p("imu_frame", "head_link")
        p("publish_tf", True)
        # Cinemática del pole y el tilt
        p("pole_travel_m", 0.33)         # 47" a 60" según la ficha técnica
        p("tilt_up_rad", -0.35)
        p("tilt_down_rad", 0.35)
        p("battery_scale", 1.0)
        p("joint_states_rate", 5.0)
        # Sensores
        p("sonar_names", ["left", "front_left", "front", "front_right", "right"])
        p("sonar_frames", ["sonar_left_frame", "sonar_front_left_frame", "sonar_front_frame",
                           "sonar_front_right_frame", "sonar_right_frame"])
        p("sonar_min_range", 0.03)
        p("sonar_max_range", 4.0)
        p("sonar_fov", 0.5)
        # Cámara (stream JPEG del agente)
        p("camera_enabled", True)
        p("camera_width", 640)
        p("camera_height", 400)
        p("camera_fps", 10)
        p("camera_quality", 70)
        p("camera_fx", 0.0)              # 0 = estimado a partir del FOV
        p("camera_hfov_deg", 100.0)      # ASSUMED: cámara gran angular; calibrar con camera_calibration
        # Audio (micrófono)
        p("audio_enabled", True)
        p("audio_sample_rate", 16000)
        p("audio_channels", 1)
        # Idioma (TTS / ASR del host)
        p("language", "English")
        p("tts_backend", "auto")

        gp = lambda name: self.get_parameter(name).value  # noqa: E731
        self.params = {name: gp(name) for name in (
            "max_linear_speed", "max_angular_speed", "invert_turn", "drive_period", "cmd_vel_timeout",
            "auto_retract_kickstand", "odom_frame", "base_frame", "camera_frame", "imu_frame", "publish_tf",
            "pole_travel_m", "tilt_up_rad", "tilt_down_rad", "battery_scale", "sonar_min_range",
            "sonar_max_range", "sonar_fov", "audio_sample_rate", "audio_channels")}
        self.language = gp("language")
        self.cb_group = ReentrantCallbackGroup()

        # Estado
        self.pole_percent = 0.0
        self.tilt_percent = 0.5
        self.kickstand = None
        self.last_cmd_vel = 0.0
        self.driving = False
        self.system_info = {}
        self.agent_info = {}
        self.audio_queue = queue.Queue(maxsize=200)
        self.listening = threading.Lock()

        # Publicadores (mismos nombres que naoqi_driver)
        latched = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL,
                             reliability=ReliabilityPolicy.RELIABLE)
        self.pub_joint_states = self.create_publisher(JointState, "joint_states", 10)
        self.pub_odom = self.create_publisher(Odometry, "odom", 10)
        self.pub_info = self.create_publisher(String, "info", latched)
        self.pub_imu = self.create_publisher(Imu, "imu/torso", 10)
        self.tf_broadcaster = TransformBroadcaster(self) if self.params["publish_tf"] else None
        sonar_names, sonar_frames = gp("sonar_names"), gp("sonar_frames")
        self.sonar_pubs = [(self.create_publisher(Range, "sonar/%s" % name, 10),
                            sonar_frames[i] if i < len(sonar_frames) else "sonar_%s_frame" % name)
                           for i, name in enumerate(sonar_names)]

        # Suscriptores de comandos
        self.create_subscription(Twist, "cmd_vel", self.on_cmd_vel, 10)
        self.create_subscription(JointTrajectory, "joint_trajectory", self.on_joint_trajectory, 10)
        self.create_subscription(PoseStamped, "goal_pose", self.on_goal_pose, 10)
        self.create_subscription(String, "speech", self.on_speech, 10)

        # Servicios y acción
        self.create_service(GetRobotInfo, "get_robot_config", self.srv_get_robot_config)
        self.create_service(SetString, "set_language", self.srv_set_language)
        self.create_service(GetString, "get_language", self.srv_get_language)
        self.listen_server = ActionServer(self, Listen, "listen", execute_callback=self.execute_listen,
                                          goal_callback=lambda _goal: GoalResponse.ACCEPT,
                                          cancel_callback=lambda _goal: CancelResponse.ACCEPT,
                                          callback_group=self.cb_group)

        # Eventos del D3
        self.d3.on("DRPose.pose", self.on_pose)
        self.d3.on("DRBase.status", self.on_base_status)
        self.d3.on("DRMotor.position", self.on_tilt)
        self.d3.on("DRIMU.imu", self.on_imu)
        self.d3.on("DRUltrasonic.measurement", self.on_ultrasonic)
        self.d3.on("DRSystem.systemInfo", self.on_system_info)
        self.d3.on("DRAgent.info", self.on_agent_info)

        self.create_timer(1.0 / max(gp("joint_states_rate"), 0.5), self.publish_joint_states)
        self.create_timer(0.1, self.check_cmd_vel_timeout)

        # Media
        from d3_media.speaker import Speaker
        self.speaker = Speaker(self.robot_ip, self.robot_port, self.robot_token, self.get_logger(),
                               gp("tts_backend"))
        self.speaker.language = self.language
        self.asr = None
        self.streams = []
        if gp("camera_enabled"):
            self.setup_camera(gp("camera_width"), gp("camera_height"), gp("camera_fps"),
                              gp("camera_quality"), gp("camera_fx"), gp("camera_hfov_deg"))
        if gp("audio_enabled"):
            self.setup_audio()

    # ------------------------------------------------------------------ conexión
    def on_d3_connect(self):
        for command, data in (("navigate.enable", None), ("imu.enable", None), ("ultrasonic.enable", None),
                              ("ultrasonic.start", None), ("pose.resume", None), ("speaker.enable", None),
                              ("base.requestStatus", None), ("system.requestInfo", None), ("agent.info", None)):
            self.d3.send(command, data)

    # ------------------------------------------------------------------ comandos
    def on_cmd_vel(self, msg):
        throttle, turn = conv.twist_to_drive(msg.linear.x, msg.angular.z, self.params["max_linear_speed"],
                                             self.params["max_angular_speed"])
        if self.params["invert_turn"]:
            turn = -turn
        self.last_cmd_vel = time.monotonic()
        if throttle == 0.0 and turn == 0.0:
            self.stop_driving()
            return
        if self.params["auto_retract_kickstand"] and self.kickstand == 1:
            self.d3.send("base.kickstand.retract")
        self.driving = True
        self.d3.repeat("drive", "navigate.drive", {"throttle": throttle, "turn": turn},
                       period=self.params["drive_period"])

    def stop_driving(self):
        if self.d3.stop_repeat("drive") or self.driving:
            self.d3.send("navigate.drive", {"throttle": 0.0, "turn": 0.0})
        self.driving = False

    def check_cmd_vel_timeout(self):
        timeout = self.params["cmd_vel_timeout"]
        if timeout > 0 and self.driving and time.monotonic() - self.last_cmd_vel > timeout:
            self.get_logger().info("cmd_vel sin actualizar en %.1fs: deteniendo" % timeout)
            self.stop_driving()

    def on_joint_trajectory(self, msg):
        if not msg.points:
            return
        point = msg.points[0]
        for index, name in enumerate(msg.joint_names):
            if index >= len(point.positions):
                break
            value = point.positions[index]
            if name == "pole_joint":
                self.d3.send("base.pole.setTarget",
                             {"percent": conv.pole_m_to_percent(value, self.params["pole_travel_m"])})
            elif name in ("head_tilt_joint", "HeadPitch"):
                self.d3.send("tilt.target", {"percent": conv.tilt_rad_to_percent(
                    value, self.params["tilt_up_rad"], self.params["tilt_down_rad"])})
            else:
                self.get_logger().debug("joint %s no existe en el D3; se ignora" % name)

    def on_goal_pose(self, msg):
        q = msg.pose.orientation
        yaw = conv.yaw_from_quaternion(q.x, q.y, q.z, q.w)
        frame = msg.header.frame_id or self.params["base_frame"]
        relative = frame != self.params["odom_frame"]
        if self.params["auto_retract_kickstand"] and self.kickstand == 1:
            self.d3.send("base.kickstand.retract")
        self.d3.send("navigate.target", {"x": msg.pose.position.x, "y": msg.pose.position.y,
                                         "angleRadians": yaw, "relative": relative})

    def on_speech(self, msg):
        self.speaker.say(msg.data, self.language, blocking=False)

    # ------------------------------------------------------------------ servicios
    def srv_get_robot_config(self, _request, response):
        info = RobotInfo()
        info.type = 255  # RobotInfo no tiene enum para el D3 (NAO=0, ROMEO=1, PEPPER=2)
        info.model = "Double3"
        info.head_version = str(self.system_info.get("version", self.agent_info.get("version", "")))
        info.has_laser = False
        info.has_extended_arms = False
        info.number_of_legs = info.number_of_arms = info.number_of_hands = 0
        response.info = info
        return response

    def srv_set_language(self, request, response):
        self.language = request.data
        self.speaker.language = request.data
        if self.asr is not None:
            self.asr.configure(language=request.data)
        response.success = True
        return response

    def srv_get_language(self, _request, response):
        response.data = self.language
        return response

    # ------------------------------------------------------------------ eventos -> topics
    def on_pose(self, data):
        base = data.get("base", data)
        x = conv.first_number(base, ("x",), 0.0)
        y = conv.first_number(base, ("y",), 0.0)
        yaw = conv.first_number(base, ("yaw", "theta", "heading"), 0.0)
        speed = conv.first_number(base, ("speed", "velocity"), 0.0)
        now = self.get_clock().now().to_msg()
        qx, qy, qz, qw = conv.quaternion_from_yaw(yaw)
        odom = Odometry()
        odom.header.stamp = now
        odom.header.frame_id = self.params["odom_frame"]
        odom.child_frame_id = self.params["base_frame"]
        odom.pose.pose.position.x, odom.pose.pose.position.y = x, y
        odom.pose.pose.orientation.z, odom.pose.pose.orientation.w = qz, qw
        odom.twist.twist.linear.x = speed
        self.pub_odom.publish(odom)
        if self.tf_broadcaster is not None:
            tf = TransformStamped()
            tf.header = odom.header
            tf.child_frame_id = odom.child_frame_id
            tf.transform.translation.x, tf.transform.translation.y = x, y
            tf.transform.rotation.z, tf.transform.rotation.w = qz, qw
            self.tf_broadcaster.sendTransform(tf)

    def on_base_status(self, data):
        pole = conv.first_number(data, ("pole", "polePercent", "poleHeight"))
        if pole is not None:
            self.pole_percent = pole / 100.0 if pole > 1.0 else pole
        kickstand = conv.first_number(data, ("kickstand",))
        if kickstand is not None:
            self.kickstand = int(kickstand)

    def on_tilt(self, data):
        percent = conv.first_number(data, ("percent", "position"))
        if percent is not None:
            self.tilt_percent = percent

    def publish_joint_states(self):
        msg = JointState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.name = ["pole_joint", "head_tilt_joint"]
        msg.position = [conv.pole_percent_to_m(self.pole_percent, self.params["pole_travel_m"]),
                        conv.tilt_percent_to_rad(self.tilt_percent, self.params["tilt_up_rad"],
                                                 self.params["tilt_down_rad"])]
        self.pub_joint_states.publish(msg)

    def on_imu(self, data):
        quat = data.get("quat") or data.get("quaternion") or {}
        if not quat:
            return
        msg = Imu()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = self.params["imu_frame"]
        msg.orientation.x = float(quat.get("x", 0.0))
        msg.orientation.y = float(quat.get("y", 0.0))
        msg.orientation.z = float(quat.get("z", 0.0))
        msg.orientation.w = float(quat.get("w", 1.0))
        msg.angular_velocity_covariance[0] = -1.0     # no disponible
        msg.linear_acceleration_covariance[0] = -1.0  # no disponible
        self.pub_imu.publish(msg)

    def on_ultrasonic(self, data):
        index = conv.first_number(data, ("sensor", "index", "id"))
        distance = conv.ultrasonic_distance_m(data)
        if index is None or distance is None or not 0 <= int(index) < len(self.sonar_pubs):
            return
        pub, frame = self.sonar_pubs[int(index)]
        msg = Range()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = frame
        msg.radiation_type = Range.ULTRASOUND
        msg.field_of_view = self.params["sonar_fov"]
        msg.min_range = self.params["sonar_min_range"]
        msg.max_range = self.params["sonar_max_range"]
        msg.range = float(distance)
        pub.publish(msg)

    def on_system_info(self, data):
        self.system_info = data
        self.publish_info()

    def on_agent_info(self, data):
        self.agent_info = data
        self.publish_info()

    def publish_info(self):
        info = {"robot": "Double3", "system": self.system_info, "agent": self.agent_info}
        self.pub_info.publish(String(data=json.dumps(info, ensure_ascii=False)))

    # ------------------------------------------------------------------ cámara
    def setup_camera(self, width, height, fps, quality, fx, hfov_deg):
        import cv2
        import numpy as np
        self.pub_image = self.create_publisher(Image, "camera/front/image_raw", 5)
        self.pub_compressed = self.create_publisher(CompressedImage, "camera/front/image_raw/compressed", 5)
        self.pub_camera_info = self.create_publisher(CameraInfo, "camera/front/camera_info", 5)
        info = CameraInfo()
        info.width, info.height = width, height
        focal = fx or (width / 2.0) / math.tan(math.radians(hfov_deg) / 2.0)
        info.distortion_model = "plumb_bob"
        info.d = [0.0] * 5
        info.k = [focal, 0.0, width / 2.0, 0.0, focal, height / 2.0, 0.0, 0.0, 1.0]
        info.r = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
        info.p = [focal, 0.0, width / 2.0, 0.0, 0.0, focal, height / 2.0, 0.0, 0.0, 0.0, 1.0, 0.0]
        self.camera_info = info
        frame_id = self.params["camera_frame"]

        def on_frame(jpeg):
            stamp = self.get_clock().now().to_msg()
            compressed = CompressedImage(format="jpeg", data=jpeg)
            compressed.header.stamp, compressed.header.frame_id = stamp, frame_id
            self.pub_compressed.publish(compressed)
            if self.pub_image.get_subscription_count() > 0:
                img = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
                if img is not None:
                    msg = Image()
                    msg.header = compressed.header
                    msg.height, msg.width = img.shape[:2]
                    msg.encoding, msg.step = "bgr8", img.shape[1] * 3
                    msg.data = img.tobytes()
                    self.pub_image.publish(msg)
            self.camera_info.header = compressed.header
            self.pub_camera_info.publish(self.camera_info)

        self.streams.append(VideoStream(self.robot_ip, self.robot_port, self.robot_token, on_frame,
                                        width=width, height=height, fps=fps, quality=quality).start())

    # ------------------------------------------------------------------ audio
    def setup_audio(self):
        rate, channels = self.params["audio_sample_rate"], self.params["audio_channels"]
        latched = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL,
                             reliability=ReliabilityPolicy.RELIABLE)
        self.pub_mic = self.create_publisher(AudioData, "mic", 10)
        self.pub_mic_stamped = self.create_publisher(AudioDataStamped, "mic_stamped", 10)
        self.pub_mic_info = self.create_publisher(AudioInfo, "mic_info", latched)
        mic_info = AudioInfo(channels=channels, sample_rate=rate, sample_format="S16LE",
                             bitrate=rate * channels * 16, coding_format="wave")
        self.pub_mic_info.publish(mic_info)
        # Se republica a 1 Hz: los suscriptores con QoS volatile (como el demo) también lo reciben.
        self.create_timer(1.0, lambda: self.pub_mic_info.publish(mic_info))
        chunk_bytes = rate * channels * 2 // 10  # 100 ms
        pending = bytearray()

        def on_pcm(chunk):
            pending.extend(chunk)
            while len(pending) >= chunk_bytes:
                block = bytes(pending[:chunk_bytes])
                del pending[:chunk_bytes]
                audio = AudioData(data=block)
                self.pub_mic.publish(audio)
                stamped = AudioDataStamped(audio=audio)
                stamped.header.stamp = self.get_clock().now().to_msg()
                self.pub_mic_stamped.publish(stamped)
                if self.listening.locked():
                    try:
                        self.audio_queue.put_nowait(block)
                    except queue.Full:
                        pass

        self.streams.append(AudioStream(self.robot_ip, self.robot_port, self.robot_token, on_pcm,
                                        rate=rate, channels=channels).start())

    def execute_listen(self, goal_handle):
        """Acción listen: una escucha con ASR (Vosk) sobre el micrófono del D3."""
        from d3_media.asr import SpeechRecognizer
        result = Listen.Result()
        if self.asr is None:
            self.asr = SpeechRecognizer(sample_rate=self.params["audio_sample_rate"])
            self.asr.configure(language=self.language)
        if not self.asr.available:
            self.get_logger().warn("listen: ASR no disponible (instala vosk y un modelo en D3_VOSK_MODELS_DIR)")
            goal_handle.succeed()
            return result
        with self.listening:
            while not self.audio_queue.empty():
                self.audio_queue.get_nowait()

            def source(timeout):
                if goal_handle.is_cancel_requested:
                    return None
                try:
                    return self.audio_queue.get(timeout=timeout)
                except queue.Empty:
                    return None

            def partial(texts):
                goal_handle.publish_feedback(Listen.Feedback(partial_result=texts))

            result.result = self.asr.listen_once(source, goal_handle.request.expected,
                                                 goal_handle.request.language or self.language,
                                                 partial=partial)
        if goal_handle.is_cancel_requested:
            goal_handle.canceled()
        else:
            goal_handle.succeed()
        return result

    def destroy_node(self):
        for stream in self.streams:
            stream.stop()
        self.stop_driving()
        return super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = D3Driver()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
