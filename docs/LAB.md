# Guía de laboratorio: conectar el Double 3 real

Todo el desarrollo funciona con el simulador (`make sim`). Esta guía es para el día en que el robot
esté disponible en COLIVRI.

## 1. Conectar el D3 a la red

1. En la pantalla del robot: Settings → WiFi → la red del laboratorio.
2. Anota la IP del robot en esa red. Va en tu `.env` como `D3_IP`; **no** en archivos del repo.
3. El Mac o PC debe estar en la misma red y llegar al robot: `ping <D3_IP>`.

## 2. Verificar el developer mode (requisito)

Sin developer mode el D3 **no expone ningún puerto TCP**. Su API es solo un socket Unix local
(`/tmp/doubleapi`), el firewall está activo y no hay SSH. Por eso no basta con conectarlo a la red.

Desde el Mac:

```bash
open http://<D3_IP>:8080        # si carga el "Developer Monitor", el modo está activo
ssh double@<D3_IP>              # la contraseña la envía Double por correo
```

- **Si funciona**: sigue con el paso 3.
- **Si no funciona**: el developer mode solo lo activa Double, de forma remota. Hay que vincular el D3 a
  la cuenta Double del laboratorio y escribir a devteam@doublerobotics.com con el serial de la cabeza
  (`<HEAD_SERIAL>`; no lo publiques). Antes, pregunta en COLIVRI si alguien ya lo pidió y quién tiene
  la contraseña del usuario `double`.

Recomendado al entrar por SSH: configura una llave (`ssh-copy-id double@<D3_IP>`) para no usar la
contraseña.

## 3. Instalar d3_agent en el robot

`d3_agent` es el puerto TCP (22022) al que se conecta el contenedor del Mac. Solo usa la stdlib de
Python 3.6 y no instala nada con apt (el disco del D3 tiene ~1 GB libre y no hay restauración de fábrica).

```bash
D3_SSH=double@<D3_IP> ./d3_agent/install.sh
```

El script genera un token, lo guarda en el robot (`/etc/d3_agent/token`, permisos 600) y en tu `.env`.
Luego verifica:

```bash
ssh double@<D3_IP> 'systemctl status d3-agent --no-pager | head -5'
nc -vz <D3_IP> 22022
```

## 4. Lanzar el bringup contra el robot

```bash
make up && make build
make robot          # usa D3_IP y D3_TOKEN de .env
make check          # 64/64 interfaces del contrato
```

## 5. Grabar los eventos reales (los payloads no están documentados)

El SDK no documenta los campos de los eventos. El parser es tolerante, pero hay que confirmar los
campos con datos reales:

```bash
ssh double@<D3_IP> 'sudo systemctl stop d3-agent; python3 /opt/d3_agent/d3_agent.py \
  --token-file /etc/d3_agent/token --record /tmp/events.raw.jsonl'
# en otra terminal: make robot, mueve el robot, sube/baja el pole, habla al micrófono... luego Ctrl-C
scp double@<D3_IP>:/tmp/events.raw.jsonl recordings/            # recordings/ está en .gitignore
python3 tools/sanitize_fixtures.py recordings/events.raw.jsonl d3_sim/fixtures/lab.jsonl
```

Revisa `d3_sim/fixtures/lab.jsonl` **a mano** antes de subirlo. Revisa en particular estos campos:

| Evento | Supuesto actual (ASSUMED) | Parámetro a ajustar |
|---|---|---|
| `DRBase.status` | `battery` 0-100, `pole` 0..1, `kickstand` 1=desplegado / 2=retraído | `battery_scale` |
| `DRUltrasonic.measurement` | `sensor` 0-4 (izq→der), `distance` en m | `sonar_names`, `sonar_frames` |
| `DRPose.pose` | `base.x`, `base.y`, `base.yaw`, `base.speed` | — |
| `DRMotor.position` | `percent` 0 (arriba) .. 1 (abajo) | `tilt_up_rad`, `tilt_down_rad` |
| `DRSpeaker.volume` | `percent` 0..1 | — |

## 6. Calibración

- **Velocidad**: publica `cmd_vel` con `linear.x=0.2` durante 5 s, mide la distancia real y ajusta
  `max_linear_speed` en `d3_bringup2/config/d3.yaml`. Haz lo mismo con el giro (`max_angular_speed`;
  usa `invert_turn` si gira al revés).
