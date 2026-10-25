# Matriz de compatibilidad NAOqi → Double 3

> Generado por `contract/gen_compat.py` desde `contract/contract.yaml`. No editar a mano.

Namespace por defecto: `/d3` (en el original: `/nao` o `/pepper`).

| Estado | Interfaces |
|---|---|
| ✅ supported | 33 |
| 🟡 partial | 19 |
| 🔵 noop | 3 |
| ⛔ unsupported | 18 |
| 🕓 planned | 3 |

- **supported**: implementado con el hardware del D3.
- **partial**: implementado con limitaciones (ver notas).
- **noop**: responde éxito sin hacer nada (no aplica al D3; lo llama la secuencia de arranque).
- **unsupported**: el servicio existe y responde `success=false, "unsupported on D3"`.
- **planned**: fase posterior.

## naoqi_driver

| Interfaz | Tipo | NAOqi | D3 | Estado | Notas |
|---|---|---|---|---|---|
| `cmd_vel` (sub) | `geometry_msgs/msg/Twist` | ALMotion.move | navigate.drive (reenvío 5 Hz, watchdog 500 ms) | 🟡 partial | linear.y se ignora (base diferencial); m/s y rad/s se convierten a -1..1 con parámetros de calibración |
| `joint_trajectory` (sub) | `trajectory_msgs/msg/JointTrajectory` | ALMotion.setAngles | base.pole.setTarget / tilt.target | 🟡 partial | joints pole_joint y head_tilt_joint; HeadPitch se acepta como alias del tilt; el resto se ignora |
| `goal_pose` (sub) | `geometry_msgs/msg/PoseStamped` | ALMotion.moveTo | navigate.target (relative si frame base_footprint) | ✅ supported |  |
| `speech` (sub) | `std_msgs/msg/String` | ALTextToSpeech.say | TTS en el host + reproducción en d3_agent | ✅ supported |  |
| `joint_states` (pub) | `sensor_msgs/msg/JointState` | ALMotion.getAngles | DRBase.status.pole + DRMotor.position | ✅ supported |  |
| `odom` (pub) | `nav_msgs/msg/Odometry` | ALMotion.getPosition | DRPose.pose | ✅ supported |  |
| `/tf` (pub) | `tf2_msgs/msg/TFMessage` | URDF + ALMotion | odom->base_footprint (DRPose) + robot_state_publisher | ✅ supported |  |
| `robot_description` (pub) | `std_msgs/msg/String` | URDF del paquete | d3_description/urdf/d3.urdf | ✅ supported |  |
| `info` (pub) | `std_msgs/msg/String` | ALMemory RobotConfig | DRSystem.systemInfo + DRAgent.info | ✅ supported |  |
| `camera/front/image_raw` (pub) | `sensor_msgs/msg/Image` | ALVideoDevice kTopCamera | camera.enable v4l2 -> /dev/video9 -> stream JPEG del agente | ✅ supported |  |
| `camera/front/camera_info` (pub) | `sensor_msgs/msg/CameraInfo` | ALVideoDevice | intrínsecos por parámetro (calibrar en el lab) | 🟡 partial |  |
| `camera/bottom/image_raw` (pub) | `sensor_msgs/msg/Image` | ALVideoDevice kBottomCamera | - | ⛔ unsupported | el D3 no tiene cámara inferior equivalente |
| `camera/depth/image_raw` (pub) | `sensor_msgs/msg/Image` | ALVideoDevice kDepthCamera | RealSense D430 frontal (depth.front) | 🕓 planned | usar la RealSense en crudo deja al D3 sin evasión de obstáculos |
| `camera/stereo/image_raw` (pub) | `sensor_msgs/msg/Image` | ALVideoDevice | - | ⛔ unsupported |  |
| `camera/ir/image_raw` (pub) | `sensor_msgs/msg/Image` | ALVideoDevice | - | ⛔ unsupported |  |
| `imu/torso` (pub) | `sensor_msgs/msg/Imu` | ALMemory InertialSensor | DRIMU.imu (IMU de la cabeza) | 🟡 partial | solo orientación; sin velocidad angular ni aceleración |
| `imu/base` (pub) | `sensor_msgs/msg/Imu` | ALMemory InertialSensorBase | - | ⛔ unsupported |  |
| `laser` (pub) | `sensor_msgs/msg/LaserScan` | ALMemory laser | DRGridManager.robotGrid o depth.floor | 🕓 planned |  |
| `sonar/left` (pub) | `sensor_msgs/msg/Range` | ALSonar (NAO) | DRUltrasonic.measurement sensor 0 | ✅ supported |  |
| `sonar/front` (pub) | `sensor_msgs/msg/Range` | ALSonar (Pepper) | DRUltrasonic.measurement sensor 2 | ✅ supported |  |
| `sonar/right` (pub) | `sensor_msgs/msg/Range` | ALSonar (NAO) | DRUltrasonic.measurement sensor 4 | ✅ supported |  |
| `sonar/back` (pub) | `sensor_msgs/msg/Range` | ALSonar (Pepper) | - | ⛔ unsupported |  |
| `mic` (pub) | `audio_common_msgs/msg/AudioData` | ALAudioDevice | arecord en d3_agent -> PCM16 16 kHz mono | ✅ supported |  |
| `mic_stamped` (pub) | `audio_common_msgs/msg/AudioDataStamped` | ALAudioDevice | igual que mic, con header | ✅ supported |  |
| `mic_info` (pub) | `audio_common_msgs/msg/AudioInfo` | config | transient_local, 16 kHz / 1 canal / S16LE | ✅ supported |  |
| `bumper` (pub) | `sensor_msgs/msg/Joy` | ALMemory BumperPressed | - | ⛔ unsupported |  |
| `hand_touch` (pub) | `sensor_msgs/msg/Joy` | ALMemory HandTouched | - | ⛔ unsupported |  |
| `head_touch` (pub) | `sensor_msgs/msg/Joy` | ALMemory TactilTouched | - | ⛔ unsupported |  |
| `/diagnostics` (pub) | `diagnostic_msgs/msg/DiagnosticArray` | ALMemory (temperaturas, batería) | DRSystem.tegrastats + DRBase.status | 🕓 planned | desactivado por defecto también en el bringup original |
| `/rosout` (pub) | `rcl_interfaces/msg/Log` | log de NAOqi | - | ⛔ unsupported | desactivado por defecto en el original; los nodos D3 usan /rosout estándar |
| `get_robot_config` (srv) | `naoqi_bridge_msgs/srv/GetRobotInfo` | ALMotion.getRobotConfig | valores fijos del D3 (0 brazos/piernas/manos) | 🟡 partial | RobotInfo.type no tiene enum para D3; se reporta model=Double3 |
| `set_language` (srv) | `naoqi_bridge_msgs/srv/SetString` | ALTextToSpeech.setLanguage | idioma de TTS/ASR del host | ✅ supported |  |
| `get_language` (srv) | `naoqi_bridge_msgs/srv/GetString` | ALTextToSpeech.getLanguage | idioma de TTS/ASR del host | ✅ supported |  |
| `listen` (action) | `naoqi_bridge_msgs/action/Listen` | ALDialog / ALSpeechRecognition | ASR Vosk en el host sobre el stream mic | 🟡 partial | requiere modelo Vosk descargado; sin modelo responde resultado vacío |

