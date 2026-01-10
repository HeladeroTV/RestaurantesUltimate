# === BACKEND.PY ===
# Backend API para el sistema de restaurante con integración de FastAPI y PostgreSQL.

from fastapi import FastAPI, HTTPException, Depends, Query
from pydantic import BaseModel
from typing import List, Optional
import psycopg2
from psycopg2.extras import RealDictCursor
import json
from datetime import datetime, date, timedelta
import subprocess
import os
import shutil
import glob
import logging  # ← AÑADIDO
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from pathlib import Path
from fastapi import WebSocket, WebSocketDisconnect
from typing import List
import asyncio

# Crear carpeta de logs si no existe
LOGS_DIR = Path("logs")
LOGS_DIR.mkdir(exist_ok=True)

# Logger principal
log = logging.getLogger("RestaurantIA")
log.setLevel(logging.DEBUG)  # Nivel más bajo para capturar todo

# Evitar duplicados si ya tiene handlers (importante en hot-reload de uvicorn)
if log.handlers:
    log.handlers.clear()

# Formato bonito y completo
formatter = logging.Formatter(
    fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

# === HANDLER 1: Consola con colores (solo en desarrollo) ===
try:
    from colorlog import ColoredFormatter
    console_formatter = ColoredFormatter(
        "%(log_color)s%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s",
        datefmt="%H:%M:%S",
        log_colors={
            'DEBUG':    'cyan',
            'INFO':     'green',
            'WARNING':  'yellow',
            'ERROR':    'red',
            'CRITICAL': 'red,bg_white',
        }
    )
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(console_formatter)
    console_handler.setLevel(logging.DEBUG)
    log.addHandler(console_handler)
except ImportError:
    # Si no tiene colorlog instalado, usa formato normal
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.DEBUG)
    log.addHandler(console_handler)

# === HANDLER 2: Archivo general (rotación diaria, guarda 30 días) ===
daily_handler = TimedRotatingFileHandler(
    LOGS_DIR / "restaurantia.log",
    when="midnight",
    interval=1,
    backupCount=30,
    encoding="utf-8"
)
daily_handler.setFormatter(formatter)
daily_handler.setLevel(logging.INFO)  # Info y superior
log.addHandler(daily_handler)

# === HANDLER 3: Archivo solo de errores (rotación por tamaño, máx 5MB cada uno) ===
error_handler = RotatingFileHandler(
    LOGS_DIR / "errores_criticos.log",
    maxBytes=5_000_000,  # 5 MB
    backupCount=10,
    encoding="utf-8"
)
error_handler.setLevel(logging.WARNING)  # Warning, Error y Critical
error_handler.setFormatter(formatter)
log.addHandler(error_handler)

# Mensaje de inicio bonito
log.info("=" * 80)
log.info("     SISTEMA DE GESTIÓN RESTAURANTIA - LOGS INICIALIZADOS CORRECTAMENTE     ")
log.info("=" * 80)
# ============================================================================

# IMPORTAR LAS SUB-APPS
from inventario_backend import inventario_app
from configuraciones_backend import configuraciones_app
from recetas_backend import recetas_app
from backend_service import BackendService

app = FastAPI(title="RestaurantIA Backend")

# Montar sub-apps
app.mount("/inventario", inventario_app)
app.mount("/configuraciones", configuraciones_app)
app.mount("/recetas", recetas_app)

log.info("Backend FastAPI iniciando - RestaurantIA API v2")
log.info("Sub-apps montadas: /inventario | /configuraciones | /recetas")

# Configuración directa de PostgreSQL
DATABASE_URL = "dbname=restaurant_db user=postgres password=postgres host=localhost port=5432"
log.info(f"Conexión configurada → BD: restaurant_db | Host: localhost:5432")

@app.get("/")
def read_root():
    log.debug("GET / → Página de bienvenida solicitada")
    return {"message": "Bienvenido a la API del Sistema de Restaurante"}


async def broadcast_alerta(tipo: str, data: dict):
    """
    Función para enviar alertas en tiempo real.
    Por ahora solo registra en logs, en el futuro usará WebSockets.
    """
    log.warning(f"🚨 ALERTA [{tipo.upper()}] → {data}")
    # Aquí irá tu lógica de WebSocket cuando la implementes
    # Ejemplo: await manager.broadcast(json.dumps({"tipo": tipo, "data": data}))

def get_db():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    log.debug("Nueva conexión a BD abierta (dependency get_db)")
    try:
        yield conn
    finally:
        conn.close()
        log.debug("Conexión a BD cerrada correctamente")

# ====================== MODELOS PYDANTIC ======================
class ItemMenu(BaseModel):
    nombre: str
    precio: float
    tipo: str

class PedidoCreate(BaseModel):
    mesa_numero: int
    items: List[dict]
    estado: str = "Pendiente"
    notas: str = ""

class PedidoResponse(BaseModel):
    id: int
    mesa_numero: int
    items: List[dict]
    estado: str
    fecha_hora: str
    numero_app: Optional[int] = None
    notas: str = ""

class ClienteCreate(BaseModel):
    nombre: str
    domicilio: str
    celular: str

class ClienteResponse(BaseModel):
    id: int
    nombre: str
    domicilio: str
    celular: str
    fecha_registro: str
    
class ReservaCreate(BaseModel):
    mesa_numero: int
    cliente_id: int
    fecha_hora_inicio: str
    fecha_hora_fin: Optional[str] = None

class BackupResponse(BaseModel):
    status: str
    message: str
    file_path: str

log.info("Modelos Pydantic cargados correctamente")
log.info("Backend 100% listo - Esperando peticiones en http://localhost:8000")
log.info("=" * 70)
# =================================================================

# Endpoints
@app.get("/health")
def health():
    log.debug("GET /health - Health check solicitado")
    try:
        conn = psycopg2.connect(DATABASE_URL)
        conn.close()
        log.info("Health check OK - Base de datos conectada correctamente")
        return {"status": "ok", "database": "connected"}
    except Exception as e:
        log.error(f"Health check FALLÓ - No se pudo conectar a la BD: {e}")
        return {"status": "error", "database": str(e)}

@app.get("/menu/items", response_model=List[ItemMenu])
def obtener_menu(conn: psycopg2.extensions.connection = Depends(get_db)):
    log.debug("GET /menu/items - Solicitando menú completo")
    with conn.cursor() as cursor:
        cursor.execute("SELECT nombre, precio, tipo FROM menu ORDER BY tipo, nombre")
        items = cursor.fetchall()
        log.info(f"Menú enviado al cliente - {len(items)} ítems disponibles")
        return items