- **Cámara**: `ros2 run camera_calibration cameracalibrator` sobre `/d3/camera/front/image_raw` con un
  tablero; copia `fx` en `camera_fx`.
- **Seguridad**: haz las primeras pruebas con el robot en un espacio libre, a velocidades bajas y con una
  persona cerca del robot. La evasión de obstáculos del D3 queda en el nivel 2 por defecto
  (`enable_default_security`).

## 7. Pruebas de profundidad, grilla y marcas

Objetivo: saber si el D3 puede localizarse contra un mapa 2D (por ejemplo, el del MentorPi) **sin perder
su evasión de obstáculos**. Las pruebas van de menor a mayor riesgo. No pases a la siguiente sin cerrar
la anterior.

> **Reglas**
> - Las pruebas 1 a 8 se hacen con el **robot quieto y el kickstand desplegado**. `make robot` deja el
>   robot en `Stand` (kickstand retraído), así que después de lanzarlo corre
>   `ros2 service call /d3/go_to_posture naoqi_utilities_msgs/srv/GoToPosture "{posture_name: 'Rest'}"`.
> - **Nunca** uses `d3_agent --record` para grabar profundidad: graba en el disco del robot, que tiene
>   ~1 GB libre y no tiene restauración de fábrica. Graba siempre en el servidor (`recordings/`).
> - **Nunca** envíes `events.subscribe` con `"*"`: el SDK lo describe como "a firehose of data".
> - Antes de la prueba 11 no se envía ningún comando que cambie configuración (`depth.*`, `gridManager.*`,
>   `navigate.obstacleAvoidance.setLevel` distinto de 2).
> - Toda grabación pasa por `tools/sanitize_fixtures.py` y se revisa a mano antes de versionarla. Las
>   crudas se quedan en `recordings/` (ignorada por git). Versiona solo extractos pequeños:
>   `make safety` rechaza archivos de más de 5 MB.

> **Pendiente (requisito antes de las pruebas 4-5):** agregar al `docker/Dockerfile` el paquete
> `ros-jazzy-camera-calibration` y un detector de AprilTag (por ejemplo `pupil-apriltags` o
> `ros-jazzy-apriltag-ros`). Mientras no estén en la imagen, se instalan a mano en el contenedor, como
> se indica en esas pruebas, y la instalación se pierde al recrearlo.

### Preparación común

Terminal A: `make robot`. Terminal B: `make shell` (el contenedor ya trae `nc` y las variables `D3_IP`,
`D3_PORT` y `D3_TOKEN` de `.env`). En la terminal B define esta función. Abre una **conexión de control
aparte** con `d3_agent` (JSON por línea, ver `d3_sdk_client/protocol.py`), envía los comandos en orden,
espera N segundos y cierra. No toca las conexiones del bringup.

```bash
cd /workspace/ws/src/double3_ros2_bringup2 && mkdir -p recordings
d3_raw() {  # uso: d3_raw <segundos> <archivo_salida> '<json>' ['<json>' ...]
  local secs=$1 out=$2; shift 2
  { printf '{"auth":"%s","role":"control"}\n' "$D3_TOKEN"; printf '%s\n' "$@"; sleep "$secs"; } \
    | nc -N "$D3_IP" "${D3_PORT:-22022}" > "$out"
}
```

La primera línea de la salida es la respuesta del handshake (`{"ok":true,...}`) y el resto son eventos.

**Parada de emergencia** cuando el robot se mueve (pruebas 9 y 10). Con `cmd_vel_timeout: 0.0` (valor por
defecto) el driver **retiene la última velocidad** y la reenvía cada 200 ms. Por eso, cortar
`ros2 topic pub` con Ctrl-C **no detiene el robot** y `navigate.stop` queda pisado por el siguiente
reenvío. Para detenerlo hay que publicar velocidad cero:
`ros2 topic pub --once /d3/cmd_vel geometry_msgs/msg/Twist "{}"`. Mejor aún: para estas pruebas pon
`cmd_vel_timeout: 0.5` en `d3_bringup2/config/d3.yaml` **antes** de `make robot` (el driver lee los
parámetros solo al arrancar) y no subas ese cambio.

