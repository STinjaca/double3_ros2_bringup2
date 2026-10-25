"""Bringup del Double 3 con el mismo contrato ROS 2 que naoqi_bringup2_SinfonIA.

Argumentos compatibles con el original: nao_ip, nao_port, namespace, driver_params_file,
driver_{cmd_vel,joint_trajectory,goal_pose,speech}_topic, launch_video_server.
Nuevos: robot_ip / robot_port (alias más claros), use_sim, launch_rosbridge, launch_foxglove.

  ros2 launch d3_bringup2 d3_bringup.launch.py use_sim:=true
  ros2 launch d3_bringup2 d3_bringup.launch.py robot_ip:=$D3_IP     # token en la variable D3_TOKEN
"""
import os

import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (DeclareLaunchArgument, ExecuteProcess, IncludeLaunchDescription, LogInfo,
                            OpaqueFunction, RegisterEventHandler, SetEnvironmentVariable, TimerAction)
from launch.event_handlers import OnExecutionComplete, OnProcessStart
from launch.launch_description_sources import AnyLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

SIM_TOKEN = "sim-local-token"  # public-safe: solo simulación, el agente escucha en 127.0.0.1
CAPABILITY_NODES = ["miscellaneous", "manipulation", "navigation", "perception", "speech", "interface"]


def load_config(path):
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def truthy(value):
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def service_call(namespace, service, srv_type, request):
    name = "/%s/%s" % (namespace, service) if namespace else "/" + service
    return ExecuteProcess(cmd=["ros2", "service", "call", name, srv_type, request], output="screen")


def launch_setup(context):
    cfg_path = LaunchConfiguration("driver_params_file").perform(context)
    config = load_config(cfg_path)
    bringup = config.get("bringup", {})
    namespace = LaunchConfiguration("namespace").perform(context).strip("/")
    use_sim = truthy(LaunchConfiguration("use_sim").perform(context))

    def node_params(node_name):
        return dict(config.get(node_name, {}).get("ros__parameters", {}) or {})

    driver_params = node_params("d3_driver_node")
    robot_ip = (LaunchConfiguration("robot_ip").perform(context) or LaunchConfiguration("nao_ip").perform(context)
                or os.environ.get("D3_IP") or str(driver_params.get("robot_ip", "127.0.0.1")))
    robot_port = (LaunchConfiguration("robot_port").perform(context) or LaunchConfiguration("nao_port").perform(context)
                  or os.environ.get("D3_PORT") or str(driver_params.get("robot_port", 22022)))
    actions = []

    if use_sim:
        robot_ip, robot_port = "127.0.0.1", "22022"
        sim_socket = "/tmp/doubleapi_sim"
        agent = os.path.join(get_package_share_directory("d3_agent"), "..", "..", "lib", "d3_agent", "d3_agent.py")
        actions += [
            SetEnvironmentVariable("D3_TOKEN", SIM_TOKEN),
            LogInfo(msg="*** MODO SIMULACIÓN: d3_sim + d3_agent (perfil sim) en este contenedor ***"),
            Node(package="d3_sim", executable="d3_sim", name="d3_sim", output="screen",
                 arguments=["--socket", sim_socket]),
            TimerAction(period=1.0, actions=[ExecuteProcess(
                cmd=["python3", os.path.normpath(agent), "--profile", "sim", "--api", sim_socket,
                     "--listen", "127.0.0.1", "--port", robot_port, "--token", SIM_TOKEN,
                     "--pages-dir", os.path.join(get_package_share_directory("d3_agent"), "pages")],
                name="d3_agent", output="screen")]),
        ]
    elif not os.environ.get("D3_TOKEN"):
        actions.append(LogInfo(msg="AVISO: D3_TOKEN no está definido; d3_agent rechazará la conexión."))

    robot_args = ["--ip", robot_ip, "--port", robot_port]
    topics = bringup.get("driver", {}).get("command_topics", {})
    remaps = [(default, LaunchConfiguration("driver_%s_topic" % key).perform(context) or topics.get(key + "_topic", default))
              for key, default in (("cmd_vel", "cmd_vel"), ("joint_trajectory", "joint_trajectory"),
                                   ("goal_pose", "goal_pose"), ("speech", "speech"))]
    remaps = [(src, dst) for src, dst in remaps if src != dst]

    driver = Node(package="d3_driver", executable="d3_driver_node", name="d3_driver_node", namespace=namespace,
                  output="screen", arguments=robot_args, parameters=[driver_params], remappings=remaps)
    urdf_path = os.path.join(get_package_share_directory("d3_description"), "urdf", "d3.urdf")
    with open(urdf_path, encoding="utf-8") as fh:
        urdf = fh.read()
    state_publisher = Node(package="robot_state_publisher", executable="robot_state_publisher",
                           name="robot_state_publisher", namespace=namespace, output="log",
                           parameters=[{"robot_description": urdf}])
    capabilities = {}
    for short in CAPABILITY_NODES:
        name = "d3_%s_node" % short
        params = node_params(name)
        if short == "interface" and os.environ.get("HOST_IP"):
            params.setdefault("video_server_ip", os.environ["HOST_IP"])
        capabilities[short] = Node(package="d3_capabilities", executable=name, name=name, namespace=namespace,
                                   output="screen", arguments=robot_args, parameters=[params])
    actions += [driver, state_publisher] + list(capabilities.values())

    if truthy(LaunchConfiguration("launch_video_server").perform(context)):
        actions.append(Node(package="web_video_server", executable="web_video_server", name="web_video_server",
                            namespace=namespace, output="log"))
    if truthy(LaunchConfiguration("launch_rosbridge").perform(context)):
        actions.append(IncludeLaunchDescription(AnyLaunchDescriptionSource(os.path.join(
            get_package_share_directory("rosbridge_server"), "launch", "rosbridge_websocket_launch.xml"))))
    if truthy(LaunchConfiguration("launch_foxglove").perform(context)):
        actions.append(Node(package="foxglove_bridge", executable="foxglove_bridge", name="foxglove_bridge",
                            output="log", parameters=[{"port": 8765, "address": "0.0.0.0"}]))

    # --- Secuencia de arranque: misma cadena que naoqi_pepper_bringup.launch.py -----------------
    startup = bringup.get("startup", {})
    if startup.get("enabled", True):
        steps = [
            ("Autonomous blinking enabled.", service_call(namespace, "toggle_blinking", "std_srvs/srv/SetBool", "{data: true}")),
            ("Autonomous life disabled.", service_call(namespace, "set_autonomous_state", "std_srvs/srv/SetBool", "{data: false}")),
            ("Robot in '%s' posture." % startup.get("posture", "Stand"), service_call(
                namespace, "go_to_posture", "naoqi_utilities_msgs/srv/GoToPosture",
                "{posture_name: '%s'}" % startup.get("posture", "Stand"))),
            ("Basic awareness disabled.", service_call(namespace, "toggle_awareness", "std_srvs/srv/SetBool", "{data: false}")),
            ("Tracker stopped.", service_call(namespace, "set_tracker_mode", "naoqi_utilities_msgs/srv/SetTrackerMode", "{mode: 'stop'}")),
        ]
        if startup.get("hide_double_gui", False):
            steps.append(("Double GUI hidden.", service_call(namespace, "toggle_app_launcher", "std_srvs/srv/SetBool", "{data: false}")))
        if startup.get("splash_url"):
            steps.append(("Splash shown on screen.", service_call(
                namespace, "show_image", "naoqi_utilities_msgs/srv/SendURL", "{url: '%s'}" % startup["splash_url"])))
        actions.append(RegisterEventHandler(OnProcessStart(
            target_action=capabilities["miscellaneous"],
            on_start=[LogInfo(msg="Miscellaneous node started. Beginning setup sequence..."),
                      TimerAction(period=float(startup.get("delay_sec", 5.0)), actions=[steps[0][1]])])))
        for (message, action), (_, next_action) in zip(steps, steps[1:] + [(None, None)]):
            follow = [LogInfo(msg=message)]
            if next_action is not None:
                follow.append(next_action)
            else:
                follow += [LogInfo(msg="-" * 58), LogInfo(msg="--- Double 3 is ready and configured. ---"),
                           LogInfo(msg="-" * 58)]
            actions.append(RegisterEventHandler(OnExecutionComplete(target_action=action, on_completion=follow)))
    return actions