@app.post("/pedidos", response_model=PedidoResponse)
async def crear_pedido(pedido: PedidoCreate, conn: psycopg2.extensions.connection = Depends(get_db)):
    total_items = len(pedido.items)
    mesa = pedido.mesa_numero
    es_digital = mesa == 99
    log.info(f"POST /pedidos → {'Digital' if es_digital else f'Mesa {mesa}'} | {total_items} ítems | Notas: '{pedido.notas.strip()[:40]}...'")

    with conn.cursor() as cursor:
        # --- VERIFICACIÓN Y CONSUMO DE STOCK ---
        items_agrupados = {}
        for item in pedido.items:
            nombre_item = item['nombre']
            items_agrupados[nombre_item] = items_agrupados.get(nombre_item, 0) + 1

        ingredientes_a_consumir = []
        
        for nombre_item, cantidad_pedido in items_agrupados.items():
            cursor.execute("SELECT r.id FROM recetas r WHERE r.nombre_plato = %s", (nombre_item,))
            receta = cursor.fetchone()
            
            if receta:
                cursor.execute("""
                    SELECT ir.ingrediente_id, ir.cantidad_necesaria, i.cantidad_disponible, i.nombre as nombre_ingrediente
                    FROM ingredientes_recetas ir
                    JOIN inventario i ON ir.ingrediente_id = i.id
                    WHERE ir.receta_id = %s
                """, (receta['id'],))
                
                for ing in cursor.fetchall():
                    cantidad_total_necesaria = float(ing['cantidad_necesaria']) * cantidad_pedido
                    cantidad_actual = float(ing['cantidad_disponible'])
                    
                    # ← AQUÍ ESTABA EL PROBLEMA: Ahora usa <= para permitir llegar a 0
                    if cantidad_actual < cantidad_total_necesaria:
                        log.warning(f"STOCK INSUFICIENTE → '{ing['nombre_ingrediente']}' | Disp: {cantidad_actual} | Necesario: {cantidad_total_necesaria} → Pedido RECHAZADO")
                        raise HTTPException(
                            status_code=400, 
                            detail=f"No hay suficiente stock de '{ing['nombre_ingrediente']}' para preparar '{nombre_item}'. Disponible: {cantidad_actual}, Necesario: {cantidad_total_necesaria}"
                        )
                    
                    ingredientes_a_consumir.append({
                        "id": ing['ingrediente_id'],
                        "cantidad": cantidad_total_necesaria
                    })
                    log.debug(f"Stock verificado → {ing['nombre_ingrediente']} | -{cantidad_total_necesaria} unidades para {cantidad_pedido} × '{nombre_item}'")

        # --- GENERAR NÚMERO DE PEDIDO DIGITAL ---
        numero_app = None
        if pedido.mesa_numero == 99:
            cursor.execute("SELECT MAX(numero_app) FROM pedidos WHERE mesa_numero = 99")
            max_app = cursor.fetchone()
            numero_app = (max_app['max'] + 1) if max_app and max_app['max'] else 1
            log.debug(f"Pedido digital → Número asignado: {numero_app}")

        fecha_hora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        cursor.execute("""
            INSERT INTO pedidos (mesa_numero, numero_app, estado, fecha_hora, items, notas)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, mesa_numero, numero_app, estado, fecha_hora, items, notas
        """, (
            pedido.mesa_numero,
            numero_app,
            pedido.estado,
            fecha_hora,
            json.dumps(pedido.items),
            pedido.notas
        ))
        
        result = cursor.fetchone()
        pedido_id_nuevo = result['id']

        # === CONSUMIR STOCK + ALERTA DE STOCK BAJO EN TIEMPO REAL ===
        for consumo in ingredientes_a_consumir:
            cursor.execute("""
                UPDATE inventario 
                SET cantidad_disponible = cantidad_disponible - %s,
                    fecha_actualizacion = CURRENT_TIMESTAMP
                WHERE id = %s
                RETURNING nombre, cantidad_disponible, cantidad_minima_alerta, unidad_medida
            """, (consumo['cantidad'], consumo['id']))
            
            ing = cursor.fetchone()
            if ing:
                nombre_ing = ing['nombre']
                disponible = float(ing['cantidad_disponible'])
                minimo_alerta = float(ing['cantidad_minima_alerta'])
                unidad = ing['unidad_medida'] or "unidades"

                log.debug(f"Stock actualizado → {nombre_ing} | Quedan: {disponible} {unidad}")

                # ENVIAR ALERTA SI ESTÁ BAJO O CRÍTICO (AHORA ASYNC)
                if disponible <= minimo_alerta:
                    alerta = {
                        "ingrediente": nombre_ing,
                        "disponible": round(disponible, 2),
                        "minimo": minimo_alerta,
                        "unidad": unidad,
                        "mensaje": f"¡Stock crítico de {nombre_ing}! Solo quedan {disponible} {unidad}"
                    }
                    # ← LÍNEA CORREGIDA: Ahora usa await en vez de create_task
                    await broadcast_alerta("stock_bajo", alerta)
                    log.warning(f"ALERTA STOCK BAJO ENVIADA → {nombre_ing} ({disponible} ≤ {minimo_alerta})")

        conn.commit()
        
        fecha_hora_str = result['fecha_hora'].strftime("%Y-%m-%d %H:%M:%S") if isinstance(result['fecha_hora'], datetime) else result['fecha_hora']
        
        log.info(f"PEDIDO CREADO CON ÉXITO → ID: {pedido_id_nuevo} | {'Digital' if es_digital else f'Mesa {mesa}'} | {total_items} ítems | {len(ingredientes_a_consumir)} ingredientes consumidos")

        return {
            "id": pedido_id_nuevo,
            "mesa_numero": result['mesa_numero'],
            "items": result['items'],
            "estado": result['estado'],
            "fecha_hora": fecha_hora_str,
            "numero_app": result['numero_app'],
            "notas": result['notas']
        }

