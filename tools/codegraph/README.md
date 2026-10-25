# Grafo de código

`extract.py` analiza de forma estática los repos naoqi_* de SinfonIA (sin ejecutarlos) y los cruza con
`contract/contract.yaml`. El resultado es un grafo con estos nodos:

| Tipo de nodo | Ejemplo |
|---|---|
| `package` | `pkg:naoqi_speech` |
| `ros_node` | `node:naoqi_speech_node` |
| `interface` | `iface:say` (con `ros_kind`, `type` y `d3_status`) |
| `msg_type` | `type:naoqi_utilities_msgs/srv/Say` |
| `naoqi_api` | `naoqi:ALTextToSpeech.setLanguage`: lo que llama el callback de cada interfaz |
| `d3_node`, `d3_impl` | `d3node:d3_speech_node`, `d3impl:speaker.setVolume` |

```bash
python3 tools/codegraph/extract.py --src ../ros2_naoqi_ws/src
```

Salidas en `tools/codegraph/out/` (generadas, ignoradas por git):

- `graph.json`: nodos y aristas, para scripts o para cargarlo en una herramienta de IA.
- `graph.graphml`: para Gephi, yEd o NetworkX (`nx.read_graphml`).
- `graph.mmd`: vista Mermaid (nodo NAOqi → interfaz → nodo D3, coloreada por estado).
- `drift.txt`: diferencias entre el código y el contrato. El script termina con código 1 si falta algo,
  así que sirve como chequeo en CI cuando SinfonIA cambie sus repos.

## Herramientas de grafo de código con IA (complemento opcional)

El extractor propio es la base confiable, porque entiende ROS: sabe qué es un servicio y qué API NAOqi
llama cada callback. Para preguntas abiertas sobre el código ("¿dónde se maneja la reconexión?"),
se puede indexar el mismo directorio con una herramienta de grafo de código con IA que se exponga por
MCP a Claude Code.

Hay varios proyectos de código abierto de ese tipo, por ejemplo graphify, GitNexus o code-graph-rag.
**Ninguno está evaluado todavía en este proyecto.** Antes de adoptar uno, comprueba:

1. Que corra localmente, sin subir el código a un servicio externo.
2. Que entienda Python y C++.
3. Que importe o exporte GraphML/JSON, para combinarlo con `graph.json`.
