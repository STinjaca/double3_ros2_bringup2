# d3_agent

Corre **en la cabeza del Double 3** (Ubuntu 18.04, Python 3.6) y solo usa la stdlib. Es el único
componente que vive en el robot. Hace de puerto TCP (22022, protegido con token) entre el contenedor
ROS 2 del host y la API local del robot (`/tmp/doubleapi`).

| Rol (handshake) | Qué hace |
|---|---|
| `control` | Reenvía comandos y eventos JSON a `/tmp/doubleapi`, con una conexión por cliente. Atiende `agent.ping`, `agent.info` y `agent.audio.stop` |
| `video` | Activa `camera.enable {"template":"v4l2"}` y transmite JPEG desde `/dev/video9` con GStreamer |
| `audio` | Transmite PCM S16LE del micrófono (`arecord`) |
| `play` | Recibe un WAV (o una URL) y lo reproduce en el parlante (`aplay` / `playbin`) |

Además sirve `pages/` en `127.0.0.1:8081` para `show_text` y `get_input` en la pantalla. La página
`input.html` devuelve la respuesta con `POST /event` y el agente la reenvía como evento `DRAgent.input`.

## Parada segura al perder el control (comportamiento por defecto)

Si se cierra una conexión `control` que mandó comandos de movimiento (`navigate.drive`, `navigate.target`,
`base.turnBy`), el agente envía `navigate.cancelTarget` y `navigate.drive` en cero, y avisa a los demás
clientes con el evento `DRAgent.safeStop`. Las conexiones que solo observan no detienen al robot al cerrarse.

- `navigate.drive` ya se detiene solo por el watchdog de 500 ms del D3. El caso que cubre esta parada es
  `navigate.target` (`move_to`, `navigate_to`), que el robot sigue ejecutando por su cuenta.
- Una caída de Wi-Fi no cierra el socket por sí sola. Por eso el agente activa keepalive y
  `TCP_USER_TIMEOUT` en las conexiones `control` y da el enlace por muerto en `--link-timeout`
  segundos (por defecto 3; variable `D3_LINK_TIMEOUT`).

Seguir moviéndose sin el host **no** es nunca el comportamiento implícito. Una futura "ruta a bordo"
(por ejemplo, terminar el tramo actual si se cae la red) será un modo explícito que el cliente activa por
comando, con su propia política de parada. Qué hacer en un despliegue concreto (dónde parar, qué decir) se
define en el repo de ese despliegue, no aquí.

El protocolo está documentado en [`d3_sdk_client/protocol.py`](../d3_sdk_client/d3_sdk_client/protocol.py).

```bash
# En el robot (lo hace install.sh):
python3 d3_agent.py --profile robot --token-file /etc/d3_agent/token
# Grabar eventos crudos para fixtures (NO subir; sanitizar primero):
python3 d3_agent.py --token-file /etc/d3_agent/token --record /tmp/events.raw.jsonl
# Simulación (lo lanza d3_bringup2 con use_sim:=true):
python3 d3_agent.py --profile sim --api /tmp/doubleapi_sim --token <token>
```

Instalación en el robot: [`install.sh`](install.sh). Guía completa: [docs/LAB.md](../docs/LAB.md).