@app.get("/pedidos/activos", response_model=List[PedidoResponse])
def obtener_pedidos_activos(conn: psycopg2.extensions.connection = Depends(get_db)):
    log.debug("GET /pedidos/activos - Solicitando pedidos en cocina")
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT id, mesa_numero, numero_app, estado, fecha_hora, items, notas 
            FROM pedidos 
            WHERE estado IN ('Pendiente', 'En preparacion', 'Listo')
            ORDER BY fecha_hora DESC
        """)
        rows = cursor.fetchall()
        pedidos = []
        for row in rows:
            fecha_hora_str = row['fecha_hora'].strftime("%Y-%m-%d %H:%M:%S") if isinstance(row['fecha_hora'], datetime) else row['fecha_hora']
            pedidos.append({
                "id": row['id'],
                "mesa_numero": row['mesa_numero'],
                "numero_app": row['numero_app'],
                "estado": row['estado'],
                "fecha_hora": fecha_hora_str,
                "items": row['items'],
                "notas": row['notas']
            })
        log.info(f"{len(pedidos)} pedidos activos enviados a cocina → {', '.join([str(p['id']) for p in pedidos[:5]])}{'...' if len(pedidos)>5 else ''}")
        return pedidos

# --- MODIFICACIÓN EN EL ENDPOINT DE ACTUALIZACIÓN DE ESTADO ---
@app.patch("/pedidos/{pedido_id}/estado")
def actualizar_estado_pedido(pedido_id: int, estado: str, conn = Depends(get_db)):
    log.info(f"PATCH /pedidos/{pedido_id}/estado → Cambiando a '{estado}'")

    with conn.cursor() as cursor:
        # Verificar si el pedido existe
        cursor.execute("SELECT estado, hora_inicio_cocina, hora_fin_cocina FROM pedidos WHERE id = %s", (pedido_id,))
        pedido = cursor.fetchone()
        if not pedido:
            log.warning(f"Intento de actualizar estado → Pedido {pedido_id} NO ENCONTRADO")
            raise HTTPException(status_code=404, detail="Pedido no encontrado")

        estado_anterior = pedido['estado']
        log.debug(f"Pedido {pedido_id} encontrado | Estado actual: '{estado_anterior}' → '{estado}'")

        # --- LÓGICA PARA REGISTRAR MARCAS DE TIEMPO ---
        now = datetime.now()
        extra_update = ""
        extra_values = []

        if estado == "En preparacion" and pedido['hora_inicio_cocina'] is None:
            extra_update = ", hora_inicio_cocina = %s"
            extra_values.append(now)
            log.info(f"Inicio de cocina registrado → Pedido {pedido_id} | {now.strftime('%H:%M:%S')}")
        elif estado == "Listo" and pedido['hora_inicio_cocina'] is not None and pedido['hora_fin_cocina'] is None:
            extra_update = ", hora_fin_cocina = %s"
            extra_values.append(now)
            log.info(f"Pedido {pedido_id} MARCADO COMO LISTO → Fin de cocina: {now.strftime('%H:%M:%S')}")

        # Actualizar el estado (y potencialmente las marcas de tiempo)
        update_query = f"UPDATE pedidos SET estado = %s {extra_update} WHERE id = %s RETURNING id, mesa_numero, cliente_id, estado, fecha_hora, items, numero_app, notas, updated_at, hora_inicio_cocina, hora_fin_cocina"
        cursor.execute(update_query, (estado, *extra_values, pedido_id))
        result = cursor.fetchone()

        if not result:
            raise HTTPException(status_code=404, detail="Pedido no encontrado")

        conn.commit()

        # Devolver el pedido actualizado
        pedido_dict = dict(result)
        
        # Calcular tiempo de cocina si aplica
        if pedido_dict['hora_inicio_cocina'] and pedido_dict['hora_fin_cocina']:
            tiempo_cocina = (pedido_dict['hora_fin_cocina'] - pedido_dict['hora_inicio_cocina']).total_seconds() / 60
            pedido_dict['tiempo_cocina_minutos'] = round(tiempo_cocina, 1)
            log.info(f"Pedido {pedido_id} listo en cocina → Tiempo total: {tiempo_cocina:.1f} minutos")
        elif pedido_dict['hora_inicio_cocina'] and estado == "Listo":
            tiempo_cocina = (now - pedido_dict['hora_inicio_cocina']).total_seconds() / 60
            pedido_dict['tiempo_cocina_minutos'] = round(tiempo_cocina, 1)
            log.info(f"Pedido {pedido_id} listo → Tiempo en cocina: {tiempo_cocina:.1f} minutos")

        log.info(f"ESTADO ACTUALIZADO CON ÉXITO → Pedido {pedido_id} | '{estado_anterior}' → '{estado}'")
        return pedido_dict
# --- FIN MODIFICACIÓN ---



# Endpoint para inicializar menú
@app.post("/menu/inicializar")
def inicializar_menu(conn: psycopg2.extensions.connection = Depends(get_db)):
    log.warning("POST /menu/inicializar → ¡¡REINICIANDO MENÚ COMPLETO!! (Se eliminarán todos los ítems actuales)")
    
    try:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM menu")
            log.info(f"Menú anterior eliminado ({cursor.rowcount} ítems borrados)")

            for nombre, precio, tipo in menu_inicial:
                cursor.execute("""
                    INSERT INTO menu (nombre, precio, tipo)
                    VALUES (%s, %s, %s)
                """, (nombre, precio, tipo))
            
            conn.commit()
            log.info(f"MENÚ INICIALIZADO CON ÉXITO → {len(menu_inicial)} ítems insertados correctamente")
            return {"status": "ok", "items_insertados": len(menu_inicial)}
            
    except Exception as e:
        conn.rollback()
        log.error(f"ERROR CRÍTICO al inicializar menú → {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error al inicializar menú: {str(e)}")

# ¡NUEVO ENDPOINT! → Eliminar último ítem de un pedido
@app.delete("/pedidos/{pedido_id}/ultimo_item")
def eliminar_ultimo_item(pedido_id: int, conn: psycopg2.extensions.connection = Depends(get_db)):
    log.info(f"DELETE /pedidos/{pedido_id}/ultimo_item → Eliminando último ítem del pedido")
    
    with conn.cursor() as cursor:
        cursor.execute("SELECT items FROM pedidos WHERE id = %s", (pedido_id,))
        row = cursor.fetchone()
        if not row:
            log.warning(f"Intento de eliminar ítem → Pedido {pedido_id} NO ENCONTRADO")
            raise HTTPException(status_code=404, detail="Pedido no encontrado")
        
        items = json.loads(row['items'])
        if not items:
            log.warning(f"Pedido {pedido_id} está vacío → No hay ítems para eliminar")
            raise HTTPException(status_code=400, detail="No hay ítems para eliminar")
        
        item_eliminado = items.pop()
        cursor.execute("UPDATE pedidos SET items = %s WHERE id = %s", (json.dumps(items), pedido_id))
        conn.commit()
        
        log.info(f"ÚLTIMO ÍTEM ELIMINADO → Pedido {pedido_id} | Eliminado: '{item_eliminado['nombre']}' | Quedan: {len(items)} ítems")
        return {"status": "ok", "message": f"Ítem '{item_eliminado['nombre']}' eliminado"}

# ¡NUEVOS ENDPOINTS! → Gestión completa de pedidos y menú

@app.put("/pedidos/{pedido_id}")
def actualizar_pedido(pedido_id: int, pedido_actualizado: PedidoCreate, conn: psycopg2.extensions.connection = Depends(get_db)):
    log.info(f"PUT /pedidos/{pedido_id} → Actualizando pedido completo | Mesa: {pedido_actualizado.mesa_numero} | {len(pedido_actualizado.items)} ítems")
    
    with conn.cursor() as cursor:
        cursor.execute("SELECT id FROM pedidos WHERE id = %s", (pedido_id,))
        if not cursor.fetchone():
            log.warning(f"Intento de actualizar → Pedido {pedido_id} NO ENCONTRADO")
            raise HTTPException(status_code=404, detail="Pedido no encontrado")
        
        fecha_hora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("""
            UPDATE pedidos 
            SET mesa_numero = %s, estado = %s, fecha_hora = %s, items = %s, notas = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (
            pedido_actualizado.mesa_numero,
            pedido_actualizado.estado,
            fecha_hora,
            json.dumps(pedido_actualizado.items),
            pedido_actualizado.notas,
            pedido_id
        ))
        
        conn.commit()
        log.info(f"PEDIDO {pedido_id} ACTUALIZADO CORRECTAMENTE → Estado: '{pedido_actualizado.estado}' | {len(pedido_actualizado.items)} ítems")
        return {"status": "ok", "message": "Pedido actualizado"}

