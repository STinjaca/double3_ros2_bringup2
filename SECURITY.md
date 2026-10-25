# Repo público: información sensible y cómo tratarla

Este repositorio es **público**. Cualquier commit queda publicado para siempre: aunque se borre después,
puede seguir en forks y cachés. Antes de cada push, revisa `git diff --cached` y corre `make safety`.

## Qué nunca va al repo

| # | Información | Riesgo | Cómo se trata |
|---|---|---|---|
| 1 | Contraseña SSH del usuario `double` (la envía Double por correo) | Control total del robot | Nunca va en archivos. Usar llave SSH en `~/.ssh` |
| 2 | Token de `d3_agent` (`D3_TOKEN`) | Cualquiera en la red podría mover el robot | Va en `.env` (ignorado) y en `/etc/d3_agent/token` en el robot. El agente rechaza `changeme` o un token vacío |
| 3 | Serial de la cabeza del D3 y la cuenta Double del laboratorio | Identifica el equipo y permite gestiones ante Double | En la documentación se escribe `<HEAD_SERIAL>` |
| 4 | IPs, SSID, contraseñas WiFi, MACs y hostnames del laboratorio | Mapea la red de la universidad | Van en `.env` o como argumentos del launch. En los ejemplos se usa `192.0.2.x` (RFC 5737) o `<D3_IP>` |
| 5 | Grabaciones de eventos del robot (`d3_agent --record`) | Contienen red, geolocalización y seriales | Se guardan en `recordings/` (ignorado). Solo se sube la salida de `tools/sanitize_fixtures.py`, revisada a mano |
| 6 | Video, audio, fotos, rosbags y capturas con personas | Datos personales (Ley 1581 de 2012, Habeas Data) y consentimiento | Prohibido subirlos; `.gitignore` bloquea `*.bag`, `*.mcap`, `*.wav`, `*.jpg`, `*.png`, etc. |
| 7 | Correo personal en los commits | Queda expuesto en el historial | Usar el correo noreply de GitHub (`git config user.email`) y activar "Block command line pushes that expose my email" |
| 8 | Manuales internos del laboratorio (PDFs de COLIVRI/SinfonIA) y rutas de los equipos | Material interno no publicado | No se copian al repo; solo se enlaza la documentación pública |
| 9 | Código o documentación de `d3-sdk` | El repo no declara licencia (todos los derechos reservados) | Se enlaza; el protocolo se reimplementa con código propio |
| 10 | Código de los repos naoqi_* de SinfonIA | Varios declaran la licencia como "TODO" | Solo se referencian en `d3.repos`; no se copian |
| 11 | Claves de servicios de IA en la nube | Costos y abuso | Solo como variables de entorno |
| 12 | Afiliación institucional | Que se lea como un producto oficial | El README y el NOTICE aclaran que es un proyecto de monitoría, sin afiliación oficial |

## Controles automáticos

- `.gitignore` estricto (secretos, grabaciones, media, modelos, build).
- `pre-commit` con gitleaks, detección de llaves privadas, archivos grandes y `tools/check_public_safety.py`,
  que bloquea IPs privadas o institucionales, MACs y secretos literales.
  Instalación: `pip install pre-commit && pre-commit install`.
- En GitHub: activar **Secret scanning** y **Push protection** (Settings → Code security).

## Reportar un problema de seguridad

Si encuentras información sensible publicada por error, abre un issue **sin** copiar el dato. También
puedes escribir al mantenedor por GitHub (@STinjaca). Se rotará el secreto y se limpiará el historial.