### Prueba 1. Latencia de red con `agent.ping` (solo lectura)

- **Objetivo:** tener la línea base de ida y vuelta servidor ↔ `d3_agent`. `agent.ping` lo responde el
  agente y no llega a la API del D3.
- **Cómo:** en la terminal B, `ping -c 50 "$D3_IP"` y luego:
  ```bash
  python3 - <<'EOF'
  import os, statistics, time
  from d3_sdk_client import D3Client
  c = D3Client(os.environ["D3_IP"], int(os.environ.get("D3_PORT", 22022)), os.environ["D3_TOKEN"]).start()
  assert c.wait_connected(5), "sin conexión con d3_agent"
  rtt = []
  for _ in range(100):
      t = time.monotonic()
      if c.request("agent.ping", None, "DRAgent.pong", timeout=2) is not None:
          rtt.append((time.monotonic() - t) * 1000)
      time.sleep(0.1)
  q = statistics.quantiles(rtt, n=20)
  print("n=%d perdidos=%d min=%.1f mediana=%.1f p95=%.1f max=%.1f ms"
        % (len(rtt), 100 - len(rtt), min(rtt), statistics.median(rtt), q[18], max(rtt)))
  c.stop()
  EOF
  ```
- **Qué se registra:** mínimo, mediana, p95, máximo y pings perdidos de ICMP y de `agent.ping`, y la red
  usada (Wi-Fi del laboratorio o cable en el servidor).
- **Listo cuando:** hay tres corridas en momentos distintos y sus cifras quedan anotadas.

### Prueba 2. Grabar eventos sin cambiar configuración

- **Objetivo:** saber si los eventos de profundidad, grilla y marcas llegan **sin habilitar nada**, qué
  traen, cuánto pesan y con qué frecuencia llegan.
- **Cómo:** con el bringup corriendo y el robot quieto:
  ```bash
  F=recordings/eventos_$(date +%Y%m%d_%H%M%S).raw.jsonl
  d3_raw 30 "$F" '{"c":"events.subscribe","d":{"events":["DRGridManager.robotGrid","DRFrontDepth.frame","DRFloorDepth.frame","DRCamera.tags","DRPose.resetOrigin"]}}'
  python3 - "$F" <<'EOF'
  import collections, json, sys
  n, size = collections.Counter(), collections.defaultdict(list)
  for line in open(sys.argv[1], encoding="utf-8"):
      try:
          e = json.loads(line)
      except ValueError:
          continue
      if "class" in e:
          k = "%s.%s" % (e["class"], e["key"]); n[k] += 1; size[k].append(len(line))
  for k in sorted(n):
      print("%-26s %5d ev  %6.2f/s  prom %9d B  max %9d B"
            % (k, n[k], n[k] / 30.0, sum(size[k]) // n[k], max(size[k])))
  EOF
  ```
  Para ver las claves de cada evento: `grep -m1 '"key":"frame"' "$F" | cut -c1-400`.
- **Qué se registra:** una tabla por evento con estas columnas: ¿llega?, eventos/s, tamaño promedio y
  máximo, si el contenido es binario o base64, y los nombres de los campos.
- **Si un evento no llega:** se anota "no llega sin habilitar". **No** se envía `depth.*.enable` ni
  `gridManager.enable`: eso es configuración (prueba 11).
- **Listo cuando:** la tabla está completa para los cinco eventos y la grabación quedó en `recordings/`.

### Prueba 3. Efecto sobre la pose durante la prueba 2

- **Objetivo:** confirmar que recibir profundidad no retrasa ni corta la pose, el video ni el audio del
  bringup.
- **Cómo:** en otra terminal (`make shell`), mide 30 s **sin** la suscripción de la prueba 2 y repite
  **durante** ella:
  - `ros2 topic hz /d3/odom --window 300`
  - `ros2 topic hz /d3/camera/front/image_raw/compressed`
  - el script de `agent.ping` de la prueba 1

  `ros2 topic delay` no sirve aquí: el driver pone la marca de tiempo al recibir el evento en el servidor
  (`driver_node.py`, `on_pose`), así que no ve el retraso robot → servidor. El `agent.ping` hecho en
  paralelo es la medida indirecta de ese retraso.
