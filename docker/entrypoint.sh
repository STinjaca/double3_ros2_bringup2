#!/usr/bin/env bash
# Carga ROS, las dependencias de mensajes y el workspace (si ya está compilado).
# Se usa como ENTRYPOINT y también desde ~/.bashrc en shells interactivos.
source /opt/ros/jazzy/setup.bash
source /opt/deps_ws/install/setup.bash
if [ -f /workspace/ws/install/setup.bash ]; then
  source /workspace/ws/install/setup.bash
fi
# Solo como ENTRYPOINT ejecuta el comando; al hacer `source` desde .bashrc no hay argumentos.
if [ "${BASH_SOURCE[0]}" = "$0" ] && [ "$#" -gt 0 ]; then
  exec "$@"
fi
