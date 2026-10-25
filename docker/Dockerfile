# Imagen de desarrollo ROS 2 Jazzy para el bringup del Double 3.
# Multi-arquitectura: arm64 nativo en Mac (Apple Silicon) y amd64 en el PC Ubuntu 24.04 del lab.
# A diferencia de la imagen NAOqi no hace falta `platform: linux/amd64`: no usamos `qi` ni libqi.
FROM ros:jazzy-ros-base

ARG INSTALL_VOSK=true
ENV DEBIAN_FRONTEND=noninteractive \
    ROS_DISTRO=jazzy \
    PIP_BREAK_SYSTEM_PACKAGES=1 \
    RMW_IMPLEMENTATION=rmw_cyclonedds_cpp \
    D3_VOSK_MODELS_DIR=/models/vosk \
    D3_PIPER_MODELS_DIR=/models/piper

RUN apt-get update && apt-get install -y --no-install-recommends \
      python3-pip python3-vcstool python3-opencv python3-numpy python3-yaml python3-pytest \
      ros-jazzy-audio-common-msgs \
      ros-jazzy-foxglove-bridge \
      ros-jazzy-image-transport-plugins \
      ros-jazzy-rmw-cyclonedds-cpp \
      ros-jazzy-robot-state-publisher \
      ros-jazzy-rosbridge-server \
      ros-jazzy-tf2-ros \
      ros-jazzy-web-video-server \
      espeak-ng \
      gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
      iputils-ping netcat-openbsd nano \
    && rm -rf /var/lib/apt/lists/*

# ASR offline opcional (los modelos NO van en la imagen: se montan en /models/vosk/<idioma>)
RUN if [ "$INSTALL_VOSK" = "true" ]; then pip install --no-cache-dir vosk || echo "vosk no disponible en esta arquitectura"; fi

# Dependencias externas: solo mensajes (naoqi_utilities_msgs, naoqi_bridge_msgs) y el demo de conformidad.
COPY d3.repos /opt/deps_ws/d3.repos
RUN mkdir -p /opt/deps_ws/src && cd /opt/deps_ws \
 && vcs import --shallow src < d3.repos \
 && . /opt/ros/jazzy/setup.sh \
 && colcon build --packages-select naoqi_utilities_msgs naoqi_bridge_msgs --event-handlers console_direct- \
 && rm -rf build log

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh \
 && echo 'source /entrypoint.sh' >> /root/.bashrc

WORKDIR /workspace/ws
ENTRYPOINT ["/entrypoint.sh"]
CMD ["sleep", "infinity"]
