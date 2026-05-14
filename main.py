import json
import os
from contextlib import asynccontextmanager
from typing import List

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from database import (
    init_db,
    get_all_puestos, get_puesto, update_puesto,
    get_stock, update_stock,
    get_all_tecnicos, get_tecnico_by_pin, create_tecnico, update_tecnico, delete_tecnico,
    add_historial, get_historial_puesto, get_historial_all,
)


class ConnectionManager:
    def __init__(self):
        self.active: List[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)

    async def broadcast(self, message: str, skip: WebSocket = None):
        dead = []
        for ws in self.active:
            if ws is skip:
                continue
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()

# ── WhatsApp config ───────────────────────────────────────────────────────────
WHATSAPP_DEST = os.environ.get("WHATSAPP_DEST", "34627461015")


async def send_whatsapp_notification(puesto_data: dict, tecnico_nombre: str):
    """Envía notificación WhatsApp vía el gateway propio al completar una reparación."""
    gateway_url = "https://aquateam-whatsapp-gateway-production.up.railway.app/send-template"
    destino = os.getenv("WHATSAPP_DEST", "34627461015")

    problemas = []
    if puesto_data.get("check_electrico"):   problemas.append("Problema eléctrico")
    if puesto_data.get("check_botones"):     problemas.append("Botones")
    if puesto_data.get("check_no_enfria"):   problemas.append("No enfría")
    if puesto_data.get("check_perdida_agua"): problemas.append("Pérdida de agua")
    problema_texto = ", ".join(problemas) if problemas else ""
    if puesto_data.get("descripcion_problema"):
        problema_texto += (" — " if problema_texto else "") + puesto_data["descripcion_problema"]

    cliente = puesto_data.get("nombre_cliente", "")
    codigo  = puesto_data.get("codigo_cliente", "")
    cliente_completo = f"{cliente} ({codigo})" if codigo else cliente

    payload = {
        "phone": destino,
        "template_name": "maquina_reparada",
        "components": [
            {"type": "text", "text": cliente_completo or "Sin nombre"},
            {"type": "text", "text": puesto_data.get("nombre_equipo") or "Sin equipo"},
            {"type": "text", "text": puesto_data.get("numero_serie") or "Sin serie"},
            {"type": "text", "text": problema_texto or "Sin descripción"},
        ],
    }

    auth = (os.getenv("PANEL_USERNAME", "admin"), os.getenv("PANEL_PASSWORD", ""))
    async with httpx.AsyncClient() as client:
        response = await client.post(gateway_url, json=payload, timeout=10, auth=auth)
        if response.status_code != 200:
            raise Exception(f"Gateway error {response.status_code}: {response.text}")

    return {"ok": True}


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")


# ── HTML pages ───────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return FileResponse("static/index.html")


@app.get("/puesto/{numero}")
async def page_puesto(numero: int):
    return FileResponse("static/puesto.html")


@app.get("/stock")
async def page_stock():
    return FileResponse("static/stock.html")


@app.get("/qrs")
async def page_qrs():
    return FileResponse("static/qrs.html")


@app.get("/tecnicos")
async def page_tecnicos():
    return FileResponse("static/tecnicos.html")


@app.get("/historial")
async def page_historial():
    return FileResponse("static/historial.html")


# ── API puestos ───────────────────────────────────────────────────────────────

@app.get("/api/puestos")
async def api_puestos():
    return await get_all_puestos()


@app.get("/api/puesto/{numero}")
async def api_get_puesto(numero: int):
    p = await get_puesto(numero)
    if not p:
        raise HTTPException(404, "Puesto no encontrado")
    return p


@app.post("/api/puesto/{numero}")
async def api_update_puesto(numero: int, data: dict):
    p = await get_puesto(numero)
    if not p:
        raise HTTPException(404, "Puesto no encontrado")

    updated = await update_puesto(numero, data)

    # Registrar cambios en historial si vienen técnico y cambios
    tecnico_id = data.get("tecnico_id")
    tecnico_nombre = data.get("tecnico_nombre", "Desconocido")
    cambios = data.get("cambios", [])
    if tecnico_id and cambios:
        for cambio in cambios:
            await add_historial(
                puesto_numero=numero,
                tecnico_id=tecnico_id,
                tecnico_nombre=tecnico_nombre,
                accion=cambio,
            )
        await manager.broadcast(
            json.dumps({"type": "historial_updated", "puesto_numero": numero})
        )

    await manager.broadcast(
        json.dumps({"type": "puesto_updated", "numero": numero, "data": updated})
    )
    return updated