## Nuevas en el D3

| Interfaz | Tipo | NAOqi | D3 | Estado | Notas |
|---|---|---|---|---|---|
| `sonar/front_left` (pub) | `sensor_msgs/msg/Range` | - (nuevo en D3) | DRUltrasonic.measurement sensor 1 | ✅ supported |  |
| `sonar/front_right` (pub) | `sensor_msgs/msg/Range` | - (nuevo en D3) | DRUltrasonic.measurement sensor 3 | ✅ supported |  |

## naoqi_miscellaneous_node

| Interfaz | Tipo | NAOqi | D3 | Estado | Notas |
|---|---|---|---|---|---|
| `set_autonomous_state` (srv) | `std_srvs/srv/SetBool` | ALAutonomousLife | - | 🔵 noop |  |
| `toggle_awareness` (srv) | `std_srvs/srv/SetBool` | ALBasicAwareness | - | 🔵 noop |  |
| `toggle_blinking` (srv) | `std_srvs/srv/SetBool` | ALAutonomousBlinking | - | 🔵 noop |  |
| `battery_percentage` (pub) | `std_msgs/msg/Float32` | ALBattery.getBatteryCharge | DRBase.status.battery | ✅ supported |  |
| `set_leds` (sub) | `naoqi_utilities_msgs/msg/LedParameters` | ALLeds.fadeRGB | se registra y se ignora con un aviso | 🟡 partial | el D3 no tiene LEDs controlables; la suscripción existe para no romper clientes |

