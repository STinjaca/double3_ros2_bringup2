# Mismos comandos en macOS (Docker Desktop) y en Ubuntu 24.04 del laboratorio.
#   make image   construye la imagen      make up      levanta el contenedor
#   make build   colcon build             make sim     bringup con el simulador
#   make demo    demo de conformidad      make check   compara el grafo ROS con contract.yaml
#   make robot   bringup contra el D3 real (usa D3_IP y D3_TOKEN de .env)
COMPOSE := docker compose -f compose.yaml
ifeq ($(shell uname -s),Linux)
COMPOSE += -f compose.linux.yaml
FOXGLOVE ?= false
else
FOXGLOVE ?= true
endif
EXEC := $(COMPOSE) exec ros /entrypoint.sh bash -c
NS ?= d3

.PHONY: image up down shell build sim robot demo check test graph safety clean

image:
	$(COMPOSE) build

up:
	@mkdir -p models sounds
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

shell: up
	$(COMPOSE) exec ros bash

build: up
	$(EXEC) "colcon build --symlink-install --event-handlers console_cohesion+"

sim: up
	$(EXEC) "ros2 launch d3_bringup2 d3_bringup.launch.py use_sim:=true launch_foxglove:=$(FOXGLOVE)"

robot: up
	$(EXEC) 'ros2 launch d3_bringup2 d3_bringup.launch.py robot_ip:=$${D3_IP:?define D3_IP en .env} launch_foxglove:=$(FOXGLOVE)'

demo: up
	$(EXEC) "python3 /opt/deps_ws/src/naoqi_bringup2_sinfonIA/scripts/naoqi_capabilities_demo.py --ros-args \
	  -p robot_namespace:=$(NS) -p interactive_demo:=false -p step_pause_sec:=0.3 -p section_pause_sec:=0.3 \
	  -p call_tablet_services:=true -p call_sound_playback:=false -p call_exploration_services:=true"

check: up
	$(EXEC) "python3 src/double3_ros2_bringup2/contract/check_contract.py --namespace $(NS)"

test: up
	$(EXEC) "cd src/double3_ros2_bringup2 && python3 -m pytest -q d3_sdk_client/test d3_driver/test"

graph:
	python3 tools/codegraph/extract.py && python3 contract/gen_compat.py

safety:
	python3 tools/check_public_safety.py $$(git ls-files)

clean:
	$(COMPOSE) down -v