@app.delete("/pedidos/{pedido_id}")
def eliminar_pedido(pedido_id: int, conn: psycopg2.extensions.connection = Depends(get_db)):
    log.warning(f"DELETE /pedidos/{pedido_id} → ¡¡¡ELIMINANDO PEDIDO COMPLETO!!!")
    
    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM pedidos WHERE id = %s", (pedido_id,))
        if cursor.rowcount == 0:
            log.warning(f"Intento de eliminar → Pedido {pedido_id} NO ENCONTRADO")
            raise HTTPException(status_code=404, detail="Pedido no encontrado")
        
        conn.commit()
        log.warning(f"PEDIDO {pedido_id} ELIMINADO POR COMPLETO DE LA BASE DE DATOS")
        return {"status": "ok", "message": "Pedido eliminado"}

@app.post("/menu/items")
def agregar_item_menu(item: ItemMenu, conn: psycopg2.extensions.connection = Depends(get_db)):
    log.info(f"POST /menu/items → Agregando nuevo ítem: '{item.nombre}' | ${item.precio} | {item.tipo}")
    
    with conn.cursor() as cursor:
        cursor.execute("""
            INSERT INTO menu (nombre, precio, tipo)
            VALUES (%s, %s, %s)
            RETURNING id
        """, (item.nombre, item.precio, item.tipo))
        item_id = cursor.fetchone()['id']
        conn.commit()
        
        log.info(f"ÍTEM AGREGADO AL MENÚ → ID: {item_id} | '{item.nombre}' | ${item.precio}")
        return {"status": "ok", "id": item_id, "message": "Ítem agregado al menú"}

@app.delete("/menu/items")
def eliminar_item_menu(nombre: str, tipo: str, conn: psycopg2.extensions.connection = Depends(get_db)):
    log.warning(f"DELETE /menu/items → Eliminando ítem: '{nombre}' ({tipo})")
    
    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM menu WHERE nombre = %s AND tipo = %s", (nombre, tipo))
        if cursor.rowcount == 0:
            log.warning(f"Ítem no encontrado → '{nombre}' ({tipo})")
            raise HTTPException(status_code=404, detail="Ítem no encontrado en el menú")
        
        conn.commit()
        log.info(f"ÍTEM ELIMINADO DEL MENÚ → '{nombre}' ({tipo})")
        return {"status": "ok", "message": "Ítem eliminado del menú"}

# NUEVOS ENDPOINTS PARA GESTIÓN DE CLIENTES

@app.get("/clientes", response_model=List[ClienteResponse])
def obtener_clientes(conn: psycopg2.extensions.connection = Depends(get_db)):
    log.debug("GET /clientes → Consultando lista de clientes registrados")
    
    with conn.cursor() as cursor:
        cursor.execute("SELECT id, nombre, domicilio, celular, fecha_registro FROM clientes ORDER BY nombre")
        clientes = []
        for row in cursor.fetchall():
            fecha_str = row['fecha_registro'].strftime("%Y-%m-%d %H:%M:%S") if isinstance(row['fecha_registro'], datetime) else row['fecha_registro']
            clientes.append({
                "id": row['id'],
                "nombre": row['nombre'],
                "domicilio": row['domicilio'],
                "celular": row['celular'],
                "fecha_registro": fecha_str
            })
        
        log.info(f"{len(clientes)} clientes enviados al frontend")
        return clientes

@app.post("/clientes", response_model=ClienteResponse)
def crear_cliente(cliente: ClienteCreate, conn: psycopg2.extensions.connection = Depends(get_db)):
    log.info(f"POST /clientes → Registrando nuevo cliente: {cliente.nombre} | {cliente.celular}")
    
    with conn.cursor() as cursor:
        fecha_registro = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("""
            INSERT INTO clientes (nombre, domicilio, celular)
            VALUES (%s, %s, %s)
            RETURNING id, nombre, domicilio, celular, fecha_registro
        """, (cliente.nombre, cliente.domicilio, cliente.celular))
        result = cursor.fetchone()
        conn.commit()
        
        fecha_str = result['fecha_registro'].strftime("%Y-%m-%d %H:%M:%S") if isinstance(result['fecha_registro'], datetime) else result['fecha_registro']
        
        log.info(f"CLIENTE REGISTRADO → ID: {result['id']} | {cliente.nombre} | {cliente.celular}")
        return {
            "id": result['id'],
            "nombre": result['nombre'],
            "domicilio": result['domicilio'],
            "celular": result['celular'],
            "fecha_registro": fecha_str
        }

@app.delete("/clientes/{cliente_id}")
def eliminar_cliente(cliente_id: int, conn: psycopg2.extensions.connection = Depends(get_db)):
    log.warning(f"DELETE /clientes/{cliente_id} → Eliminando cliente permanentemente")
    
    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM clientes WHERE id = %s", (cliente_id,))
        if cursor.rowcount == 0:
            log.warning(f"Cliente {cliente_id} no encontrado para eliminar")
            raise HTTPException(status_code=404, detail="Cliente no encontrado")
        
        conn.commit()
        log.warning(f"CLIENTE {cliente_id} ELIMINADO DE LA BASE DE DATOS")
        return {"status": "ok", "message": "Cliente eliminado"}
    