- **Qué se registra:** Hz promedio, desviación y hueco máximo de `odom` y de la cámara, y p95 de
  `agent.ping`, con y sin suscripción.
- **Listo cuando:** hay una tabla comparativa. Si `odom` pierde frecuencia o el p95 sube de forma clara,
  se anota como límite: la profundidad no puede ir por la misma red sin reducirla.

### Prueba 4. Calibrar la cámara frontal

- **Objetivo:** reemplazar los intrínsecos supuestos (HFOV 100°, sin distorsión: `driver_node.py`,
  `setup_camera`) por una calibración real a **640×400**, la resolución que se usará para AprilTag.
- **Cómo:** `camera_calibration` **no viene en la imagen**. Instálalo en el contenedor (se pierde al
  recrearlo) y usa X11; en Linux está habilitado por `compose.linux.yaml`. Mueve el tablero, no el robot:
  ```bash
  apt-get update && apt-get install -y ros-jazzy-camera-calibration
  ros2 run camera_calibration cameracalibrator --size 8x6 --square 0.025 --no-service-check \
    --ros-args -r image:=/d3/camera/front/image_raw -r camera:=/d3/camera/front
  ```
  `--size` son las esquinas **interiores** del tablero y `--square` el lado del cuadro en metros: ajústalos
  a tu tablero. Deja el tilt de la cabeza fijo durante toda la prueba.
- **Qué se registra:** `ost.yaml` (se guarda con SAVE en `/tmp/calibrationdata.tar.gz`; cópialo a
  `recordings/`), el error de reproyección que muestra la herramienta, la resolución y la posición del tilt.
- **Listo cuando:** existe `ost.yaml` a 640×400 con error de reproyección anotado (idealmente < 0,5 px).
  Hoy el driver solo usa `camera_fx`: el resto de la calibración se usa directamente en la prueba 5.

### Prueba 5. Alcance de detección de AprilTag a 640×400

- **Objetivo:** saber a qué distancia y ángulo máximos se detecta una AprilTag con la cámara ya
  calibrada, para dimensionar las marcas del piso o las paredes.
- **Cómo:** el robot sigue quieto y se mueve la marca. Imprime marcas `tag36h11` de 10, 15 y 20 cm de
  lado (el cuadro negro) y mide su tamaño real. Ponlas a la altura aproximada de la cámara, a 1, 2, 3, 4,
  5 y 6 m, de frente y giradas 30°, 45° y 60°. En cada posición graba 10 s:
  `ros2 bag record -o recordings/tag_<tam>_<dist>_<ang> /d3/camera/front/image_raw/compressed`.
  Detecta fuera de línea con los intrínsecos de `ost.yaml`, por ejemplo con `pupil-apriltags`
  (`pip install pupil-apriltags`, no viene en la imagen).
- **Qué se registra:** por tamaño, distancia y ángulo: porcentaje de cuadros con detección y error de la
  distancia estimada contra la cinta métrica.
- **Listo cuando:** para cada tamaño de marca hay una distancia máxima con al menos 90 % de detección y
  un ángulo máximo a esa distancia, con su error de distancia.

### Prueba 6. Decodificar `robotGrid` y compararla con el entorno

- **Objetivo:** saber si la grilla distingue obstáculo, libre y desconocido, y en qué orientación está.
  Es requisito para convertirla en `LaserScan`.
- **Cómo:** pon una caja a ~1 m al frente y una pared a ~2 m a un lado, y mide las distancias. Graba y
  decodifica. Según el SDK, el campo `base64` es un `Uint8Array` comprimido con zlib de 40000 valores
  (200×200 casillas de 10 cm); confirma los nombres reales de los campos en la grabación.
  ```bash
  F=recordings/grid_$(date +%Y%m%d_%H%M%S).raw.jsonl
  d3_raw 15 "$F" '{"c":"events.subscribe","d":{"events":["DRGridManager.robotGrid"]}}'
  python3 - "$F" <<'EOF'
  import base64, collections, json, sys, zlib
  import cv2, numpy as np
  for line in open(sys.argv[1], encoding="utf-8"):
      e = json.loads(line)
      if e.get("class") == "DRGridManager" and e.get("key") == "robotGrid":
          d = e["data"]
          raw = zlib.decompress(base64.b64decode(d["base64"]))
          print("bytes:", len(raw), "otras claves:", {k: v for k, v in d.items() if k != "base64"})
          g = np.frombuffer(raw, np.uint8)
          print("valores:", collections.Counter(g.tolist()).most_common(10))
          if g.size == 40000:
              cv2.imwrite("recordings/grid.png", cv2.resize(g.reshape(200, 200), (800, 800),
                                                            interpolation=cv2.INTER_NEAREST))
          break
  EOF
  ```
