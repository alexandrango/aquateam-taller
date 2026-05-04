import json
import os
from contextlib import asynccontextmanager
from typing import List

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