@app.get("/reportes")
def obtener_reporte(tipo: str, start_date: str, end_date: str, conn: psycopg2.extensions.connection = Depends(get_db)):
    log.info(f"GET /reportes → Generando reporte | Tipo: {tipo} | {start_date} → {end_date}")
    
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT items, estado, fecha_hora
            FROM pedidos
            WHERE fecha_hora >= %s AND fecha_hora < %s
            AND estado IN ('Listo', 'Entregado', 'Pagado')
        """, (start_date, end_date))
        
        pedidos = cursor.fetchall()
        
        ventas_totales = 0
        pedidos_totales = len(pedidos)
        productos_vendidos = 0
        productos_mas_vendidos = {}

        for pedido in pedidos:
            items = pedido['items']
            if isinstance(items, str):
                items = json.loads(items)
            
            for item in items:
                nombre = item['nombre']
                precio = item['precio']
                
                ventas_totales += precio
                productos_vendidos += 1
                
                productos_mas_vendidos[nombre] = productos_mas_vendidos.get(nombre, 0) + 1

        productos_mas_vendidos_lista = sorted(
            [{'nombre': k, 'cantidad': v} for k, v in productos_mas_vendidos.items()],
            key=lambda x: x['cantidad'],
            reverse=True
        )[:10]

        log.info(f"REPORTE GENERADO → Ventas: ${ventas_totales:,.2f} | Pedidos: {pedidos_totales} | Productos vendidos: {productos_vendidos}")
        return {
            "ventas_totales": round(ventas_totales, 2),
            "pedidos_totales": pedidos_totales,
            "productos_vendidos": productos_vendidos,
            "productos_mas_vendidos": productos_mas_vendidos_lista
        }
        

@app.get("/analisis/productos")
def obtener_analisis_productos(
    start_date: str = Query(None, description="Fecha de inicio (YYYY-MM-DD)"),
    end_date: str = Query(None, description="Fecha de fin (YYYY-MM-DD)"),
    conn: psycopg2.extensions.connection = Depends(get_db)
):
    """
    Obtiene el análisis de productos vendidos en un rango de fechas.
    """
    rango = f"{start_date or 'Inicio'} → {end_date or 'Hoy'}"
    log.info(f"GET /analisis/productos → Análisis de ventas | Rango: {rango}")

    # Construir la condición de fecha si se proporcionan parámetros
    fecha_condicion = ""
    params = []
    if start_date and end_date:
        fecha_condicion = "AND fecha_hora >= %s AND fecha_hora < %s"
        params = [start_date, end_date]
    elif start_date:
        fecha_condicion = "AND fecha_hora >= %s"
        params = [start_date]
    elif end_date:
        fecha_condicion = "AND fecha_hora < %s"
        params = [end_date]

    with conn.cursor() as cursor:
        cursor.execute(f"""
            SELECT items
            FROM pedidos
            WHERE estado IN ('Entregado', 'Pagado')
            {fecha_condicion}
        """, params)
        
        pedidos = cursor.fetchall()

    conteo_productos = {}
    for pedido in pedidos:
        items = pedido['items']
        if isinstance(items, str):
            items = json.loads(items)

        if isinstance(items, list):
            for item in items:
                nombre = item.get('nombre')
                if nombre:
                    conteo_productos[nombre] = conteo_productos.get(nombre, 0) + 1

    productos_ordenados = sorted(conteo_productos.items(), key=lambda x: x[1], reverse=True)
    top_10 = [{"nombre": k, "cantidad": v} for k, v in productos_ordenados[:10]]
    bottom_10 = [{"nombre": k, "cantidad": v} for k, v in productos_ordenados[-10:]]

    log.info(f"ANÁLISIS COMPLETADO → {len(conteo_productos)} productos distintos | Top: {top_10[0]['nombre'] if top_10 else 'N/A'} ({top_10[0]['cantidad'] if top_10 else 0} ventas)")

    return {
        "productos_mas_vendidos": top_10,
        "productos_menos_vendidos": bottom_10
    }


@app.get("/mesas")
def obtener_mesas(conn = Depends(get_db)):
    """
    Devuelve mesas con estado calculado dinámicamente desde pedidos activos.
    OPTIMIZADO: Usa una sola query JOIN para máximo rendimiento.
    """
    log.debug("GET /mesas → Consultando estado de mesas (con cálculo dinámico de ocupación)")

    try:
        with conn.cursor() as cursor:
            # === QUERY ULTRA-OPTIMIZADA CON LEFT JOIN ===
            cursor.execute("""
                SELECT 
                    m.numero,
                    m.capacidad,
                    -- Calcular si está ocupada (pedido activo)
                    CASE 
                        WHEN p.id IS NOT NULL THEN TRUE 
                        ELSE FALSE 
                    END AS ocupada,
                    -- Detectar si tiene reserva activa
                    CASE 
                        WHEN r.id IS NOT NULL THEN TRUE 
                        ELSE FALSE 
                    END AS reservada,
                    c.nombre AS cliente_reservado_nombre,
                    r.fecha_hora_inicio AS fecha_hora_reserva
                FROM mesas m
                -- Pedidos activos (determina ocupada)
                LEFT JOIN pedidos p ON m.numero = p.mesa_numero 
                    AND p.estado IN ('Tomando pedido', 'Pendiente', 'En preparacion', 'Listo', 'Entregado')
                -- Reservas activas
                LEFT JOIN reservas r ON m.numero = r.mesa_numero 
                    AND DATE(r.fecha_hora_inicio) >= CURRENT_DATE
                LEFT JOIN clientes c ON r.cliente_id = c.id
                WHERE m.numero != 99
                ORDER BY m.numero;
            """)
            mesas_db = cursor.fetchall()

        # Procesar resultados
        mesas_result = []
        ocupadas = 0
        reservadas = 0

        for mesa_row in mesas_db:
            es_ocupada = bool(mesa_row['ocupada'])
            es_reservada = bool(mesa_row['reservada'])
            
            if es_ocupada:
                ocupadas += 1
            if es_reservada:
                reservadas += 1

            mesas_result.append({
                "numero": mesa_row['numero'],
                "capacidad": mesa_row['capacidad'],
                "ocupada": es_ocupada,  # ← AHORA SÍ SE CALCULA CORRECTAMENTE
                "reservada": es_reservada,
                "cliente_reservado_nombre": mesa_row['cliente_reservado_nombre'],
                "fecha_hora_reserva": str(mesa_row['fecha_hora_reserva']) if mesa_row['fecha_hora_reserva'] else None
            })

        # Mesa virtual (siempre disponible)
        mesas_result.append({
            "numero": 99,
            "capacidad": 100,
            "ocupada": False,
            "reservada": False,
            "cliente_reservado_nombre": None,
            "fecha_hora_reserva": None,
            "es_virtual": True
        })

        log.info(f"Mesas enviadas → {len(mesas_db)} físicas | {ocupadas} ocupadas | {reservadas} reservadas | Actualización dinámica ✅")
        return mesas_result

    except Exception as e:
        log.error(f"ERROR CRÍTICO en obtener_mesas → {e}", exc_info=True)
        # Fallback seguro
        fallback = [
            {"numero": i, "capacidad": c, "ocupada": False, "reservada": False, "cliente_reservado_nombre": None, "fecha_hora_reserva": None}
            for i, c in [(1,2),(2,2),(3,4),(4,4),(5,6),(6,6)]
        ] + [{"numero": 99, "capacidad": 100, "ocupada": False, "reservada": False, "cliente_reservado_nombre": None, "fecha_hora_reserva": None, "es_virtual": True}]
        log.warning("Devolviendo fallback por error en BD")
        return fallback


@app.get("/mesas/disponibles/")
def obtener_mesas_disponibles_para_fecha_hora(
    fecha_hora_str: str = Query(..., description="Fecha y hora en formato YYYY-MM-DD HH:MM:SS"),
    conn = Depends(get_db)
):
    log.info(f"GET /mesas/disponibles → Buscando mesas libres para {fecha_hora_str}")

    try:
        fecha_hora_obj = datetime.strptime(fecha_hora_str, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        log.warning(f"Formato de fecha inválido recibido: {fecha_hora_str}")
        raise HTTPException(status_code=400, detail="Formato de fecha/hora inválido. Use YYYY-MM-DD HH:MM:SS")

    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT numero, capacidad FROM mesas WHERE numero != 99;")
            mesas_db = cursor.fetchall()

        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT DISTINCT mesa_numero
                FROM pedidos
                WHERE estado IN ('Tomando pedido', 'Pendiente', 'En preparacion', 'Listo', 'Entregado')
                AND mesa_numero != 99;
            """)
            ocupadas_db = {row['mesa_numero'] for row in cursor.fetchall()}

        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT DISTINCT mesa_numero
                FROM reservas
                WHERE %s BETWEEN fecha_hora_inicio AND COALESCE(fecha_hora_fin, fecha_hora_inicio + INTERVAL '1 hour');
            """, (fecha_hora_obj,))
            reservadas_db = {row['mesa_numero'] for row in cursor.fetchall()}
        
        disponibles = [
            {"numero": m['numero'], "capacidad": m['capacidad']}
            for m in mesas_db
            if m['numero'] not in ocupadas_db and m['numero'] not in reservadas_db
        ]

        log.info(f"{len(disponibles)} mesas disponibles para {fecha_hora_str}")
        return disponibles

    except Exception as e:
        log.error(f"ERROR en obtener_mesas_disponibles → {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# --- ENDPOINT DE RESPALDO (BACKUP) ---
def find_pg_dump():
    path_in_path = shutil.which("pg_dump")
    if path_in_path:
        log.debug(f"pg_dump encontrado en PATH: {path_in_path}")
        return path_in_path
    
    possible_paths = glob.glob("C:/Program Files/PostgreSQL/*/bin/pg_dump.exe")
    if possible_paths:
        possible_paths.sort()
        elegido = possible_paths[-1]
        log.debug(f"pg_dump encontrado en instalación: {elegido}")
        return elegido
    
    log.error("pg_dump NO ENCONTRADO en el sistema")
    return None


@app.post("/backup", response_model=BackupResponse)
def crear_respaldo():
    log.warning("POST /backup → INICIANDO RESPALDO COMPLETO DE LA BASE DE DATOS")

    try:
        pg_dump_exe = find_pg_dump()
        if not pg_dump_exe:
            log.error("No se encontró pg_dump → Respaldo cancelado")
            raise HTTPException(status_code=500, detail="pg_dump no encontrado en el sistema")

        desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
        backup_dir = os.path.join(desktop_path, "Backups_RestaurantPRO")
        os.makedirs(backup_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"backup_restaurant_db_{timestamp}.sql"
        filepath = os.path.join(backup_dir, filename)
        
        env = os.environ.copy()
        env["PGPASSWORD"] = "postgres"
        
        command = [
            pg_dump_exe, "-U", "postgres", "-h", "localhost", "-p", "5432",
            "-d", "restaurant_db", "-f", filepath
        ]
        
        log.info(f"Ejecutando pg_dump → {filepath}")
        result = subprocess.run(command, env=env, capture_output=True, text=True)
        
        if result.returncode == 0:
            log.info(f"RESPALDO COMPLETADO CON ÉXITO → {filepath} ({os.path.getsize(filepath) / 1024 / 1024:.1f} MB)")
            return {"status": "ok", "message": "Respaldo creado exitosamente.", "file_path": filepath}
        else:
            log.error(f"pg_dump FALLÓ → {result.stderr}")
            raise HTTPException(status_code=500, detail=result.stderr)
            
    except Exception as e:
        log.error(f"ERROR GENERAL EN BACKUP → {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error creando respaldo: {str(e)}")

@app.post("/backup", response_model=BackupResponse)
def crear_respaldo():
    """
    Crea un respaldo de la base de datos PostgreSQL usando pg_dump.
    """
    log.warning("POST /backup → ¡¡¡INICIANDO RESPALDO COMPLETO DE LA BASE DE DATOS!!!")

    try:
        pg_dump_exe = find_pg_dump()
        if not pg_dump_exe:
            log.error("pg_dump NO ENCONTRADO → Respaldo abortado")
            raise HTTPException(status_code=500, detail="No se encontró pg_dump. Instala PostgreSQL o agrégalo al PATH.")

        desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
        backup_dir = os.path.join(desktop_path, "Backups_RestaurantPRO")
        os.makedirs(backup_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"backup_restaurant_db_{timestamp}.sql"
        filepath = os.path.join(backup_dir, filename)
        
        env = os.environ.copy()
        env["PGPASSWORD"] = "postgres"
        
        command = [
            pg_dump_exe, "-U", "postgres", "-h", "localhost", "-p", "5432",
            "-d", "restaurant_db", "-f", filepath
        ]
        
        log.info(f"Ejecutando pg_dump → Guardando en: {filepath}")
        result = subprocess.run(command, env=env, capture_output=True, text=True)
        
        if result.returncode == 0:
            tamaño_mb = os.path.getsize(filepath) / (1024 * 1024)
            log.info(f"RESPALDO COMPLETADO CON ÉXITO → {filepath} | {tamaño_mb:.2f} MB")
            return {"status": "ok", "message": "Respaldo creado exitosamente.", "file_path": filepath}
        else:
            log.error(f"pg_dump FALLÓ → Código: {result.returncode} | Error: {result.stderr.strip()}")
            raise HTTPException(status_code=500, detail=f"Error al ejecutar pg_dump: {result.stderr}")

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"ERROR GENERAL EN RESPALDO → {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error creando respaldo: {str(e)}")


# (Este código estaba mal indentado en tu mensaje, lo corrijo y agrego logs)
@app.get("/mesas/disponibles/")
def obtener_mesas_disponibles_para_fecha_hora(
    fecha_hora_str: str = Query(..., description="Fecha y hora en formato YYYY-MM-DD HH:MM:SS"),
    conn = Depends(get_db)
):
    log.info(f"GET /mesas/disponibles → Buscando mesas libres para: {fecha_hora_str}")

    try:
        fecha_hora_obj = datetime.strptime(fecha_hora_str, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        log.warning(f"Formato inválido de fecha recibido → {fecha_hora_str}")
        raise HTTPException(status_code=400, detail="Formato de fecha/hora inválido. Use YYYY-MM-DD HH:MM:SS")

    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT numero, capacidad FROM mesas WHERE numero != 99;")
            mesas_db = cursor.fetchall()

        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT DISTINCT mesa_numero FROM pedidos
                WHERE estado IN ('Tomando pedido', 'Pendiente', 'En preparacion', 'Listo', 'Entregado')
                AND mesa_numero != 99;
            """)
            ocupadas_db = {row['mesa_numero'] for row in cursor.fetchall()}

        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT DISTINCT mesa_numero FROM reservas
                WHERE %s BETWEEN fecha_hora_inicio AND COALESCE(fecha_hora_fin, fecha_hora_inicio + INTERVAL '1 hour');
            """, (fecha_hora_obj,))
            reservadas_db = {row['mesa_numero'] for row in cursor.fetchall()}
        
        mesas_disponibles = [
            {"numero": m['numero'], "capacidad": m['capacidad']}
            for m in mesas_db
            if m['numero'] not in ocupadas_db and m['numero'] not in reservadas_db
        ]

        log.info(f"{len(mesas_disponibles)} mesas disponibles para {fecha_hora_str} → {', '.join([str(m['numero']) for m in mesas_disponibles]) or 'Ninguna'}")
        return mesas_disponibles

    except Exception as e:
        log.error(f"ERROR en obtener_mesas_disponibles_para_fecha_hora → {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error interno del servidor al consultar disponibilidad.")


class ReservaCreate(BaseModel):
    mesa_numero: int
    cliente_id: int
    fecha_hora_inicio: str
    fecha_hora_fin: Optional[str] = None

class ReservaUpdate(BaseModel):
    mesa_numero: Optional[int] = None
    cliente_id: Optional[int] = None
    fecha_hora_inicio: Optional[str] = None
    fecha_hora_fin: Optional[str] = None


@app.get("/reservas/")
def obtener_reservas(
    fecha: Optional[str] = Query(None, description="Fecha en formato YYYY-MM-DD para filtrar"),
    conn = Depends(get_db)
):
    filtro = f" para {fecha}" if fecha else " (todas)"
    log.info(f"GET /reservas → Obteniendo reservas{filtro}")

    try:
        query = """
            SELECT r.id, r.mesa_numero, r.cliente_id, c.nombre as cliente_nombre, r.fecha_hora_inicio, r.fecha_hora_fin
            FROM reservas r
            JOIN clientes c ON r.cliente_id = c.id
        """
        params = []
        if fecha:
            query += " WHERE DATE(r.fecha_hora_inicio) = %s"
            params.append(fecha)
        query += " ORDER BY r.fecha_hora_inicio;"

        with conn.cursor() as cursor:
            cursor.execute(query, params)
            reservas_db = cursor.fetchall()

        reservas = [
            {
                "id": res['id'],
                "mesa_numero": res['mesa_numero'],
                "cliente_id": res['cliente_id'],
                "cliente_nombre": res['cliente_nombre'],
                "fecha_hora_inicio": str(res['fecha_hora_inicio']),
                "fecha_hora_fin": str(res['fecha_hora_fin']) if res['fecha_hora_fin'] else None
            }
            for res in reservas_db
        ]

        log.info(f"{len(reservas)} reservas enviadas al frontend")
        return reservas

    except Exception as e:
        log.error(f"ERROR al obtener reservas → {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error interno del servidor al obtener reservas.")


@app.post("/reservas/", status_code=201)
def crear_reserva_simplificada(reserva: ReservaCreate, conn = Depends(get_db)):
    log.info(f"POST /reservas → Creando reserva Mesa {reserva.mesa_numero} | Cliente ID {reserva.cliente_id} | {reserva.fecha_hora_inicio}")

    try:
        fecha_inicio_obj = datetime.fromisoformat(reserva.fecha_hora_inicio.replace(" ", "T"))
        if reserva.fecha_hora_fin:
            fecha_fin_obj = datetime.fromisoformat(reserva.fecha_hora_fin.replace(" ", "T"))
        else:
            fecha_fin_obj = fecha_inicio_obj + timedelta(hours=1)
            log.debug(f"Duración no especificada → Asignando 1 hora por defecto")

        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO reservas (mesa_numero, cliente_id, fecha_hora_inicio, fecha_hora_fin)
                VALUES (%s, %s, %s, %s) RETURNING id;
            """, (reserva.mesa_numero, reserva.cliente_id, fecha_inicio_obj, fecha_fin_obj))
            reserva_id = cursor.fetchone()['id']
        
        conn.commit()

        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT r.id, r.mesa_numero, r.cliente_id, c.nombre as cliente_nombre, r.fecha_hora_inicio, r.fecha_hora_fin
                FROM reservas r
                JOIN clientes c ON r.cliente_id = c.id
                WHERE r.id = %s;
            """, (reserva_id,))
            nueva = cursor.fetchone()

        log.info(f"RESERVA CREADA CON ÉXITO → ID: {reserva_id} | Mesa {reserva.mesa_numero} | {nueva['cliente_nombre']} | {fecha_inicio_obj.strftime('%Y-%m-%d %H:%M')}")

        return {
            "id": nueva['id'],
            "mesa_numero": nueva['mesa_numero'],
            "cliente_id": nueva['cliente_id'],
            "cliente_nombre": nueva['cliente_nombre'],
            "fecha_hora_inicio": str(nueva['fecha_hora_inicio']),
            "fecha_hora_fin": str(nueva['fecha_hora_fin']) if nueva['fecha_hora_fin'] else None
        }

    except ValueError as ve:
        log.warning(f"Error de formato de fecha en reserva → {ve}")
        raise HTTPException(status_code=400, detail=f"Formato de fecha/hora inválido: {ve}")
    except Exception as e:
        log.error(f"ERROR al crear reserva → {e}", exc_info=True)
        conn.rollback()
        raise HTTPException(status_code=500, detail="Error interno del servidor al crear la reserva.")


@app.delete("/reservas/{reserva_id}")
def eliminar_reserva(reserva_id: int, conn = Depends(get_db)):
    """
    Elimina una reserva existente por su ID.
    """
    log.warning(f"DELETE /reservas/{reserva_id} → ELIMINANDO RESERVA PERMANENTEMENTE")

    try:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM reservas WHERE id = %s RETURNING id;", (reserva_id,))
            eliminado = cursor.fetchone()
            if not eliminado:
                log.warning(f"Reserva {reserva_id} no encontrada → 404")
                raise HTTPException(status_code=404, detail="Reserva no encontrada")

        conn.commit()
        log.warning(f"RESERVA {reserva_id} ELIMINADA CON ÉXITO DE LA BASE DE DATOS")
        return {"status": "ok", "message": "Reserva eliminada"}

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"ERROR CRÍTICO al eliminar reserva {reserva_id} → {e}", exc_info=True)
        conn.rollback()
        raise HTTPException(status_code=500, detail="Error interno del servidor al eliminar la reserva.")


# --- NUEVO ENDPOINT CORREGIDO: Ventas por Hora ---
@app.get("/reportes/ventas_por_hora")
def obtener_ventas_por_hora(
    fecha: str = Query(..., description="Fecha en formato YYYY-MM-DD para filtrar ventas por hora"),
    conn: psycopg2.extensions.connection = Depends(get_db)
):
    log.info(f"GET /reportes/ventas_por_hora → Generando ventas por hora del día {fecha}")

    try:
        datetime.strptime(fecha, "%Y-%m-%d")
    except ValueError:
        log.warning(f"Fecha inválida recibida en ventas_por_hora → {fecha}")
        raise HTTPException(status_code=400, detail="Formato de fecha inválido. Use YYYY-MM-DD.")

    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT EXTRACT(HOUR FROM fecha_hora) AS hora, SUM(item_data.precio) AS total_venta
                FROM pedidos,
                     jsonb_to_recordset(pedidos.items) AS item_data(nombre TEXT, precio REAL, tipo TEXT, cantidad INTEGER)
                WHERE DATE(fecha_hora) = %s
                  AND estado IN ('Entregado', 'Pagado')
                GROUP BY EXTRACT(HOUR FROM fecha_hora)
                ORDER BY hora;
            """, (fecha,))
            
            resultados_db = cursor.fetchall()

        ventas_por_hora = {f"{h:02d}": 0.0 for h in range(24)}
        total_del_dia = 0.0

        for row in resultados_db:
            hora_int = int(row['hora'])
            total = float(row['total_venta'] or 0)
            hora_str = f"{hora_int:02d}"
            ventas_por_hora[hora_str] = total
            total_del_dia += total

        hora_pico = max(ventas_por_hora.items(), key=lambda x: x[1])[0] if total_del_dia > 0 else "N/A"
        monto_pico = ventas_por_hora[hora_pico]

        log.info(f"VENTAS POR HORA {fecha} → Total día: ${total_del_dia:,.2f} | Hora pico: {hora_pico}h → ${monto_pico:,.2f}")
        return ventas_por_hora

    except Exception as e:
        log.error(f"ERROR CRÍTICO en ventas_por_hora ({fecha}) → {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error interno del servidor al calcular ventas por hora: {str(e)}")


