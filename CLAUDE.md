# aquateam-taller

## Qué es este proyecto

Sistema de gestión del taller de reparaciones de Aquateam Balear. Controla los puestos de trabajo (bancos numerados del 4 al 20), el estado de cada equipo en reparación, el stock de guardias de dispensadores, el registro de técnicos con PIN y el historial de acciones.

**Funcionalidades:**
- Tablero de 17 puestos (números 4–20) con datos del equipo, cliente y estado de diagnóstico
- Ficha de puesto: datos del cliente (nombre, código, teléfono, delegación), tipo (comercial/alquiler/propiedad), datos del equipo (nombre, serie, código de barras), síntomas (check eléctrico, botones, no enfría, pérdida agua) y diagnósticos detallados (frío, eléctrico, agua)
- Stock de guardias: 3 tipos (`sotobanco`, `tres_aguas`, `dos_aguas`) con estado preparada/no preparada
- Gestión de técnicos: nombre + PIN de 4 dígitos, alta/modificación/baja (soft delete si tiene historial)
- Historial de acciones por puesto con trazabilidad de técnico, campo modificado y valor nuevo
- QR codes por puesto para acceso rápido desde móvil/tablet
- **WebSockets** para sincronización en tiempo real entre múltiples pantallas del taller

**No tiene IA ni RAG.** No usa Claude ni ninguna API de IA. Sistema completamente local.

**Sin login de sesión** — autenticación por PIN: admin vía `ADMIN_PIN` env var, técnicos vía PIN almacenado en la BD.

---

## Stack técnico

| Capa | Tecnología | Versión |
|------|-----------|---------|
| Backend framework | FastAPI | sin pinear (latest) |
| Servidor ASGI | Uvicorn[standard] | sin pinear |
| Base de datos | SQLite (aiosqlite async) | sin pinear |
| WebSockets | websockets | sin pinear |
| Formularios | python-multipart | sin pinear |
| Frontend | HTML + JS vanilla (archivos estáticos) | — |

**Diferencias clave respecto a otros repos Aquateam:**
- **Sin IA / Claude / RAG** — gestión pura de taller
- **aiosqlite directo** — sin SQLAlchemy ORM ni Alembic; `CREATE TABLE IF NOT EXISTS` + `ALTER TABLE` inline en `init_db()`
- **Migraciones inline** — columnas nuevas se añaden con `ALTER TABLE` en `init_db()` capturando la excepción si ya existen
- **Frontend HTML/JS vanilla** — sin React, sin npm, sin build step; 6 ficheros `.html` en `static/`
- **WebSockets nativos** — `ConnectionManager` con broadcast a todos los clientes conectados excepto el emisor
- **PIN sin hashear** — los PINs de técnicos se guardan en texto plano en la BD (no bcrypt ni hash)
- **Puerto hardcodeado 8000** en el Dockerfile — no usa `${PORT}` de Railway

---

## Arquitectura y archivos clave

```
aquateam-taller/
├── main.py          # FastAPI app: rutas HTML (FileResponse), API REST, WebSocket /ws
├── database.py      # aiosqlite: init_db(), CRUD puestos/stock/técnicos/historial
├── static/
│   ├── index.html         # Tablero de puestos (vista general del taller)
│   ├── puesto.html        # Ficha detalle de un puesto de reparación
│   ├── stock.html         # Estado stock de guardias
│   ├── qrs.html           # Generación/impresión de QR codes por puesto
│   ├── tecnicos.html      # Gestión de técnicos (CRUD)
│   └── historial.html     # Historial global de acciones
├── Dockerfile       # python:3.11-slim, CMD uvicorn puerto 8000 fijo
└── requirements.txt
```

**No hay `railway.toml`** — Railway auto-detecta el Dockerfile.

### Tablas SQLite

```
puestos (17 filas, números 4–20, creadas en init_db)
  numero (unique), nombre_cliente, codigo_cliente, es_comercial, es_alquiler,
  es_propiedad, delegacion, fecha_entrada, telefono, nombre_equipo, numero_serie,
  codigo_barras, descripcion_problema,
  check_electrico, check_botones, check_no_enfria, check_perdida_agua,
  diag_frio_termostato, diag_frio_condensador, diag_frio_gas,
  diag_elec_agitador, diag_elec_cableria, diag_elec_termostato,
  diag_elec_compresor, diag_elec_botonera,
  diag_agua_pin_electrico, diag_agua_banco_hielo, diag_agua_bomba_laton,
  diag_agua_condensador, updated_at

stock_guardias (3 filas fijas: sotobanco, tres_aguas, dos_aguas)
  tipo (unique), preparada, updated_at

tecnicos
  nombre, pin (4 dígitos, unique), activo, created_at

historial
  puesto_numero, tecnico_id, tecnico_nombre, accion, campo, valor_nuevo, timestamp
```

