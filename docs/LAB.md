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