@app.get("/reportes/eficiencia_cocina")
def get_eficiencia_cocina(
    tipo: str,
    start_date: str,
    end_date: str,
    conn = Depends(get_db)
):
    log.info(f"REPORTE EFICIENCIA COCINA → {tipo} | {start_date} → {end_date}")

    with conn.cursor() as cursor:
        query = """
            SELECT id, hora_inicio_cocina, hora_fin_cocina
            FROM pedidos
            WHERE hora_inicio_cocina IS NOT NULL
              AND hora_fin_cocina IS NOT NULL
              AND fecha_hora >= %s
              AND fecha_hora < %s
              AND estado IN ('Listo', 'Entregado', 'Pagado')
            ORDER BY fecha_hora
        """
        cursor.execute(query, (start_date, end_date))
        rows = cursor.fetchall()

        if not rows:
            return {
                "promedio_minutos": 0,
                "total_pedidos": 0,
                "mas_rapido_min": 0,
                "mas_lento_min": 0,
                "detalle_pedidos": []
            }

        tiempos = []
        detalle = []

        for row in rows:
            inicio = row['hora_inicio_cocina']
            fin = row['hora_fin_cocina']
            if isinstance(inicio, str):
                inicio = datetime.fromisoformat(inicio.replace("Z", "+00:00"))
            if isinstance(fin, str):
                fin = datetime.fromisoformat(fin.replace("Z", "+00:00"))
            
            minutos = (fin - inicio).total_seconds() / 60
            tiempos.append(minutos)
            detalle.append({"id": row['id'], "tiempo": round(minutos, 1)})

        promedio = sum(tiempos) / len(tiempos)
        mas_rapido = min(tiempos)
        mas_lento = max(tiempos)

        log.info(f"EFICIENCIA → {len(tiempos)} pedidos | Promedio: {promedio:.1f} min")

        return {
            "promedio_minutos": round(promedio, 1),
            "total_pedidos": len(tiempos),
            "mas_rapido_min": round(mas_rapido, 1),
            "mas_lento_min": round(mas_lento, 1),
            "detalle_pedidos": detalle
        }