- **Qué se registra:** los valores distintos y su cantidad, qué valor cae sobre la caja y la pared, el eje
  que apunta al frente del robot y el significado de `offset`. Si la grilla está vacía con el robot quieto,
  se anota y se repite la grabación durante la prueba 9.
- **Listo cuando:** hay una tabla valor → significado (obstáculo, libre, desconocido) confirmada con la
  caja y la pared, y la orientación de la grilla respecto a `base_footprint`.

### Prueba 7. `camera.tagDetector` con un QR impreso

- **Objetivo:** saber qué trae `DRCamera.tags`: solo el contenido, o también esquinas, posición o pose.
- **Cómo:** imprime un QR con el texto `d3-lab-01` y mide su lado en metros. Con el robot quieto, ponlo
  frente a la cámara:
  ```bash
  d3_raw 20 recordings/tags_$(date +%Y%m%d_%H%M%S).raw.jsonl \
    '{"c":"events.subscribe","d":{"events":["DRCamera.tags"]}}' \
    '{"c":"camera.tagDetector.enable","d":{"format":"QRCode","anyTag":true,"tags":[{"content":"d3-lab-01","action":"text","shape":"info","size":0.10,"red":1,"green":0,"blue":0}]}}'
  d3_raw 2 /dev/null '{"c":"camera.tagDetector.disable"}'
  d3_raw 10 recordings/tags_apagado.raw.jsonl '{"c":"events.subscribe","d":{"events":["DRCamera.tags"]}}'
  ```
  Ajusta `size` a la medida real. Mientras corre, revisa `ros2 topic hz /d3/camera/front/image_raw/compressed`.
- **Qué se registra:** los campos de `DRCamera.tags` y su frecuencia, si la cámara del bringup se corta o
  baja de fps, y si aparece algo en la pantalla del robot.
- **Listo cuando:** el contenido del evento está documentado aquí, `tags_apagado.raw.jsonl` no tiene
  eventos `DRCamera.tags` (el detector quedó apagado) y la cámara sigue a su frecuencia normal.

### Prueba 8. `pose.resetOrigin` con el robot quieto

- **Objetivo:** ver el salto de `odom` y averiguar cuándo cambia el origen por su cuenta. El driver no lo
  maneja: publica la pose tal cual llega.
- **Cómo:** hazla con el robot detenido **después** de haberlo movido (por ejemplo al final de la sesión
  de las pruebas 9 y 10). Si se hace antes, la pose ya está cerca de cero y el salto no se ve. En una
  terminal, `ros2 topic echo /d3/odom --field pose.pose`. En otra:
  ```bash
  d3_raw 5 recordings/reset_$(date +%Y%m%d_%H%M%S).raw.jsonl \
    '{"c":"events.subscribe","d":{"events":["DRPose.resetOrigin","DRPose.pose"]}}' '{"c":"pose.resetOrigin"}'
  ```
  Luego apaga y enciende el robot sin moverlo y anota la primera pose después del arranque. La parte del
  dock (¿cambia el origen al salir del dock?) implica movimiento: hazla con las condiciones de la prueba 9.
- **Qué se registra:** la pose antes y después (x, y, yaw), si llega `DRPose.resetOrigin`, la pose tras el
  reinicio y la pose antes y después de salir del dock.
- **Listo cuando:** se sabe si `resetOrigin` pone en cero x, y y yaw, y si el origen cambia al encender y
  al salir del dock.

### Prueba 9. Manejar despacio con evasión nivel 2 y la suscripción de profundidad activa

- **Objetivo:** confirmar que la evasión del D3 se comporta igual con y sin la suscripción de la
  prueba 2.