**Columnas añadidas por migración inline** (en producción ya existen):
- `es_alquiler`, `es_propiedad`, `codigo_cliente` — añadidas con `ALTER TABLE` en `init_db()`

### API REST (`main.py`)

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/api/puestos` | Lista todos los puestos |
| GET | `/api/puesto/{numero}` | Datos de un puesto |
| POST | `/api/puesto/{numero}` | Actualiza puesto; registra historial si viene `tecnico_id` + `cambios` |
| GET | `/api/stock` | Estado de las 3 guardias |
| POST | `/api/stock/{tipo}` | Actualiza estado de una guardia (`sotobanco`/`tres_aguas`/`dos_aguas`) |
| POST | `/api/auth/admin` | Valida PIN de admin contra `ADMIN_PIN` env var |
| POST | `/api/auth/pin` | Valida PIN de técnico contra BD (solo activos) |
| GET | `/api/tecnicos` | Lista técnicos |
| POST | `/api/tecnicos` | Crea técnico (nombre + PIN 4 dígitos único) |
| PUT | `/api/tecnicos/{id}` | Modifica técnico |
| DELETE | `/api/tecnicos/{id}` | Elimina técnico (soft delete si tiene historial, hard delete si no) |
| POST | `/api/historial` | Añade entrada de historial manual |
| GET | `/api/historial/puesto/{numero}` | Historial de un puesto |
| GET | `/api/historial` | Historial global (últimos 1000 registros) |
| WS | `/ws` | WebSocket: broadcast `puesto_updated`, `stock_updated`, `historial_updated` |

### WebSocket — eventos broadcast

```json
{"type": "puesto_updated", "numero": 5, "data": {...}}
{"type": "stock_updated", "data": [...]}
{"type": "historial_updated", "puesto_numero": 5}
```

Todos los clientes conectados a `/ws` reciben el evento excepto el emisor.

---

## Variables de entorno importantes

```env
# PIN de administrador (obligatoria en producción)
ADMIN_PIN=0000            # Default: "0000" — cambiar siempre en Railway

# Ruta de la base de datos SQLite
DB_PATH=/data/taller.db   # Default: ./taller.db (efímero sin volumen Railway)
                          # Para persistencia: crear volumen en Railway, montarlo en /data
                          # y configurar DB_PATH=/data/taller.db