@app.delete("/mesas/limpiar_fisicas")
def limpiar_mesas_fisicas(conn=Depends(get_db)):
    try:
        with conn.cursor() as cursor:
            # CASCADE se encarga de borrar los pedidos asociados
            cursor.execute("DELETE FROM mesas WHERE numero != 99")
            eliminadas = cursor.rowcount
            conn.commit()
        log.info(f"CONFIGURACIÓN INICIAL → {eliminadas} mesas físicas eliminadas (pedidos asociados también)")
        return {"status": "ok", "eliminadas": eliminadas}
    except Exception as e:
        log.error(f"Error crítico al limpiar mesas: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/menu/todo")
def limpiar_menu_completo(conn=Depends(get_db)):
    try:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM menu")
            eliminados = cursor.rowcount
            conn.commit()
        log.info(f"Menú completo limpiado → {eliminados} ítems eliminados")
        return {"status": "ok", "message": "Menú limpiado correctamente"}
    except Exception as e:
        log.error(f"Error al limpiar menú: {e}")
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/mesas")
def crear_mesa(mesa: dict, conn=Depends(get_db)):
    try:
        numero = int(mesa["numero"])
        capacidad = int(mesa["capacidad"])
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO mesas (numero, capacidad) 
                VALUES (%s, %s)
                ON CONFLICT (numero) DO UPDATE SET capacidad = %s
            """, (numero, capacidad, capacidad))
            conn.commit()
        log.info(f"Mesa creada/actualizada → Mesa {numero} - Capacidad: {capacidad}")
        return {"status": "ok"}
    except Exception as e:
        log.error(f"Error al crear mesa: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/reportes/rango")
def obtener_reporte_rango(
    fecha_inicio: str, 
    fecha_fin: str, 
    conn = Depends(get_db)
):
    """
    Endpoint para obtener reporte en un rango de fechas
    """
    try:
        with conn.cursor() as cursor:
            # Obtener ventas totales en el rango
            cursor.execute("""
                SELECT 
                    COALESCE(SUM(total), 0) as ventas_totales,
                    COUNT(*) as pedidos_totales
                FROM pedidos 
                WHERE DATE(fecha_hora) BETWEEN %s AND %s 
                AND estado = 'Pagado'
            """, (fecha_inicio, fecha_fin))
            
            resultado = cursor.fetchone()
            ventas_totales = float(resultado[0]) if resultado[0] else 0
            pedidos_totales = int(resultado[1]) if resultado[1] else 0
            
            # Obtener productos vendidos en el rango
            cursor.execute("""
                SELECT SUM(pp.cantidad) as productos_vendidos
                FROM pedidos p
                JOIN pedido_producto pp ON p.id = pp.pedido_id
                WHERE DATE(p.fecha_hora) BETWEEN %s AND %s
                AND p.estado = 'Pagado'
            """, (fecha_inicio, fecha_fin))
            
            resultado_productos = cursor.fetchone()
            productos_vendidos = int(resultado_productos[0]) if resultado_productos[0] else 0
            
            # Obtener productos más vendidos
            cursor.execute("""
                SELECT 
                    pr.nombre,
                    SUM(pp.cantidad) as cantidad
                FROM pedidos p
                JOIN pedido_producto pp ON p.id = pp.pedido_id
                JOIN productos pr ON pp.producto_id = pr.id
                WHERE DATE(p.fecha_hora) BETWEEN %s AND %s
                AND p.estado = 'Pagado'
                GROUP BY pr.id, pr.nombre
                ORDER BY cantidad DESC
                LIMIT 10
            """, (fecha_inicio, fecha_fin))
            
            productos_mas_vendidos = [
                {"nombre": row[0], "cantidad": int(row[1])}
                for row in cursor.fetchall()
            ]
            
            return {
                "ventas_totales": ventas_totales,
                "pedidos_totales": pedidos_totales,
                "productos_vendidos": productos_vendidos,
                "productos_mas_vendidos": productos_mas_vendidos
            }
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al generar reporte: {str(e)}")