## naoqi_manipulation_node

| Interfaz | Tipo | NAOqi | D3 | Estado | Notas |
|---|---|---|---|---|---|
| `go_to_posture` (srv) | `naoqi_utilities_msgs/srv/GoToPosture` | ALRobotPosture.goToPosture | Stand: pole.stand + kickstand.retract; Sit/Rest: pole.sit + kickstand.deploy | 🟡 partial |  |
| `play_animation` (srv) | `naoqi_utilities_msgs/srv/PlayAnimation` | ALBehaviorManager | secuencias de pole/tilt/giro (nod, shake, greet...) | 🟡 partial |  |
| `set_tangential_security_distance` (srv) | `naoqi_utilities_msgs/srv/SetSecurityDistance` | ALMotion.setTangentialSecurityDistance | navigate.obstacleAvoidance.setLevel (<0.1 m -> 0) | 🟡 partial |  |
| `set_orthogonal_security_distance` (srv) | `naoqi_utilities_msgs/srv/SetSecurityDistance` | ALMotion.setOrthogonalSecurityDistance | navigate.obstacleAvoidance.setLevel | 🟡 partial |  |
| `enable_default_security` (srv) | `std_srvs/srv/Trigger` | ALMotion | navigate.obstacleAvoidance.setLevel 2 | ✅ supported |  |
| `set_stiffnesses` (srv) | `naoqi_utilities_msgs/srv/SetStiffnesses` | ALMotion.setStiffnesses | - | ⛔ unsupported |  |
| `toggle_smart_stiffness` (srv) | `std_srvs/srv/SetBool` | ALMotion.setSmartStiffnessEnabled | - | ⛔ unsupported |  |
| `set_open_close_hand` (srv) | `naoqi_utilities_msgs/srv/SetOpenCloseHand` | ALMotion.setAngles | - | ⛔ unsupported |  |
| `toggle_breathing` (srv) | `naoqi_utilities_msgs/srv/SetBreathing` | ALMotion.setBreathEnabled | - | ⛔ unsupported |  |
| `set_move_arms_enabled` (srv) | `naoqi_utilities_msgs/srv/SetMoveArmsEnabled` | ALMotion.setMoveArmsEnabled | - | ⛔ unsupported |  |
| `toggle_arms_collision_protection` (srv) | `std_srvs/srv/SetBool` | ALMotion.setCollisionProtectionEnabled | - | ⛔ unsupported |  |

## naoqi_navigation_node

| Interfaz | Tipo | NAOqi | D3 | Estado | Notas |
|---|---|---|---|---|---|
| `move_to` (srv) | `naoqi_utilities_msgs/srv/MoveTo` | ALMotion.moveTo | navigate.target relative + espera DRNavigateModule.arrive | ✅ supported |  |
| `navigate_to` (srv) | `naoqi_utilities_msgs/srv/MoveTo` | ALNavigation.navigateTo | navigate.target absoluto en el frame de DRPose (odom) | 🟡 partial | sin mapa: el frame es la odometría desde el arranque (pose.resetOrigin) |
| `start_exploring` (srv) | `naoqi_utilities_msgs/srv/Explore` | ALNavigation.explore | - | ⛔ unsupported |  |
| `stop_exploring` (srv) | `std_srvs/srv/Trigger` | ALNavigation.stopExploration | - | ⛔ unsupported |  |

## naoqi_perception_node

