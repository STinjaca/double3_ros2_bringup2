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
