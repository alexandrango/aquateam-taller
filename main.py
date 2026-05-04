import json
from contextlib import asynccontextmanager
from typing import List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from database import init_db, get_all_puestos, get_puesto, update_puesto, get_stock, update_stock


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


# ── HTML pages ──────────────────────────────────────────────────────────────

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


# ── API puestos ──────────────────────────────────────────────────────────────

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
    msg = json.dumps({"type": "puesto_updated", "numero": numero, "data": updated})
    await manager.broadcast(msg)
    return updated


# ── API stock ────────────────────────────────────────────────────────────────

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


# ── WebSocket ────────────────────────────────────────────────────────────────

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