# Puerto (Railway lo inyecta pero el Dockerfile NO lo usa — hardcodeado a 8000)
PORT=8000
```

**Nota crítica sobre `DB_PATH`:** sin volumen Railway y sin configurar `DB_PATH`, la BD se crea en `./taller.db` dentro del contenedor. Todos los datos (puestos, técnicos, historial) se pierden en cada redeploy. El comentario en `database.py:8` explica exactamente cómo configurar el volumen.

---

## Cómo se despliega

El proyecto se despliega en **Railway** con un único servicio.

No hay `railway.toml` — Railway auto-detecta el Dockerfile.

**Dockerfile:**
- Base: `python:3.11-slim` (sin dependencias del sistema adicionales)
- `pip install -r requirements.txt`
- `COPY . .`
- CMD: `uvicorn main:app --host 0.0.0.0 --port 8000`

**Inicialización de BD:** ocurre en el lifespan de FastAPI (`await init_db()` en el `@asynccontextmanager`). Se crean las tablas si no existen y se ejecutan las migraciones inline. Los 17 puestos (4–20) y las 3 guardias se insertan con `INSERT OR IGNORE`, por lo que son idempotentes.

**Env vars a configurar en Railway:**
- `ADMIN_PIN` — obligatoria (sin ella el PIN de admin es "0000")
- `DB_PATH` — obligatoria si se usa volumen para persistir datos (ej. `/data/taller.db`)

**Para persistencia en Railway:**
1. Crear un volumen en Railway y montarlo en `/data`
2. Configurar `DB_PATH=/data/taller.db` como variable de entorno del servicio

**Siempre hacer `git push` después de cada commit** — Railway despliega desde GitHub.

---

## Reglas importantes para no romper nada

- **Puestos numerados 4–20 (nunca 1–3)** — los números 1–3 no existen en el sistema. El `init_db()` hace `INSERT OR IGNORE` para `range(4, 21)`. No cambiar este rango sin entender el layout físico del taller.

- **Migraciones inline en `init_db()`** — las columnas `es_alquiler`, `es_propiedad` y `codigo_cliente` se añaden con `ALTER TABLE` capturando la excepción. Si se añaden nuevas columnas, seguir este mismo patrón en `database.py`. **No usar Alembic** — no está en el stack.

- **Soft delete de técnicos con historial** — `delete_tecnico()` comprueba si el técnico tiene registros en `historial`. Si los tiene, lo desactiva (`activo=0`) en lugar de borrarlo, para mantener la trazabilidad. No cambiar este comportamiento o el historial perderá referencias.

- **PIN de técnicos en texto plano** — los PINs se almacenan sin hashear. Son solo 4 dígitos numéricos (10.000 combinaciones). No es apropiado para datos sensibles, pero el sistema es de uso interno en el taller. No cambiar la BD a hashes sin actualizar la lógica del frontend.

- **Puerto 8000 hardcodeado en Dockerfile** — a diferencia de otros repos Aquateam, este Dockerfile no usa `${PORT:-8000}`. Railway inyecta `PORT` como env var pero el proceso escucha siempre en 8000. Railway detecta el `EXPOSE 8000` y lo mapea correctamente, pero si Railway cambia el puerto asignado puede haber problemas. Considerar cambiar a `CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]`.

- **`get_historial_all()` limitado a 1000 registros** — el endpoint `GET /api/historial` devuelve como máximo 1000 entradas ordenadas por timestamp DESC. Si el volumen de acciones es alto, las entradas más antiguas quedarán fuera. No es configurable actualmente.

- **WebSocket sin autenticación** — cualquiera que conozca la URL puede conectarse a `/ws` y recibir todos los eventos del taller en tiempo real. Es aceptable para uso en red local del taller, pero no para exponer públicamente.

- **`requirements.txt` sin versiones pinadas** — `fastapi`, `uvicorn[standard]`, `aiosqlite`, `websockets` y `python-multipart` no tienen versión fija. Un redeploy puede instalar versiones incompatibles si alguna de estas librerías introduce breaking changes. Considerar pinear versiones en producción.

- **Sin volumen → datos efímeros** — sin volumen Railway, cada redeploy destruye todos los datos. El comentario en `database.py:6-8` es explícito al respecto. Verificar siempre que `DB_PATH` apunta a un volumen persistente en producción.

---

## Errores conocidos y soluciones

| Error | Causa | Solución |
|-------|-------|---------|
| Datos del taller borrados tras redeploy | `DB_PATH` no configurado o sin volumen Railway | Crear volumen en Railway montado en `/data`, configurar `DB_PATH=/data/taller.db` |
| Admin PIN no funciona | `ADMIN_PIN` no configurada, usa default "0000" | Configurar `ADMIN_PIN` en las env vars del servicio en Railway |
| PIN de técnico rechazado aunque es correcto | Técnico marcado como `activo=0` | El técnico fue desactivado (soft delete); reactivarlo desde el panel de técnicos o directamente en la BD |
| WebSocket no conecta | FastAPI arranca sin `websockets` instalado | Verificar que `websockets` está en `requirements.txt` y fue instalado en el contenedor |
| `aiosqlite.OperationalError: database is locked` | Múltiples conexiones concurrentes a SQLite | Cada función en `database.py` abre y cierra su propia conexión via `async with aiosqlite.connect(DB_PATH)`. Si el volumen de peticiones es muy alto, considerar connection pooling o migrar a PostgreSQL |
| Puesto `{numero}` no encontrado (404) | Se intenta acceder a un puesto con número fuera de 4–20 | Solo existen puestos 4–20; verificar la URL del cliente |
| Columna `es_alquiler`/`es_propiedad`/`codigo_cliente` no existe | BD creada antes de las migraciones inline y `init_db()` no se ejecutó | Reiniciar el servicio (el lifespan ejecuta `init_db()` en cada arranque y aplica las migraciones) |
| `requirements.txt` instala versión incompatible | Sin versiones pinadas, pip resuelve latest | Pinear versiones en `requirements.txt` con las que funcionan en producción |