| Interfaz | Tipo | NAOqi | D3 | Estado | Notas |
|---|---|---|---|---|---|
| `set_tracker_mode` (srv) | `naoqi_utilities_msgs/srv/SetTrackerMode` | ALTracker / ALBasicAwareness | stop: soportado; start_*: seguimiento de rostro en el host | 🟡 partial | fase posterior: detector de rostros sobre camera/front + base.turnBy / tilt.target |
| `point_at` (srv) | `naoqi_utilities_msgs/srv/PointAt` | ALTracker.pointAt | - | ⛔ unsupported |  |

## naoqi_speech_node

| Interfaz | Tipo | NAOqi | D3 | Estado | Notas |
|---|---|---|---|---|---|
| `say` (srv) | `naoqi_utilities_msgs/srv/Say` | ALTextToSpeech / ALAnimatedSpeech | TTS en el host (espeak-ng; Piper opcional) -> WAV -> aplay en el D3 | 🟡 partial | animated se ignora; asynchronous se respeta |
| `shut_up` (srv) | `std_srvs/srv/Trigger` | ALTextToSpeech.stopAll | agent.audio.stop | ✅ supported |  |
| `set_volume` (srv) | `naoqi_utilities_msgs/srv/SetVolume` | ALAudioDevice.setOutputVolume | speaker.setVolume | ✅ supported |  |
| `get_volume` (srv) | `naoqi_utilities_msgs/srv/GetVolume` | ALAudioDevice.getOutputVolume | speaker.requestVolume -> DRSpeaker.volume | ✅ supported |  |
| `configure_speech` (srv) | `naoqi_utilities_msgs/srv/ConfigureSpeech` | ALSpeechRecognition | vocabulario/idioma del ASR Vosk en el host | 🟡 partial |  |
| `play_sound` (srv) | `naoqi_utilities_msgs/srv/PlaySound` | ALAudioPlayer.playFile | archivo WAV del HOST subido a d3_agent | 🟡 partial | en Pepper la ruta era del robot; aquí es del contenedor del host |
| `play_web_stream` (srv) | `naoqi_utilities_msgs/srv/PlayWebStream` | ALAudioPlayer.playWebStream | playbin en d3_agent | ✅ supported |  |
| `stop_all_sounds` (srv) | `std_srvs/srv/Trigger` | ALAudioPlayer.stopAll | agent.audio.stop | ✅ supported |  |
| `word_recognized` (pub) | `naoqi_utilities_msgs/msg/WordConfidence` | ALMemory WordRecognized | Vosk con gramática del vocabulario | 🟡 partial |  |

## naoqi_interface_node

| Interfaz | Tipo | NAOqi | D3 | Estado | Notas |
|---|---|---|---|---|---|
| `show_image` (srv) | `naoqi_utilities_msgs/srv/SendURL` | ALTabletService.showImage | gui.accessoryWebView.open | ✅ supported |  |
| `show_webview` (srv) | `naoqi_utilities_msgs/srv/SendURL` | ALTabletService.showWebview | gui.accessoryWebView.open | ✅ supported |  |
| `play_video` (srv) | `naoqi_utilities_msgs/srv/SendURL` | ALTabletService.playVideo | gui.accessoryWebView.open | ✅ supported |  |
| `hide_tablet` (srv) | `std_srvs/srv/Trigger` | ALTabletService.hide | gui.accessoryWebView.close | ✅ supported |  |
| `show_topic_stream` (srv) | `naoqi_utilities_msgs/srv/SendURL` | ALTabletService.showWebview + web_video_server | accessoryWebView -> http://HOST_IP:8080/stream?topic= | ✅ supported |  |
| `show_text` (srv) | `naoqi_utilities_msgs/srv/ShowText` | ALTabletService show_words.html | página text.html servida por d3_agent | ✅ supported |  |
| `get_input` (srv) | `naoqi_utilities_msgs/srv/GetInput` | ALTabletService input_*.html + onJSEvent | página input.html -> POST a d3_agent -> DRAgent.input | ✅ supported |  |
| `take_and_show_picture` (srv) | `std_srvs/srv/Trigger` | ALPhotoCapture + ALTabletService | último frame de camera/front -> página en pantalla | 🟡 partial |  |
| `toggle_app_launcher` (srv) | `std_srvs/srv/SetBool` | ALServiceManager / AppLauncher | gui.show / gui.hide | 🟡 partial |  |