@app.post("/api/puesto/{numero}/completar")
async def api_completar_puesto(numero: int, body: dict):
    """Marca la reparación como completada: envía WhatsApp y limpia el puesto."""
    p = await get_puesto(numero)
    if not p:
        raise HTTPException(404, "Puesto no encontrado")

    tecnico_id     = body.get("tecnico_id")
    tecnico_nombre = body.get("tecnico_nombre", "Desconocido")

    # 1. Intentar enviar WhatsApp — si falla, abortar sin tocar el puesto
    try:
        await send_whatsapp_notification(p, tecnico_nombre)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    # 2. Registrar en historial
    await add_historial(
        puesto_numero=numero,
        tecnico_id=tecnico_id,
        tecnico_nombre=tecnico_nombre,
        accion="Reparación completada — aviso WhatsApp enviado",
    )

    # 3. Limpiar el puesto (reset a valores vacíos)
    empty: dict = {}
    for k in ("nombre_cliente", "codigo_cliente", "delegacion", "fecha_entrada",
              "telefono", "nombre_equipo", "numero_serie", "codigo_barras",
              "descripcion_problema"):
        empty[k] = ""
    for k in ("es_comercial", "es_alquiler", "es_propiedad",
              "check_electrico", "check_botones", "check_no_enfria", "check_perdida_agua",
              "diag_frio_termostato", "diag_frio_condensador", "diag_frio_gas",
              "diag_elec_agitador", "diag_elec_cableria", "diag_elec_termostato",
              "diag_elec_compresor", "diag_elec_botonera",
              "diag_agua_pin_electrico", "diag_agua_banco_hielo",
              "diag_agua_bomba_laton", "diag_agua_condensador"):
        empty[k] = 0
    await update_puesto(numero, empty)

    # 4. Broadcast WebSocket
    await manager.broadcast(
        json.dumps({"type": "puesto_completado", "numero": numero})
    )

    return {"ok": True}


# ── API stock ─────────────────────────────────────────────────────────────────

@app.get("/api/stock")
async def api_get_stock():
    return await get_stock()


@app.post("/api/stock/{tipo}")
async def api_update_stock(tipo: str, body: dict):
    valid = {"sotobanco", "tres_aguas", "dos_aguas"}
    if tipo not in valid:
        raise HTTPException(400, "Tipo inválido")
    preparada = bool(body.get("preparada", False))
    updated = await update_stock(tipo, preparada)
    msg = json.dumps({"type": "stock_updated", "data": updated})
    await manager.broadcast(msg)
    return updated


# ── API auth ──────────────────────────────────────────────────────────────────

@app.post("/api/auth/admin")
async def api_auth_admin(body: dict):
    admin_pin = os.environ.get("ADMIN_PIN", "0000")
    pin = str(body.get("pin", "")).strip()
    if pin == admin_pin:
        return {"ok": True}
    return {"ok": False}


@app.post("/api/auth/pin")
async def api_auth_pin(body: dict):
    pin = str(body.get("pin", "")).strip()
    tecnico = await get_tecnico_by_pin(pin)
    if tecnico:
        return {"ok": True, "tecnico": {"id": tecnico["id"], "nombre": tecnico["nombre"]}}
    return {"ok": False}


# ── API técnicos ──────────────────────────────────────────────────────────────

@app.get("/api/tecnicos")
async def api_get_tecnicos():
    return await get_all_tecnicos()


@app.post("/api/tecnicos")
async def api_create_tecnico(body: dict):
    nombre = str(body.get("nombre", "")).strip()
    pin = str(body.get("pin", "")).strip()
    if not nombre:
        raise HTTPException(400, "El nombre es obligatorio")
    if not pin.isdigit() or len(pin) != 4:
        raise HTTPException(400, "El PIN debe ser exactamente 4 dígitos numéricos")
    existing = await get_tecnico_by_pin(pin)
    if existing:
        raise HTTPException(409, "Este PIN ya está en uso")
    return await create_tecnico(nombre, pin)


@app.put("/api/tecnicos/{id}")
async def api_update_tecnico(id: int, body: dict):
    nombre = str(body.get("nombre", "")).strip()
    pin = str(body.get("pin", "")).strip()
    activo = bool(body.get("activo", True))
    if not nombre:
        raise HTTPException(400, "El nombre es obligatorio")
    if not pin.isdigit() or len(pin) != 4:
        raise HTTPException(400, "El PIN debe ser exactamente 4 dígitos numéricos")
    result = await update_tecnico(id, nombre, pin, activo)
    if not result:
        raise HTTPException(404, "Técnico no encontrado")
    return result


@app.delete("/api/tecnicos/{id}")
async def api_delete_tecnico(id: int):
    return await delete_tecnico(id)


# ── API historial ─────────────────────────────────────────────────────────────

@app.post("/api/historial")
async def api_add_historial(body: dict):
    await add_historial(
        puesto_numero=body.get("puesto_numero"),
        tecnico_id=body.get("tecnico_id"),
        tecnico_nombre=body.get("tecnico_nombre", ""),
        accion=body.get("accion", ""),
        campo=body.get("campo"),
        valor_nuevo=body.get("valor_nuevo"),
    )
    await manager.broadcast(
        json.dumps({"type": "historial_updated", "puesto_numero": body.get("puesto_numero")})
    )
    return {"ok": True}


@app.get("/api/historial/puesto/{numero}")
async def api_historial_puesto(numero: int):
    return await get_historial_puesto(numero)


@app.get("/api/historial")
async def api_historial_all():
    return await get_historial_all()


# ── WebSocket ─────────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception:
        manager.disconnect(ws)
