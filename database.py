import aiosqlite
import os
from datetime import datetime, timezone

# La ruta de la base de datos se lee de la variable de entorno DB_PATH.
# En Railway: crea un volumen, móntalo en /data y añade DB_PATH=/data/taller.db
# como variable de entorno en el servicio. Sin volumen los datos se pierden al redeploy.
DB_PATH = os.environ.get("DB_PATH", "./taller.db")


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS puestos (
                id INTEGER PRIMARY KEY,
                numero INTEGER UNIQUE,
                nombre_cliente TEXT DEFAULT '',
                es_comercial BOOLEAN DEFAULT 0,
                delegacion TEXT DEFAULT '',
                fecha_entrada TEXT DEFAULT '',
                telefono TEXT DEFAULT '',
                nombre_equipo TEXT DEFAULT '',
                numero_serie TEXT DEFAULT '',
                codigo_barras TEXT DEFAULT '',
                descripcion_problema TEXT DEFAULT '',
                check_electrico BOOLEAN DEFAULT 0,
                check_botones BOOLEAN DEFAULT 0,
                check_no_enfria BOOLEAN DEFAULT 0,
                check_perdida_agua BOOLEAN DEFAULT 0,
                diag_frio_termostato BOOLEAN DEFAULT 0,
                diag_frio_condensador BOOLEAN DEFAULT 0,
                diag_frio_gas BOOLEAN DEFAULT 0,
                diag_elec_agitador BOOLEAN DEFAULT 0,
                diag_elec_cableria BOOLEAN DEFAULT 0,
                diag_elec_termostato BOOLEAN DEFAULT 0,
                diag_elec_compresor BOOLEAN DEFAULT 0,
                diag_elec_botonera BOOLEAN DEFAULT 0,
                diag_agua_pin_electrico BOOLEAN DEFAULT 0,
                diag_agua_banco_hielo BOOLEAN DEFAULT 0,
                diag_agua_bomba_laton BOOLEAN DEFAULT 0,
                diag_agua_condensador BOOLEAN DEFAULT 0,
                updated_at TEXT DEFAULT ''
            )
        """)
        for numero in range(4, 21):
            await db.execute(
                "INSERT OR IGNORE INTO puestos (numero) VALUES (?)",
                (numero,)
            )

        await db.execute("""
            CREATE TABLE IF NOT EXISTS stock_guardias (
                id INTEGER PRIMARY KEY,
                tipo TEXT UNIQUE,
                preparada BOOLEAN DEFAULT 0,
                updated_at TEXT DEFAULT ''
            )
        """)
        for tipo in ("sotobanco", "tres_aguas", "dos_aguas"):
            await db.execute(
                "INSERT OR IGNORE INTO stock_guardias (tipo, preparada) VALUES (?, 0)",
                (tipo,)
            )

        await db.execute("""
            CREATE TABLE IF NOT EXISTS tecnicos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                pin TEXT NOT NULL UNIQUE,
                activo BOOLEAN DEFAULT 1,
                created_at TEXT
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS historial (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                puesto_numero INTEGER,
                tecnico_id INTEGER,
                tecnico_nombre TEXT,
                accion TEXT,
                campo TEXT,
                valor_nuevo TEXT,
                timestamp TEXT
            )
        """)

        # Migración: añadir es_alquiler si no existe (tabla ya creada en producción)
        try:
            await db.execute("ALTER TABLE puestos ADD COLUMN es_alquiler BOOLEAN DEFAULT 0")
        except Exception:
            pass  # La columna ya existe

        try:
            await db.execute("ALTER TABLE puestos ADD COLUMN es_propiedad BOOLEAN DEFAULT 0")
        except Exception:
            pass  # La columna ya existe

        try:
            await db.execute("ALTER TABLE puestos ADD COLUMN codigo_cliente TEXT DEFAULT ''")
        except Exception:
            pass  # La columna ya existe

        await db.commit()


def _now():
    return datetime.now(timezone.utc).isoformat()


# ── Puestos ──────────────────────────────────────────────────────────────────

async def get_all_puestos():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM puestos ORDER BY numero") as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def get_puesto(numero: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM puestos WHERE numero = ?", (numero,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def update_puesto(numero: int, data: dict):
    allowed = {
        "nombre_cliente", "codigo_cliente", "es_comercial", "es_alquiler", "es_propiedad", "delegacion", "fecha_entrada",
        "telefono", "nombre_equipo", "numero_serie", "codigo_barras",
        "descripcion_problema", "check_electrico", "check_botones",
        "check_no_enfria", "check_perdida_agua", "diag_frio_termostato",
        "diag_frio_condensador", "diag_frio_gas", "diag_elec_agitador",
        "diag_elec_cableria", "diag_elec_termostato", "diag_elec_compresor",
        "diag_elec_botonera", "diag_agua_pin_electrico", "diag_agua_banco_hielo",
        "diag_agua_bomba_laton", "diag_agua_condensador",
    }
    fields = {k: v for k, v in data.items() if k in allowed}
    if not fields:
        return await get_puesto(numero)

    fields["updated_at"] = _now()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [numero]

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"UPDATE puestos SET {set_clause} WHERE numero = ?", values
        )
        await db.commit()

    return await get_puesto(numero)


# ── Stock ─────────────────────────────────────────────────────────────────────

async def get_stock():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM stock_guardias ORDER BY id") as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def update_stock(tipo: str, preparada: bool):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE stock_guardias SET preparada = ?, updated_at = ? WHERE tipo = ?",
            (1 if preparada else 0, _now(), tipo)
        )
        await db.commit()
    return await get_stock()


# ── Técnicos ──────────────────────────────────────────────────────────────────

async def get_all_tecnicos():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM tecnicos ORDER BY nombre") as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def get_tecnico_by_pin(pin: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM tecnicos WHERE pin = ? AND activo = 1", (pin,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def create_tecnico(nombre: str, pin: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO tecnicos (nombre, pin, activo, created_at) VALUES (?, ?, 1, ?)",
            (nombre, pin, _now())
        )
        await db.commit()
        async with db.execute("SELECT last_insert_rowid()") as cur:
            row = await cur.fetchone()
            rowid = row[0]
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM tecnicos WHERE id = ?", (rowid,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def update_tecnico(id: int, nombre: str, pin: str, activo: bool):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE tecnicos SET nombre = ?, pin = ?, activo = ? WHERE id = ?",
            (nombre, pin, 1 if activo else 0, id)
        )
        await db.commit()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM tecnicos WHERE id = ?", (id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def delete_tecnico(id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM historial WHERE tecnico_id = ?", (id,)
        ) as cur:
            row = await cur.fetchone()
            tiene_historial = row[0] > 0

        if tiene_historial:
            await db.execute("UPDATE tecnicos SET activo = 0 WHERE id = ?", (id,))
        else:
            await db.execute("DELETE FROM tecnicos WHERE id = ?", (id,))
        await db.commit()
    return {"ok": True, "desactivado": tiene_historial}


# ── Historial ─────────────────────────────────────────────────────────────────

async def add_historial(
    puesto_numero: int,
    tecnico_id: int,
    tecnico_nombre: str,
    accion: str,
    campo: str = None,
    valor_nuevo: str = None,
):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO historial
               (puesto_numero, tecnico_id, tecnico_nombre, accion, campo, valor_nuevo, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (puesto_numero, tecnico_id, tecnico_nombre, accion, campo, valor_nuevo, _now())
        )
        await db.commit()


async def get_historial_puesto(puesto_numero: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM historial WHERE puesto_numero = ? ORDER BY timestamp DESC",
            (puesto_numero,)
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def get_historial_all():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM historial ORDER BY timestamp DESC LIMIT 1000"
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]