- **Cómo:** en un espacio libre, con una persona junto al robot lista para la parada de emergencia y
  `cmd_vel_timeout: 0.5` configurado (ver "Preparación común"):
  1. `ros2 service call /d3/go_to_posture naoqi_utilities_msgs/srv/GoToPosture "{posture_name: 'Stand'}"`
     y luego `ros2 service call /d3/enable_default_security std_srvs/srv/Trigger`.
  2. Pon una caja a 3 m al frente. Recorrido de referencia **sin** suscripción:
     `ros2 service call /d3/move_to naoqi_utilities_msgs/srv/MoveTo "{x_coordinate: 4.0, y_coordinate: 0.0, theta_coordinate: 0.0}"`.
  3. Repite **con** la suscripción de la prueba 2 activa (`d3_raw 120 ...` en otra terminal).
  4. Repite los dos casos con `cmd_vel` lento:
     `ros2 topic pub -r 5 /d3/cmd_vel geometry_msgs/msg/Twist "{linear: {x: 0.15}}"`.
- **Qué se registra:** en cada pasada, si el robot frena, se detiene o rodea la caja, y a qué distancia.
  Graba también la suscripción para repetir la prueba 6 si la grilla estaba vacía.
- **Listo cuando:** hay tres pasadas por caso y el comportamiento con suscripción es igual al de
  referencia. Si cambia, se detiene todo y se anota.

### Prueba 10. Deriva de la odometría cada 10 m

- **Objetivo:** medir cuánto error acumula `odom` para dimensionar cada cuánto hace falta relocalizar con
  marcas.
- **Cómo:** mismas condiciones de la prueba 9, con el camino libre para que la evasión no desvíe al
  robot. Marca en el piso con cinta el punto de partida y la dirección. Anota `odom` al inicio y al final
  (`ros2 topic echo --once /d3/odom --field pose.pose`). Graba también `DRPose.yawRateProblem` con
  `d3_raw`.
  - **Recta:** `move_to` con `x_coordinate: 10.0` (o dos tramos de 5 m).
  - **Con un giro:** 5 m, giro de 90° (`theta_coordinate: 1.5708` con x = y = 0) y otros 5 m.
- **Qué se registra:** posición y orientación final medidas con cinta y transportador contra las de
  `odom`: error de posición (cm), error de yaw (°), error por metro y eventos `yawRateProblem`.
- **Listo cuando:** hay tres repeticiones de cada recorrido, con error medio y máximo.

### Prueba 11. Cambiar configuración de `depth.*` (solo después de consultar a Double)

- **Objetivo:** probar `depth.front.*` o `depth.floor.*` (`enable` con parámetros, `detectors`,
  `setROI`, `disable`) si las pruebas anteriores muestran que hacen falta.
- **Requisito:** respuesta escrita de Double (devteam@doublerobotics.com) que diga qué valores usa el
  robot por defecto, cómo restaurarlos y si el cambio afecta la evasión. El SDK no documenta un comando
  para leer la configuración actual, y el robot no tiene restauración de fábrica.
- **Cómo:** con el robot quieto y el kickstand desplegado, cambia **un** parámetro por vez y anota el
  comando exacto. Antes de cualquier otro uso, restaura según la respuesta de Double y repite la prueba 9.
- **Qué se registra:** la respuesta de Double (resumida aquí), cada comando enviado y el resultado de la
  prueba 9 después de restaurar.
- **Listo cuando:** la configuración quedó restaurada y la prueba 9 vuelve a dar el comportamiento de
  referencia.

## Checklist del primer día

- [ ] SSH y Developer Monitor funcionan
- [ ] `d3-agent` activo y `nc -vz <D3_IP> 22022` responde
- [ ] `make robot` + `make check` → 64/64
- [ ] `/d3/odom` cambia al empujar el robot con `cmd_vel` lento
- [ ] `go_to_posture Stand/Rest` sube/baja el pole y mueve el kickstand
- [ ] `say` se oye en el parlante del D3
- [ ] La cámara se ve en Foxglove (`ws://localhost:8765`)
- [ ] `battery_percentage` coincide con la pantalla del robot
- [ ] `get_input` aparece en la pantalla y devuelve lo que se toca
- [ ] Eventos grabados, sanitizados y revisados