def generate_launch_description():
    default_params = os.path.join(get_package_share_directory("d3_bringup2"), "config", "d3.yaml")
    default_ns = load_config(default_params).get("bringup", {}).get("namespace", "d3")
    args = [
        DeclareLaunchArgument("robot_ip", default_value="", description="IP del D3 (o D3_IP en el entorno)"),
        DeclareLaunchArgument("robot_port", default_value="", description="Puerto de d3_agent (22022)"),
        DeclareLaunchArgument("nao_ip", default_value="", description="Alias de robot_ip (compatibilidad)"),
        DeclareLaunchArgument("nao_port", default_value="", description="Alias de robot_port (compatibilidad)"),
        DeclareLaunchArgument("namespace", default_value=default_ns, description="Namespace ROS del robot"),
        DeclareLaunchArgument("driver_params_file", default_value=default_params),
        DeclareLaunchArgument("driver_cmd_vel_topic", default_value=""),
        DeclareLaunchArgument("driver_joint_trajectory_topic", default_value=""),
        DeclareLaunchArgument("driver_goal_pose_topic", default_value=""),
        DeclareLaunchArgument("driver_speech_topic", default_value=""),
        DeclareLaunchArgument("launch_video_server", default_value="true"),
        DeclareLaunchArgument("launch_rosbridge", default_value="true"),
        DeclareLaunchArgument("launch_foxglove", default_value="false"),
        DeclareLaunchArgument("use_sim", default_value="false", description="Simulador en vez del robot"),
    ]
    return LaunchDescription(args + [OpaqueFunction(function=launch_setup)])
