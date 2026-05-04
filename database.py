import aiosqlite
from datetime import datetime, timezone

DB_PATH = "taller.db"


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

        await db.commit()


def _now():
    return datetime.now(timezone.utc).isoformat()


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
        "nombre_cliente", "es_comercial", "delegacion", "fecha_entrada",
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
