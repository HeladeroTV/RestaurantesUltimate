# === APP.PY ===
# Módulo principal de la interfaz gráfica del sistema de restaurante usando Flet.
import flet as ft
from typing import Optional, Callable, List, Dict, Any
from datetime import datetime
import threading
import time
import requests
import winsound
import time as time_module
import logging  # <-- NUEVO
from pathlib import Path
import copy


# ====================== SISTEMA DE LOGS PROFESIONAL ======================
logging.getLogger("RestaurantIA").handlers.clear()  # Evita duplicados al recargar
log = logging.getLogger("RestaurantIA")

# Configuración rápida y limpia (sin colores para este primer fragmento, luego lo hacemos brutal)
log.setLevel(logging.DEBUG)
if not log.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s | %(levelname)-8s | %(message)s', datefmt='%H:%M:%S')
    handler.setFormatter(formatter)
    log.addHandler(handler)

log.info("app.py cargado correctamente - Iniciando módulo principal")
# ===========================================================================

# IMPORTAR LAS NUEVAS CLASES DE INVENTARIO Y LA NUEVA VISTA DE CAJA
from inventario_view import crear_vista_inventario
from inventario_service import InventoryService
from configuraciones_view import crear_vista_configuraciones
from reportes_view import crear_vista_reportes
from caja_view import crear_vista_caja # <-- IMPORTAR LA NUEVA VISTA DE CAJA
from reservas_view import crear_vista_reservas
from reservas_service import ReservasService # Asumiendo que creas este archivo
# --- AÑADIR ESTOS IMPORTS ---
from recetas_view import crear_vista_recetas
from recetas_service import RecetasService

log.info("Módulos importados correctamente (vistas y servicios)")

# === FUNCIÓN: reproducir_sonido_pedido ===
# Reproduce una melodía simple cuando se confirma un pedido.
def reproducir_sonido_pedido():
    log.debug("Reproduciendo sonido de confirmación de pedido")
    try:
        # Melodía: Do - Mi - Sol
        tones = [523, 659, 784]  # Hz
        for tone in tones:
            winsound.Beep(tone, 200)  # 200 ms por nota
            time_module.sleep(0.05)
        log.debug("Sonido de pedido reproducido correctamente")
    except Exception as e:
        log.error(f"Error al reproducir sonido de pedido: {e}")

# === FUNCIÓN: generar_resumen_pedido ===
# Genera un texto resumen del pedido actual con items y total.
def generar_resumen_pedido(pedido):
    if not pedido.get("items"):
        return "Sin items."
    total = sum(item["precio"] for item in pedido["items"])
    items_str = "\n".join(f"- {item['nombre']} (${item['precio']:.2f})" for item in pedido["items"])
    titulo = obtener_titulo_pedido(pedido)
    log.debug(f"Resumen de pedido generado | {titulo} | {len(pedido['items'])} ítems | Total: ${total:.2f}")
    return f"[{titulo}]\n{items_str}\nTotal: ${total:.2f}"

# === FUNCIÓN: obtener_titulo_pedido ===
# Genera el título del pedido dependiendo si es de mesa o app.
def obtener_titulo_pedido(pedido):
    if pedido.get("mesa_numero") == 99 and pedido.get("numero_app"):
        titulo = f"Digital #{pedido['numero_app']:03d}"
    else:
        titulo = f"Mesa {pedido['mesa_numero']}"
    return titulo

# === FUNCIÓN: crear_selector_item ===
# Crea un selector con dropdowns para filtrar y elegir items del menú.
def crear_selector_item(menu):
    log.debug(f"Creando selector de ítems - Menú con {len(menu)} ítems disponibles")
    tipos = list(set(item["tipo"] for item in menu))
    tipos.sort()
    tipo_dropdown = ft.Dropdown(
        label="Tipo de item",
        options=[ft.dropdown.Option(tipo) for tipo in tipos],
        value=tipos[0] if tipos else "Entradas",
        width=200,
    )
    search_field = ft.TextField(
        label="Buscar ítem...",
        prefix_icon=ft.Icons.SEARCH,
        width=200,
        hint_text="Escribe para filtrar..."
    )
    items_dropdown = ft.Dropdown(
        label="Seleccionar item",
        width=200,
    )
    def filtrar_items(e):
        query = search_field.value.lower().strip() if search_field.value else ""
        tipo_actual = tipo_dropdown.value
        if query:
            items_filtrados = [item for item in menu if query in item["nombre"].lower()]
        else:
            items_filtrados = [item for item in menu if item["tipo"] == tipo_actual]
        items_dropdown.options = [ft.dropdown.Option(item["nombre"]) for item in items_filtrados]
        items_dropdown.value = None
        if e and e.page:
            e.page.update()

    def actualizar_items(e):
        filtrar_items(e)
    tipo_dropdown.on_change = actualizar_items
    search_field.on_change = filtrar_items
    actualizar_items(None)
    container = ft.Column([
        tipo_dropdown,
        search_field,
        items_dropdown
    ], spacing=10)
    container.tipo_dropdown = tipo_dropdown
    container.search_field = search_field
    container.items_dropdown = items_dropdown
    def get_selected_item():
        tipo = tipo_dropdown.value
        nombre = items_dropdown.value
        if tipo and nombre:
            for item in menu:
                if item["nombre"] == nombre and item["tipo"] == tipo:
                    log.debug(f"Ítem seleccionado: {nombre} ({tipo}) - Precio: ${item['precio']}")
                    return item
        return None
    container.get_selected_item = get_selected_item

    def update_menu_data(new_menu):
        nonlocal menu
        menu = new_menu
        # Preservar selección actual si es posible
        seleccion_actual = items_dropdown.value
        tipo_actual = tipo_dropdown.value
        
        tipos = list(set(item["tipo"] for item in menu))
        tipos.sort()
        tipo_dropdown.options = [ft.dropdown.Option(tipo) for tipo in tipos]
        
        # Si el tipo seleccionado sigue existiendo, mantenerlo
        if tipo_actual not in tipos and tipos:
            tipo_dropdown.value = tipos[0]
        else:
             tipo_dropdown.value = tipo_actual
             
        # Actualizar lista de items manteniendo selección si existe
        actualizar_items(None)
        
        # Restaurar selección de item si aún existe en la lista filtrada
        opciones_nombres = [opt.key for opt in items_dropdown.options]
        if seleccion_actual in opciones_nombres:
            items_dropdown.value = seleccion_actual
        else:
             items_dropdown.value = None
             
        container.update()

    container.update_menu_data = update_menu_data
    log.debug("Selector de ítems creado correctamente")
    return container

def crear_mesas_grid(backend_service, on_select, app_instance=None):
    """
    VERSIÓN OPTIMIZADA: Solo actualiza mesas que cambiaron
    Reduce renders del 100% al ~5% en operación normal
    """
    log.debug("Iniciando actualización optimizada del grid de mesas")
    
    try:
        mesas_backend = backend_service.obtener_mesas()
        log.info(f"Mesas obtenidas del backend: {len(mesas_backend)} mesas")

        if not mesas_backend or len(mesas_backend) == 0:
            log.warning("Backend devolvió 0 mesas → usando fallback temporal")
            mesas_backend = [
                {"numero": 1, "capacidad": 4, "ocupada": False},
                {"numero": 2, "capacidad": 4, "ocupada": False},
                {"numero": 3, "capacidad": 6, "ocupada": False},
            ]
            
    except Exception as e:
        log.error(f"Error crítico al obtener mesas del backend: {e}")
        mesas_backend = [
            {"numero": 1, "capacidad": 4, "ocupada": False},
            {"numero": 2, "capacidad": 6, "ocupada": False},
        ]

    # Detectar mesas que cambiaron
    mesas_actuales = {m['numero']: m for m in mesas_backend}
    cache_anterior = copy.deepcopy(getattr(app_instance, 'mesas_cache', {})) if app_instance else {}
    widgets_cache = getattr(app_instance, 'mesas_widgets_cache', {}) if app_instance else {}
    
    # === DETECTAR CAMBIOS (versión mejorada con pedidos) ===
    mesas_nuevas = set(mesas_actuales.keys()) - set(cache_anterior.keys())
    mesas_eliminadas = set(cache_anterior.keys()) - set(mesas_actuales.keys())
    mesas_modificadas = set()

    # Obtener pedidos activos para detectar mesas ocupadas
    try:
        pedidos_activos = backend_service.obtener_pedidos_activos()
        mesas_con_pedidos = {p['mesa_numero'] for p in pedidos_activos if p.get('estado') in ['Pendiente', 'En preparacion', 'Listo']}
    except:
        mesas_con_pedidos = set()

    for num, mesa_actual in mesas_actuales.items():
        if num in cache_anterior:
            mesa_anterior = cache_anterior[num]
            
            # Detectar si la mesa tiene pedido activo (más confiable)
            ocupada_real = num in mesas_con_pedidos
            ocupada_anterior = cache_anterior.get(num, {}).get('_ocupada_cache', False)
            
            # Comparar campos que afectan la UI
            if (ocupada_real != ocupada_anterior or
                mesa_actual.get('reservada') != mesa_anterior.get('reservada') or
                mesa_actual.get('capacidad') != mesa_anterior.get('capacidad')):
                mesas_modificadas.add(num)
                # Guardar estado real en caché
                mesa_actual['_ocupada_cache'] = ocupada_real
        else:
            # Mesa nueva, marcar si tiene pedido
            mesa_actual['_ocupada_cache'] = num in mesas_con_pedidos
    
    cambios_detectados = len(mesas_nuevas) + len(mesas_eliminadas) + len(mesas_modificadas)
    
    if cambios_detectados == 0 and cache_anterior:
        log.debug("⚡ SIN CAMBIOS - Reutilizando grid existente (0 renders)")
        # Retornar grid con widgets en caché
        grid = ft.GridView(
            expand=1,
            runs_count=3,
            max_extent=220,
            child_aspect_ratio=1.0,
            spacing=15,
            run_spacing=15,
            padding=15,
        )
        # Agregar widgets en orden
        for num in sorted(mesas_actuales.keys()):
            if num in widgets_cache:
                grid.controls.append(widgets_cache[num])
        return grid
    
    log.info(f"⚡ CAMBIOS DETECTADOS: {len(mesas_nuevas)} nuevas | {len(mesas_modificadas)} modificadas | {len(mesas_eliminadas)} eliminadas")

    # === CREAR/ACTUALIZAR SOLO MESAS MODIFICADAS ===
    grid = ft.GridView(
        expand=1,
        runs_count=3,
        max_extent=220,
        child_aspect_ratio=1.0,
        spacing=15,
        run_spacing=15,
        padding=15,
    )

    mesas_ocupadas = mesas_libres = mesas_reservadas = 0

    for mesa in sorted(mesas_backend, key=lambda m: m['numero']):
        if mesa["numero"] == 99:
            continue

        num_mesa = mesa["numero"]
        ocupada = mesa.get("ocupada", False)
        reservada = mesa.get("reservada", False)

        # Contadores
        if ocupada:
            mesas_ocupadas += 1
            color_base = ft.Colors.RED_700
            estado = "OCUPADA"
        else:
            mesas_libres += 1
            color_base = ft.Colors.GREEN_700
            estado = "LIBRE"

        # === OPTIMIZACIÓN: Reutilizar widget si no cambió ===
        if num_mesa not in mesas_nuevas and num_mesa not in mesas_modificadas and num_mesa in widgets_cache:
            grid.controls.append(widgets_cache[num_mesa])
            continue
        
        # === CREAR WIDGET NUEVO SOLO SI CAMBIÓ ===
        contenido_mesa = ft.Column(
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=5,
            controls=[
                ft.Row(
                    alignment=ft.MainAxisAlignment.CENTER,
                    controls=[
                        ft.Icon(ft.Icons.TABLE_RESTAURANT, color=ft.Colors.AMBER_400),
                        ft.Text(f"Mesa {num_mesa}", size=16, weight=ft.FontWeight.BOLD),
                    ]
                ),
                ft.Text(f"Capacidad: {mesa['capacidad']}", size=12),
                ft.Text(estado, size=14, weight=ft.FontWeight.BOLD)
            ]
        )

        carta_mesa = ft.Container(
            key=f"mesa-{num_mesa}",
            bgcolor=color_base,
            border_radius=15,
            padding=15,
            ink=True,
            on_click=lambda e, num=num_mesa: on_select(num),
            content=contenido_mesa,
            animate=ft.Animation(200, "easeOut"),
            animate_scale=ft.Animation(200, "easeOut"),
        )

        def on_hover_mesa(e, carta=carta_mesa, color_base=color_base):
            if e.data == "true":
                carta.scale = 1.05
                carta.bgcolor = ft.Colors.BLUE_800 if color_base == ft.Colors.GREEN_700 else ft.Colors.RED_900
            else:
                carta.scale = 1.0
                carta.bgcolor = color_base
            carta.update()

        carta_mesa.on_hover = lambda e, carta=carta_mesa, cb=color_base: on_hover_mesa(e, carta, cb)
        
        # Guardar en caché
        if app_instance:
            widgets_cache[num_mesa] = carta_mesa
        
        grid.controls.append(carta_mesa)

    # === MESA VIRTUAL 99 (siempre se crea) ===
    contenido_mesa_virtual = ft.Column(
        alignment=ft.MainAxisAlignment.CENTER,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=5,
        controls=[
            ft.Row(
                alignment=ft.MainAxisAlignment.CENTER,
                controls=[
                    ft.Icon(ft.Icons.MOBILE_FRIENDLY, color=ft.Colors.AMBER_400),
                    ft.Text("Pedido digital", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                ]
            ),
            ft.Text("Pedidos por Digital", size=12, color=ft.Colors.WHITE),
            ft.Text("Siempre disponible", size=10, color=ft.Colors.WHITE),
        ]
    )
    
    if 99 in widgets_cache and 99 not in mesas_modificadas:
        grid.controls.append(widgets_cache[99])
    else:
        carta_mesa_virtual = ft.Container(
            key="Pedido digital",
            bgcolor=ft.Colors.BLUE_700,
            border_radius=15,
            padding=15,
            ink=True,
            on_click=lambda e: on_select(99),
            width=220,
            height=150,
            content=contenido_mesa_virtual,
            animate=ft.Animation(200, "easeOut"),
            animate_scale=ft.Animation(200, "easeOut"),
        )

        def on_hover_virtual(e, carta=carta_mesa_virtual):
            if e.data == "true":
                carta.scale = 1.05
                carta.bgcolor = ft.Colors.BLUE_800
            else:
                carta.scale = 1.0
                carta.bgcolor = ft.Colors.BLUE_700
            carta.update()

        carta_mesa_virtual.on_hover = lambda e, c=carta_mesa_virtual: on_hover_virtual(e, c)
        
        if app_instance:
            widgets_cache[99] = carta_mesa_virtual
        
        grid.controls.append(carta_mesa_virtual)

    # === ACTUALIZAR CACHÉ SOLO SI HUBO CAMBIOS ===
    if app_instance and cambios_detectados > 0:
        # Hacer copia profunda ANTES de guardar para evitar referencias mutables
        app_instance.mesas_cache = copy.deepcopy(mesas_actuales)
        app_instance.mesas_widgets_cache = widgets_cache
        log.debug(f"Caché actualizado → {len(mesas_actuales)} mesas guardadas")
    elif app_instance and cambios_detectados == 0:
        # NO actualizar caché si no hubo cambios (mantener estado anterior)
        log.debug("Caché sin cambios (estado anterior preservado)")

    log.info(f"Grid actualizado → {mesas_libres} libres | {mesas_reservadas} reservadas | {mesas_ocupadas} ocupadas | Renders: {cambios_detectados}/{len(mesas_backend)}")
    return grid


# === FUNCIÓN: crear_panel_gestion ===
# Crea el panel lateral para gestionar pedidos de una mesa seleccionada.
def crear_panel_gestion(backend_service, menu, on_update_ui, page, primary_color, primary_dark_color):
    log.debug("Creando panel de gestión de pedidos")
    estado = {"mesa_seleccionada": None, "pedido_actual": None}
    mesa_info = ft.Text("", size=16, weight=ft.FontWeight.BOLD)
    tamaño_grupo_input = ft.TextField(
        label="Tamaño del grupo",
        input_filter=ft.NumbersOnlyInputFilter(),
        prefix_icon=ft.Icons.PEOPLE
    )
    # Campo de texto para la nota
    nota_pedido = ft.TextField(
        label="Notas del pedido",
        multiline=True,
        max_lines=3,
        hint_text="Ej: Sin cebolla, sin salsa, etc.",
        width=400
    )
    selector_item = crear_selector_item(menu)
    # --- NUEVO: Selector de Cantidad ---
    cantidad_dropdown = ft.Dropdown(
        label="Cantidad",
        options=[ft.dropdown.Option(i) for i in range(1, 11)],
        value="1",
        width=100,
        disabled=True
    )
    # --- BOTONES CON EFECTOS DE HOVER ESTILIZADOS ---
    asignar_btn = ft.ElevatedButton(
        text="Asignar Cliente",
        disabled=True,
        style=ft.ButtonStyle(
            color={"": "white"},
            bgcolor={"": ft.Colors.GREEN_700, "hovered": primary_dark_color},
        ),
    )
    agregar_item_btn = ft.ElevatedButton(
        text="Agregar Item",
        disabled=True,
        style=ft.ButtonStyle(
            color={"": "white"},
            bgcolor={"": ft.Colors.BLUE_700, "hovered": primary_dark_color},
        ),
    )
    eliminar_ultimo_btn = ft.ElevatedButton(
        text="Eliminar último ítem",
        disabled=True,
        style=ft.ButtonStyle(
            color={"": "white"},
            bgcolor={"": ft.Colors.RED_700, "hovered": primary_dark_color},
        ),
    )
    confirmar_pedido_btn = ft.ElevatedButton(
        text="Confirmar Pedido",
        disabled=True,
        style=ft.ButtonStyle(
            color={"": "white"},
            bgcolor={"": ft.Colors.AMBER_700, "hovered": primary_dark_color},
        ),
    )
    # --- FIN BOTONES ---
    resumen_pedido = ft.Text("", size=14)

    def actualizar_estado_botones():
        mesa_seleccionada = estado["mesa_seleccionada"]
        pedido_actual = estado["pedido_actual"]
        if not mesa_seleccionada:
            asignar_btn.disabled = True
            agregar_item_btn.disabled = True
            eliminar_ultimo_btn.disabled = True
            confirmar_pedido_btn.disabled = True
            cantidad_dropdown.disabled = True
            return
        if mesa_seleccionada.get("numero") == 99:
            asignar_btn.disabled = pedido_actual is not None
            agregar_item_btn.disabled = pedido_actual is None
            eliminar_ultimo_btn.disabled = pedido_actual is None or not pedido_actual.get("items", [])
            confirmar_pedido_btn.disabled = pedido_actual is None or not pedido_actual.get("items", [])
            cantidad_dropdown.disabled = pedido_actual is None or selector_item.get_selected_item() is None
        else:
            asignar_btn.disabled = mesa_seleccionada.get("ocupada", False)
            agregar_item_btn.disabled = pedido_actual is None
            eliminar_ultimo_btn.disabled = pedido_actual is None or not pedido_actual.get("items", [])
            confirmar_pedido_btn.disabled = pedido_actual is None or not pedido_actual.get("items", [])
            cantidad_dropdown.disabled = pedido_actual is None or selector_item.get_selected_item() is None
        page.update()

    def on_item_selected(e):
        if estado["pedido_actual"] and selector_item.get_selected_item():
            cantidad_dropdown.disabled = False
            log.debug(f"Selector de cantidad habilitado - Ítem seleccionado")
        else:
            cantidad_dropdown.disabled = True
        page.update()

    selector_item.items_dropdown.on_change = on_item_selected

    def seleccionar_mesa_interna(numero_mesa):
        log.info(f"Mesa seleccionada por el usuario: {numero_mesa}")
        try:
            mesas = backend_service.obtener_mesas()
            mesa_seleccionada = next((m for m in mesas if m["numero"] == numero_mesa), None)
            estado["mesa_seleccionada"] = mesa_seleccionada
            estado["pedido_actual"] = None

            if not mesa_seleccionada:
                log.warning(f"Mesa {numero_mesa} no encontrada en el backend")
                return

            if mesa_seleccionada.get("ocupada", False):
                log.info(f"Mesa {numero_mesa} está ocupada - Buscando pedido activo")
                pedidos_activos = backend_service.obtener_pedidos_activos()
                pedido_existente = next((p for p in pedidos_activos if p["mesa_numero"] == numero_mesa and p.get("estado") in ["Tomando pedido", "Pendiente", "En preparacion"]), None)
                if pedido_existente:
                    if numero_mesa == 99:
                        # Mostrar información especial para pedidos digitales
                        mesa_info.value = f"Mesa Digital - Pedido #{pedido_existente.get('numero_app', 'N/A'):03d} (Pedido Activo)"
                    else:
                        mesa_info.value = f"Mesa {mesa_seleccionada['numero']} - Capacidad: {mesa_seleccionada['capacidad']} personas (Pedido Activo)"
                    log.info(f"Pedido activo cargado para Mesa {numero_mesa} - ID: {pedido_existente['id']}")
                else:
                    if numero_mesa == 99:
                        mesa_info.value = "Mesa Digital - Sin pedido activo"
                    else:
                        mesa_info.value = f"Mesa {mesa_seleccionada['numero']} - Ocupada (Estado inconsistente)"
                    log.warning(f"Mesa {numero_mesa} marcada como ocupada pero sin pedido activo")
            elif mesa_seleccionada.get("reservada", False):
                fecha_reserva_str = mesa_seleccionada.get("fecha_hora_reserva")
                if fecha_reserva_str:
                    try:
                        fecha_reserva = datetime.strptime(fecha_reserva_str.split(".")[0], "%Y-%m-%d %H:%M:%S")
                        ahora = datetime.now()
                        if ahora >= fecha_reserva or (ahora - fecha_reserva).total_seconds() < 1800:
                            if numero_mesa == 99:
                                mesa_info.value = f"Mesa Digital - Reservada para {mesa_seleccionada.get('cliente_reservado_nombre', 'N/A')}"
                            else:
                                mesa_info.value = f"Mesa {mesa_seleccionada['numero']} - Reservada para {mesa_seleccionada.get('cliente_reservado_nombre', 'N/A')} - Capacidad: {mesa_seleccionada['capacidad']} personas"
                            log.info(f"Reserva activa permitida - Mesa {numero_mesa}")
                        else:
                            if numero_mesa == 99:
                                mesa_info.value = f"Mesa Digital - Reservada para {mesa_seleccionada.get('cliente_reservado_nombre', 'N/A')} el {fecha_reserva_str}"
                            else:
                                mesa_info.value = f"Mesa {mesa_seleccionada['numero']} - Reservada para {mesa_seleccionada.get('cliente_reservado_nombre', 'N/A')} el {fecha_reserva_str}"
                            estado["pedido_actual"] = None
                            asignar_btn.disabled = True
                            page.update()
                            log.info(f"Reserva futura bloqueada - Mesa {numero_mesa} hasta {fecha_reserva_str}")
                            return
                    except ValueError:
                        log.error(f"Error al parsear fecha de reserva para mesa {numero_mesa}: {fecha_reserva_str}")
                        if numero_mesa == 99:
                            mesa_info.value = "Mesa Digital - Reservada (Fecha inválida)"
                        else:
                            mesa_info.value = f"Mesa {mesa_seleccionada['numero']} - Reservada (Fecha inválida)"
                else:
                    if numero_mesa == 99:
                        mesa_info.value = "Mesa Digital - Reservada (Sin fecha)"
                    else:
                        mesa_info.value = f"Mesa {mesa_seleccionada['numero']} - Reservada (Sin fecha)"
            else:
                if numero_mesa == 99:
                    mesa_info.value = "Mesa Digital - Lista para nuevo pedido"
                else:
                    mesa_info.value = f"Mesa {mesa_seleccionada['numero']} - Capacidad: {mesa_seleccionada['capacidad']} personas"
                log.info(f"Mesa {numero_mesa} {'Digital' if numero_mesa == 99 else 'libre'} - Listo para asignar cliente")

            resumen_pedido.value = ""
            nota_pedido.value = ""
            actualizar_estado_botones()
        except Exception as e:
            log.error(f"Error crítico al seleccionar mesa {numero_mesa}: {e}")
            mesa_info.value = f"Error al seleccionar mesa {numero_mesa}"

    def asignar_cliente(e):
        mesa_seleccionada = estado["mesa_seleccionada"]
        if not mesa_seleccionada:
            log.warning("Intento de asignar cliente sin mesa seleccionada")
            return

        numero_mesa = mesa_seleccionada["numero"]
        log.info(f"Asignando cliente a Mesa {numero_mesa}")

        try:
            mesas_actualizadas = backend_service.obtener_mesas()
            mesa_estado_actual = next((m for m in mesas_actualizadas if m["numero"] == numero_mesa), None)
            if not mesa_estado_actual:
                log.error(f"Mesa {numero_mesa} desapareció del backend al intentar asignar")
                return

            if mesa_estado_actual.get("ocupada", False):
                log.warning(f"Bloqueo: Mesa {numero_mesa} ya está ocupada")
                return
            elif mesa_estado_actual.get("reservada", False):
                fecha_reserva_str = mesa_estado_actual.get("fecha_hora_reserva")
                if fecha_reserva_str:
                    try:
                        fecha_reserva = datetime.strptime(fecha_reserva_str.split(".")[0], "%Y-%m-%d %H:%M:%S")
                        ahora = datetime.now()
                        if ahora < fecha_reserva and (fecha_reserva - ahora).total_seconds() >= 1800:
                            log.warning(f"Bloqueo por reserva futura: Mesa {numero_mesa}")
                            return
                    except ValueError:
                        log.error(f"Error parseando fecha reserva al asignar Mesa {numero_mesa}")

            nuevo_pedido = {
                "id": None,
                "mesa_numero": numero_mesa,
                "items": [],
                "estado": "Tomando pedido",
                "fecha_hora": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "numero_app": None,
                "notas": nota_pedido.value or ""
            }
            estado["pedido_actual"] = nuevo_pedido
            resumen_pedido.value = ""
            on_update_ui()
            actualizar_estado_botones()
            log.info(f"Cliente asignado correctamente - Mesa {numero_mesa} | Pedido en memoria creado")

        except Exception as ex:
            log.error(f"Error al asignar cliente a Mesa {numero_mesa}: {ex}")

    def agregar_item_pedido(e):
        mesa_seleccionada = estado["mesa_seleccionada"]
        pedido_actual = estado["pedido_actual"]
        if not mesa_seleccionada or not pedido_actual:
            log.warning("Intento de agregar ítem sin mesa o pedido activo")
            return
        item = selector_item.get_selected_item()
        if not item:
            log.warning("Intento de agregar ítem sin seleccionar ningún producto")
            return

        # --- OBTENER CANTIDAD SELECCIONADA ---
        try:
            cantidad = int(cantidad_dropdown.value)
            if cantidad < 1:
                cantidad = 1
        except ValueError:
            cantidad = 1
            log.debug("Valor inválido en cantidad_dropdown → usando 1 por defecto")

        log.info(f"Agregando {cantidad} × '{item['nombre']}' a Mesa {mesa_seleccionada['numero']}")

        try:
            if pedido_actual["id"] is None:
                # Pedido en memoria
                items_actuales = pedido_actual.get("items", [])
                for _ in range(cantidad):
                    items_actuales.append({
                        "nombre": item["nombre"],
                        "precio": item["precio"],
                        "tipo": item["tipo"],
                        "cantidad": 1
                    })
                pedido_actual["items"] = items_actuales
                estado["pedido_actual"] = pedido_actual
                log.debug(f"Ítem agregado en memoria - Total ítems: {len(items_actuales)}")
            else:
                # Pedido ya existe en BD
                items_actuales = pedido_actual.get("items", [])
                for _ in range(cantidad):
                    items_actuales.append({
                        "nombre": item["nombre"],
                        "precio": item["precio"],
                        "tipo": item["tipo"],
                        "cantidad": 1
                    })
                resultado = backend_service.actualizar_pedido(
                    pedido_actual["id"],
                    pedido_actual["mesa_numero"],
                    items_actuales,
                    pedido_actual["estado"],
                    pedido_actual.get("notas", "")
                )
                pedido_actual["items"] = items_actuales
                estado["pedido_actual"] = pedido_actual
                log.info(f"Ítem agregado a pedido existente (ID: {pedido_actual['id']}) - Total: {len(items_actuales)} ítems")

            cantidad_dropdown.value = "1"
            cantidad_dropdown.disabled = selector_item.get_selected_item() is None
            resumen = generar_resumen_pedido(pedido_actual)
            resumen_pedido.value = resumen
            on_update_ui()
            actualizar_estado_botones()

        except Exception as ex:
            log.error(f"Error crítico al agregar ítem '{item['nombre']}' a Mesa {mesa_seleccionada['numero']}: {ex}")

    def eliminar_ultimo_item(e):
        pedido_actual = estado["pedido_actual"]
        if not pedido_actual:
            log.warning("Intento de eliminar ítem sin pedido activo")
            return

        log.info(f"Eliminando último ítem de Mesa {estado['mesa_seleccionada']['numero']}")

        try:
            if pedido_actual["id"] is None:
                items = pedido_actual.get("items", [])
                if items:
                    eliminado = items.pop()
                    pedido_actual["items"] = items
                    estado["pedido_actual"] = pedido_actual
                    resumen_pedido.value = generar_resumen_pedido(estado["pedido_actual"])
                    log.debug(f"Ítem eliminado en memoria: {eliminado['nombre']}")
                else:
                    resumen_pedido.value = "Sin items."
            else:
                backend_service.eliminar_ultimo_item(pedido_actual["id"])
                pedidos_activos = backend_service.obtener_pedidos_activos()
                pedido_actualizado = next((p for p in pedidos_activos if p["id"] == pedido_actual["id"]), None)
                if pedido_actualizado:
                    estado["pedido_actual"] = pedido_actualizado
                    resumen_pedido.value = generar_resumen_pedido(estado["pedido_actual"])
                    log.info(f"Último ítem eliminado en BD - Pedido ID: {pedido_actual['id']}")
                else:
                    resumen_pedido.value = "Sin items."
                    estado["pedido_actual"] = None
                    log.info(f"Pedido {pedido_actual['id']} quedó vacío tras eliminar último ítem")

            on_update_ui()
            actualizar_estado_botones()

        except Exception as ex:
            log.error(f"Error crítico al eliminar último ítem del pedido: {ex}")

    def confirmar_pedido(e):
        pedido_actual = estado["pedido_actual"]
        if not pedido_actual:
            log.warning("Intento de confirmar pedido sin pedido activo")
            return
        if not pedido_actual.get("items"):
            log.warning("Intento de confirmar pedido vacío")
            return

        mesa_num = estado["mesa_seleccionada"]["numero"]
        total = sum(item["precio"] for item in pedido_actual["items"])
        log.info(f"Confirmando pedido Mesa {mesa_num} | {len(pedido_actual['items'])} ítems | Total: ${total:.2f}")

        try:
            nota_a_guardar = nota_pedido.value.strip() if nota_pedido.value else ""

            if pedido_actual["id"] is None:
                nuevo_pedido = backend_service.crear_pedido(
                    pedido_actual["mesa_numero"],
                    pedido_actual["items"],
                    "Pendiente",
                    nota_a_guardar
                )
                estado["pedido_actual"] = nuevo_pedido
                log.info(f"Nuevo pedido creado en BD - ID: {nuevo_pedido['id']} | Mesa: {mesa_num}")
            else:
                backend_service.actualizar_pedido(
                    pedido_actual["id"],
                    pedido_actual["mesa_numero"],
                    pedido_actual["items"],
                    "Pendiente",
                    nota_a_guardar
                )
                log.info(f"Pedido existente actualizado en BD - ID: {pedido_actual['id']} | Mesa: {mesa_num}")

            cantidad_dropdown.value = "1"
            cantidad_dropdown.disabled = True
            estado["pedido_actual"] = None
            estado["mesa_seleccionada"] = None
            mesa_info.value = ""
            resumen_pedido.value = ""
            nota_pedido.value = ""
            actualizar_estado_botones()
            on_update_ui()

            threading.Thread(target=reproducir_sonido_pedido, daemon=True).start()
            log.info(f"Pedido confirmado exitosamente - Mesa {mesa_num} enviado a cocina")

        except Exception as ex:
            log.error(f"ERROR CRÍTICO al confirmar pedido Mesa {mesa_num}: {ex}")
            msg_error = str(ex)
            def cerrar_alerta_stock(e):
                page.close(dlg_alerta)
            dlg_alerta = ft.AlertDialog(
                title=ft.Text("No se puede tomar la orden", color="red"),
                content=ft.Text(f"{msg_error}", size=16),
                actions=[ft.TextButton("Entendido", on_click=cerrar_alerta_stock)],
                actions_alignment=ft.MainAxisAlignment.END,
            )
            page.open(dlg_alerta)
            page.update()

            # --- FIN MOSTRAR ERROR ---
    asignar_btn.on_click = asignar_cliente
    agregar_item_btn.on_click = agregar_item_pedido
    eliminar_ultimo_btn.on_click = eliminar_ultimo_item
    confirmar_pedido_btn.on_click = confirmar_pedido

    panel = ft.Container(
        content=ft.Column(
            controls=[
                ft.Container(
                    content=mesa_info,
                    bgcolor=ft.Colors.BLUE_GREY_900,
                    padding=10,
                    border_radius=10,
                ),
                ft.Container(height=20),
                tamaño_grupo_input,
                asignar_btn,
                ft.Divider(),
                nota_pedido,
                ft.Divider(),
                selector_item,
                ft.Row([
                    cantidad_dropdown,
                    ft.Text("   ", width=10),
                    agregar_item_btn
                ], alignment=ft.MainAxisAlignment.START),
                eliminar_ultimo_btn,
                confirmar_pedido_btn,
                ft.Divider(),
                ft.Divider(),
                ft.Text("Resumen del pedido", size=16, weight=ft.FontWeight.BOLD),
                ft.Container(
                    content=resumen_pedido,
                    bgcolor=ft.Colors.BLUE_GREY_900,
                    padding=10,
                    border_radius=10,
                )
            ],
            spacing=10,
            expand=True,
        ),
        padding=20,
        expand=True
    )
    panel.seleccionar_mesa = seleccionar_mesa_interna
    
    def actualizar_menu_gestion(novo_menu):
        selector_item.update_menu_data(novo_menu)
    panel.actualizar_menu = actualizar_menu_gestion

    log.info("Panel de gestión de pedidos creado correctamente")
    return panel


def crear_vista_cocina(backend_service, on_update_ui, page):
    log.debug("Creando vista de Cocina (versión con ícono de advertencia para retrasos)")
    lista_pedidos = ft.ListView(
        expand=1,
        spacing=10,
        padding=20,
        auto_scroll=True,
    )

    # Variables para almacenar alertas de retraso detectadas en esta vista
    alertas_retraso_vista = []

    def actualizar():
        nonlocal alertas_retraso_vista
        try:
            pedidos = backend_service.obtener_pedidos_activos()
            pendientes = sum(1 for p in pedidos if p.get("estado") == "Pendiente")
            en_preparacion = sum(1 for p in pedidos if p.get("estado") == "En preparacion")
            log.info(f"Actualizando vista Cocina | Pendientes: {pendientes} | En preparación: {en_preparacion}")

            # Detectar retrasos en pedidos activos
            ahora = datetime.now()
            alertas_retraso_vista.clear() # Limpiar alertas anteriores de esta vista
            for pedido in pedidos:
                if pedido.get("estado") in ["Pendiente", "En preparacion"] and pedido.get("items"):
                    try:
                        # Parsear la fecha del pedido
                        fecha_pedido_str = pedido.get('fecha_hora', '')
                        if fecha_pedido_str:
                            fecha_pedido = datetime.strptime(fecha_pedido_str.split(".")[0], "%Y-%m-%d %H:%M:%S")
                            mins_retraso = (ahora - fecha_pedido).total_seconds() / 60

                            # Supongamos que la instancia principal tiene el umbral
                            # (esto se obtiene de la página o de una variable global si no es accesible directamente aquí)
                            # Por ahora, usaremos un valor fijo o uno pasado como parámetro si es posible
                            # OJO: Esto es un punto crítico. La mejor forma es pasar el umbral desde la instancia principal.
                            # Por simplicidad temporal, usaremos 20 minutos como ejemplo.
                            # Lo ideal es poder acceder a app_instance.tiempo_umbral_minutos
                            umbral_retraso = 20 # Este valor debería venir de la instancia principal de la app

                            # Intentar acceder al umbral desde la instancia principal si está disponible
                            if hasattr(page, 'app_instance') and hasattr(page.app_instance, 'tiempo_umbral_minutos'):
                                 umbral_retraso = page.app_instance.tiempo_umbral_minutos
                            else:
                                log.warning("No se pudo acceder al umbral de retraso desde la página. Usando valor por defecto (20 min).")

                            if mins_retraso >= umbral_retraso:
                                titulo = obtener_titulo_pedido(pedido)
                                alertas_retraso_vista.append({
                                    "id_pedido": pedido['id'],
                                    "titulo_pedido": titulo,
                                    "estado": pedido['estado'],
                                    "tiempo_retraso": round(mins_retraso, 1),
                                    "fecha_hora": fecha_pedido
                                })
                                log.warning(f"PEDIDO ATRASADO DETECTADO EN VISTA COCINA (en tiempo real) → {titulo} | {mins_retraso:.1f} min (umbral: {umbral_retraso})")
                    except ValueError:
                        log.error(f"Error al parsear fecha_hora del pedido ID {pedido.get('id', 'N/A')}: {fecha_pedido_str}")
                        continue # Saltar este pedido si hay error en la fecha

            # Actualizar indicadores de alerta globales si hay alertas detectadas en esta vista
            hay_retrasos = len(alertas_retraso_vista) > 0
            if hasattr(page, 'app_instance'):
                 page.app_instance.hay_pedidos_atrasados = hay_retrasos
                 page.app_instance.lista_alertas_retrasos = alertas_retraso_vista
                 # Forzar actualización de visibilidad de alertas
                 if hasattr(page.app_instance, 'actualizar_visibilidad_alerta'):
                     page.app_instance.actualizar_visibilidad_alerta()

            lista_pedidos.controls.clear()
            for pedido in pedidos:
                if pedido.get("estado") in ["Pendiente", "En preparacion"] and pedido.get("items"):
                    lista_pedidos.controls.append(crear_item_pedido_cocina(pedido, backend_service, on_update_ui))
            page.update()
        except Exception as e:
            log.error(f"Error crítico al actualizar vista Cocina: {e}")

    def crear_item_pedido_cocina(pedido, backend_service, on_update_ui):
        pedido_id = pedido["id"]
        titulo_base = obtener_titulo_pedido(pedido)
        
        # Verificar si el pedido está retrasado
        pedido_atrasado = any(a['id_pedido'] == pedido_id for a in alertas_retraso_vista)
        
        # ===== NUEVO SISTEMA DE COLORES POR ESTADO =====
        estado_pedido = pedido.get("estado", "Pendiente")
        
        # Definir colores según estado
        if pedido_atrasado:
            # RETRASADO: Rojo intenso con borde pulsante
            bg_color_pedido = ft.Colors.with_opacity(0.15, ft.Colors.RED_900)
            border_color = ft.Colors.RED_600
            borde_width = 3
            icono_estado = ft.Icons.WARNING_AMBER
            color_icono = ft.Colors.RED_400
            gradient = ft.LinearGradient(
                begin=ft.alignment.top_left,
                end=ft.alignment.bottom_right,
                colors=[
                    ft.Colors.with_opacity(0.2, ft.Colors.RED_900),
                    ft.Colors.with_opacity(0.1, ft.Colors.RED_800),
                ]
            )
        elif estado_pedido == "Pendiente":
            # PENDIENTE: Azul suave
            bg_color_pedido = ft.Colors.with_opacity(0.1, ft.Colors.BLUE_900)
            border_color = ft.Colors.BLUE_700
            borde_width = 2
            icono_estado = ft.Icons.SCHEDULE
            color_icono = ft.Colors.BLUE_400
            gradient = ft.LinearGradient(
                begin=ft.alignment.top_left,
                end=ft.alignment.bottom_right,
                colors=[
                    ft.Colors.with_opacity(0.15, ft.Colors.BLUE_900),
                    ft.Colors.with_opacity(0.05, ft.Colors.BLUE_800),
                ]
            )
        elif estado_pedido == "En preparacion":
            # EN PREPARACIÓN: Naranja vibrante
            bg_color_pedido = ft.Colors.with_opacity(0.1, ft.Colors.ORANGE_900)
            border_color = ft.Colors.ORANGE_700
            borde_width = 2
            icono_estado = ft.Icons.RESTAURANT_MENU
            color_icono = ft.Colors.ORANGE_400
            gradient = ft.LinearGradient(
                begin=ft.alignment.top_left,
                end=ft.alignment.bottom_right,
                colors=[
                    ft.Colors.with_opacity(0.15, ft.Colors.ORANGE_900),
                    ft.Colors.with_opacity(0.05, ft.Colors.ORANGE_800),
                ]
            )
        else:
            # FALLBACK (por si acaso)
            bg_color_pedido = ft.Colors.BLUE_GREY_900
            border_color = ft.Colors.BLUE_GREY_700
            borde_width = 1
            icono_estado = ft.Icons.HELP_OUTLINE
            color_icono = ft.Colors.GREY_400
            gradient = None
        
        # Si está retrasado, agregar ícono de advertencia al título
        if pedido_atrasado:
            # Encontrar la alerta para obtener el tiempo de retraso
            alerta = next((a for a in alertas_retraso_vista if a['id_pedido'] == pedido_id), None)
            tiempo_retraso = alerta['tiempo_retraso'] if alerta else 0
            origen = f"⚠️ {titulo_base} - {pedido.get('fecha_hora', 'Sin fecha')[-8:]}"
            # Agregar información adicional sobre el retraso
            info_retraso = ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.ALARM, color=ft.Colors.RED_400, size=16),
                    ft.Text(
                        f"RETRASADO: {tiempo_retraso:.1f} minutos",
                        size=13,
                        color=ft.Colors.RED_300,
                        weight=ft.FontWeight.BOLD
                    )
                ], spacing=5),
                padding=ft.padding.only(top=5, bottom=5),
                bgcolor=ft.Colors.with_opacity(0.2, ft.Colors.RED_900),
                border_radius=5,
            )
        else:
            origen = f"{titulo_base} - {pedido.get('fecha_hora', 'Sin fecha')[-8:]}"
            info_retraso = None

        def cambiar_estado(e, p, nuevo_estado):
            try:
                backend_service.actualizar_estado_pedido(p["id"], nuevo_estado)
                log.info(f"Estado cambiado → Pedido {p['id']} | {p.get('estado','?')} → {nuevo_estado}")
                on_update_ui()
            except Exception as ex:
                log.error(f"Error al cambiar estado del pedido {p['id']} a '{nuevo_estado}': {ex}")

        def eliminar_pedido_click(e):
            try:
                backend_service.eliminar_pedido(pedido["id"])
                log.warning(f"Pedido ELIMINADO por cocina → ID: {pedido_id} | {titulo_base}")
                on_update_ui()
            except Exception as ex:
                log.error(f"Error al eliminar pedido {pedido_id} desde cocina: {ex}")

        notas_pedido = pedido.get('notas', '').strip()
        nota = "Sin Nota" if not notas_pedido else f"📝 {notas_pedido}"

        # ===== HEADER DEL CARD CON ÍCONO DE ESTADO =====
        header_card = ft.Container(
            content=ft.Row([
                ft.Icon(icono_estado, color=color_icono, size=24),
                ft.Text(
                    origen,
                    size=18,
                    weight=ft.FontWeight.BOLD,
                    expand=True
                ),
                ft.IconButton(
                    icon=ft.Icons.DELETE_OUTLINE,
                    on_click=eliminar_pedido_click,
                    tooltip="Eliminar pedido",
                    icon_color=ft.Colors.RED_400,
                    hover_color=ft.Colors.RED_900
                )
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            padding=10,
            bgcolor=ft.Colors.with_opacity(0.1, border_color),
            border_radius=ft.border_radius.only(top_left=10, top_right=10),
        )

        # Construir los controles base
        controls_list = [
            header_card,
            ft.Divider(height=1, color=border_color),
            ft.Container(
                content=ft.Text(generar_resumen_pedido(pedido), size=14),
                padding=10
            ),
        ]

        # Agregar información de retraso si aplica
        if info_retraso:
            controls_list.append(ft.Container(content=info_retraso, padding=ft.padding.symmetric(horizontal=10)))
            
        # Agregar nota
        controls_list.append(
            ft.Container(
                content=ft.Text(nota, color=ft.Colors.AMBER_200, size=13, italic=True),
                padding=10
            )
        )
        
        # Agregar botones de estado
        controls_list.append(
            ft.Container(
                content=ft.Row([
                    ft.ElevatedButton(
                        "🔄 En preparación",
                        on_click=lambda e, p=pedido: cambiar_estado(e, p, "En preparacion"),
                        disabled=pedido.get("estado") != "Pendiente",
                        style=ft.ButtonStyle(
                            bgcolor={
                                "": ft.Colors.ORANGE_700,
                                "disabled": ft.Colors.GREY_800
                            },
                            color=ft.Colors.WHITE
                        ),
                        expand=True
                    ),
                    ft.Container(width=10),
                    ft.ElevatedButton(
                        "✅ Listo",
                        on_click=lambda e, p=pedido: cambiar_estado(e, p, "Listo"),
                        disabled=pedido.get("estado") != "En preparacion",
                        style=ft.ButtonStyle(
                            bgcolor={
                                "": ft.Colors.GREEN_700,
                                "disabled": ft.Colors.GREY_800
                            },
                            color=ft.Colors.WHITE
                        ),
                        expand=True
                    ),
                ], spacing=0),
                padding=10
            )
        )
        
        # Badge de estado
        controls_list.append(
            ft.Container(
                content=ft.Row([
                    ft.Icon(icono_estado, color=color_icono, size=14),
                    ft.Text(
                        f"Estado: {estado_pedido}",
                        color=color_icono,
                        size=12,
                        weight=ft.FontWeight.BOLD
                    )
                ], spacing=5),
                padding=ft.padding.only(left=10, right=10, bottom=10),
            )
        )

        # ===== CONTENEDOR PRINCIPAL CON GRADIENTE Y ANIMACIÓN =====
        card_container = ft.Container(
            content=ft.Column(controls_list, spacing=0),
            bgcolor=bg_color_pedido,
            gradient=gradient,
            padding=0,
            border_radius=10,
            border=ft.border.all(borde_width, border_color),
            animate=ft.Animation(300, "easeOut"),
            shadow=ft.BoxShadow(
                spread_radius=1,
                blur_radius=8,
                color=ft.Colors.with_opacity(0.3, ft.Colors.BLACK),
                offset=ft.Offset(0, 2),
            )
        )

        # ===== ANIMACIÓN DE HOVER =====
        def on_hover_card(e):
            if e.data == "true":
                card_container.shadow = ft.BoxShadow(
                    spread_radius=2,
                    blur_radius=15,
                    color=ft.Colors.with_opacity(0.5, border_color),
                    offset=ft.Offset(0, 4),
                )
                card_container.scale = 1.02
            else:
                card_container.shadow = ft.BoxShadow(
                    spread_radius=1,
                    blur_radius=8,
                    color=ft.Colors.with_opacity(0.3, ft.Colors.BLACK),
                    offset=ft.Offset(0, 2),
                )
                card_container.scale = 1.0
            card_container.update()

        card_container.on_hover = on_hover_card

        return card_container

    vista = ft.Container(
        content=ft.Column([
            ft.Text("Pedidos en Cocina", size=20, weight=ft.FontWeight.BOLD),
            lista_pedidos
        ]),
        padding=20,
        expand=True
    )
    vista.actualizar = actualizar
    log.info("Vista de Cocina (versión con ícono de advertencia) creada correctamente")
    return vista

def crear_vista_admin(backend_service, menu, on_update_ui, page):
    log.debug("Creando vista de Administración")
    
    tipos = list(set(item["tipo"] for item in menu))
    tipos.sort()
    
    tipo_item_admin = ft.Dropdown(
        label="Tipo de item (Agregar)",
        options=[ft.dropdown.Option(tipo) for tipo in tipos],
        value=tipos[0] if tipos else "Entradas",
        width=250,
    )
    nombre_item = ft.TextField(label="Nombre de item", width=250)
    precio_item = ft.TextField(label="Precio", width=250)
    tipo_item_eliminar = ft.Dropdown(
        label="Tipo item (Eliminar)",
        options=[ft.dropdown.Option(tipo) for tipo in tipos],
        value=tipos[0] if tipos else "Entradas",
        width=250,
    )
    item_eliminar = ft.Dropdown(label="Seleccionar item a eliminar", width=300)

    def actualizar_items_eliminar(e):
        tipo = tipo_item_eliminar.value
        items = [item for item in menu if item["tipo"] == tipo]
        item_eliminar.options = [ft.dropdown.Option(item["nombre"]) for item in items]
        item_eliminar.value = None
        page.update()
        log.debug(f"Dropdown de eliminación actualizado - Tipo: {tipo} | {len(items)} ítems")

    tipo_item_eliminar.on_change = actualizar_items_eliminar
    actualizar_items_eliminar(None)

    def agregar_item(e):
        tipo = tipo_item_admin.value
        nombre = (nombre_item.value or "").strip()
        texto_precio = (precio_item.value or "").strip().replace(",", ".")
        
        if not all([tipo, nombre, texto_precio]):
            log.warning("Intento de agregar ítem con campos vacíos")
            return
            
        try:
            precio = float(texto_precio)
            if precio <= 0:
                log.warning(f"Intento de agregar ítem con precio inválido: {precio}")
                return
        except ValueError:
            log.warning(f"Precio inválido ingresado: '{texto_precio}'")
            return

        log.info(f"Agregando ítem al menú → '{nombre}' | ${precio:.2f} | Tipo: {tipo}")
        try:
            backend_service.agregar_item_menu(nombre, precio, tipo)
            nombre_item.value = precio_item.value = ""
            page.update()
            log.info(f"Ítem agregado exitosamente → '{nombre}'")
            on_update_ui()
        except Exception as ex:
            log.error(f"Error al agregar ítem '{nombre}': {ex}")

    def eliminar_item(e):
        tipo = tipo_item_eliminar.value
        nombre = item_eliminar.value
        if not tipo or not nombre:
            log.warning("Intento de eliminar ítem sin seleccionar tipo o nombre")
            return

        log.warning(f"Eliminando ítem del menú → '{nombre}' ({tipo})")
        try:
            backend_service.eliminar_item_menu(nombre, tipo)
            item_eliminar.value = None
            actualizar_items_eliminar(None)
            log.info(f"Ítem eliminado exitosamente → '{nombre}'")
            on_update_ui()
        except Exception as ex:
            log.error(f"Error al eliminar ítem '{nombre}': {ex}")

    # === GESTIÓN DE CLIENTES ===
    nombre_cliente = ft.TextField(label="Nombre", width=300)
    domicilio_cliente = ft.TextField(label="Domicilio", width=300)
    celular_cliente = ft.TextField(
        label="Celular",
        width=300,
        input_filter=ft.NumbersOnlyInputFilter(),
        prefix_icon=ft.Icons.PHONE,
        max_length=10
    )

    lista_clientes = ft.ListView(
        expand=True,
        spacing=10,
        padding=20,
        auto_scroll=True,
    )

    def actualizar_lista_clientes():
        try:
            clientes = backend_service.obtener_clientes()
            lista_clientes.controls.clear()
            log.info(f"Cargando {len(clientes)} clientes registrados")
            for cliente in clientes:
                cliente_row = ft.Container(
                    content=ft.Column([
                        ft.Text(f"{cliente['nombre']}", size=18, weight=ft.FontWeight.BOLD),
                        ft.Text(f"Domicilio: {cliente['domicilio']}", size=14),
                        ft.Text(f"Celular: {cliente['celular']}", size=14),
                        ft.Text(f"Registrado: {cliente['fecha_registro']}", size=12, color=ft.Colors.GREY_500),
                        ft.ElevatedButton(
                            "Eliminar",
                            on_click=lambda e, id=cliente['id']: eliminar_cliente_click(id),
                            style=ft.ButtonStyle(bgcolor=ft.Colors.RED_700, color=ft.Colors.WHITE)
                        )
                    ]),
                    bgcolor=ft.Colors.BLUE_GREY_900,
                    padding=10,
                    border_radius=10
                )
                lista_clientes.controls.append(cliente_row)
            page.update()
        except Exception as e:
            log.error(f"Error crítico al cargar lista de clientes: {e}")

    def agregar_cliente_click(e):
        nombre = nombre_cliente.value.strip()
        domicilio = domicilio_cliente.value.strip()
        celular = celular_cliente.value.strip()
        
        if not all([nombre, domicilio, celular]):
            log.warning("Intento de agregar cliente con campos vacíos")
            return
        if len(celular) != 10:
            log.warning(f"Celular inválido: {celular} (debe ser 10 dígitos)")
            return

        log.info(f"Agregando cliente → {nombre} | {celular}")
        try:
            backend_service.agregar_cliente(nombre, domicilio, celular)
            nombre_cliente.value = domicilio_cliente.value = celular_cliente.value = ""
            actualizar_lista_clientes()
            log.info(f"Cliente agregado exitosamente → {nombre}")
        except Exception as ex:
            log.error(f"Error al agregar cliente '{nombre}': {ex}")

    def eliminar_cliente_click(cliente_id: int):
        log.warning(f"Eliminando cliente ID: {cliente_id}")
        try:
            backend_service.eliminar_cliente(cliente_id)
            actualizar_lista_clientes()
            log.info(f"Cliente eliminado → ID: {cliente_id}")
        except Exception as ex:
            log.error(f"Error al eliminar cliente ID {cliente_id}: {ex}")

    vista = ft.Container(
        content=ft.Column([
            ft.Text("Agregar item al menú", size=20, weight=ft.FontWeight.BOLD),
            tipo_item_admin,
            nombre_item,
            precio_item,
            ft.ElevatedButton("Agregar item", on_click=agregar_item,
                style=ft.ButtonStyle(bgcolor=ft.Colors.GREEN_700, color=ft.Colors.WHITE)),
            ft.Divider(),
            ft.Text("Eliminar item del menú", size=20, weight=ft.FontWeight.BOLD),
            tipo_item_eliminar,
            item_eliminar,
            ft.ElevatedButton("Eliminar item", on_click=eliminar_item,
                style=ft.ButtonStyle(bgcolor=ft.Colors.RED_700, color=ft.Colors.WHITE)),
            ft.Divider(),
            ft.Text("Agregar Cliente", size=20, weight=ft.FontWeight.BOLD),
            nombre_cliente,
            domicilio_cliente,
            celular_cliente,
            ft.ElevatedButton("Agregar Cliente", on_click=agregar_cliente_click,
                style=ft.ButtonStyle(bgcolor=ft.Colors.GREEN_700, color=ft.Colors.WHITE)),
            ft.Divider(),
            ft.Text("Clientes Registrados", size=20, weight=ft.FontWeight.BOLD),
            ft.Container(
                content=lista_clientes,
                expand=True,
                height=500,
                padding=10,
                border_radius=10,
            )
        ], expand=True, scroll="auto"),
        padding=20,
        expand=True
    )
    
    vista.actualizar_lista_clientes = actualizar_lista_clientes

    def actualizar_menu_admin(novo_menu):
        nonlocal menu
        menu = novo_menu
        tipos = list(set(item["tipo"] for item in menu))
        tipos.sort()
        
        tipo_item_admin.options = [ft.dropdown.Option(tipo) for tipo in tipos]
        if tipo_item_admin.value not in tipos and tipos:
             tipo_item_admin.value = tipos[0]
             
        tipo_item_eliminar.options = [ft.dropdown.Option(tipo) for tipo in tipos]
        if tipo_item_eliminar.value not in tipos and tipos:
             tipo_item_eliminar.value = tipos[0]
             
        actualizar_items_eliminar(None)

    vista.actualizar_menu = actualizar_menu_admin
    log.info("Vista de Administración creada correctamente")
    return vista

# === FUNCIÓN: crear_vista_personalizacion ===
# Crea la vista para personalizar umbrales de alerta.
def crear_vista_personalizacion(app_instance):
    log.debug("Creando vista de Personalización de Alertas")
    
    tiempo_umbral_input = ft.TextField(
        label="Tiempo umbral para pedidos (minutos)",
        value=str(app_instance.tiempo_umbral_minutos),
        width=300,
        input_filter=ft.NumbersOnlyInputFilter(),
        hint_text="Ej: 20"
    )

    def guardar_configuracion_click(e):
        log.info(f"Usuario intenta cambiar umbral de tiempo - Valor ingresado: '{tiempo_umbral_input.value}'")
        
        try:
            nuevo_tiempo_umbral = int(tiempo_umbral_input.value)

            if nuevo_tiempo_umbral <= 0:
                log.warning(f"Valor inválido para umbral: {nuevo_tiempo_umbral} (debe ser > 0)")
                def cerrar_alerta(e):
                    app_instance.page.close(dlg_error)
                
                dlg_error = ft.AlertDialog(
                    title=ft.Text("Error"),
                    content=ft.Text("El umbral de tiempo debe ser un número positivo."),
                    actions=[ft.TextButton("Aceptar", on_click=cerrar_alerta)],
                    actions_alignment=ft.MainAxisAlignment.END,
                )
                app_instance.page.dialog = dlg_error
                dlg_error.open = True
                app_instance.page.update()
                return

            # Actualizar instancia
            viejo_valor = app_instance.tiempo_umbral_minutos
            app_instance.tiempo_umbral_minutos = nuevo_tiempo_umbral
            
            # Guardar en archivo
            app_instance.guardar_configuracion()

            log.info(f"Umbral de retraso actualizado → {viejo_valor} min → {nuevo_tiempo_umbral} min")

            def cerrar_alerta_ok(e):
                app_instance.page.close(dlg_success)
            
            dlg_success = ft.AlertDialog(
                title=ft.Text("Éxito"),
                content=ft.Text("Configuración guardada correctamente."),
                actions=[ft.TextButton("Aceptar", on_click=cerrar_alerta_ok)],
                actions_alignment=ft.MainAxisAlignment.END,
            )
            app_instance.page.dialog = dlg_success
            dlg_success.open = True
            app_instance.page.update()

        except ValueError:
            log.warning(f"Entrada no numérica en umbral de tiempo: '{tiempo_umbral_input.value}'")
            def cerrar_alerta_val(e):
                app_instance.page.close(dlg_error_val)
            
            dlg_error_val = ft.AlertDialog(
                title=ft.Text("Error"),
                content=ft.Text("Por favor, ingrese un valor numérico válido para el tiempo umbral."),
                actions=[ft.TextButton("Aceptar", on_click=cerrar_alerta_val)],
                actions_alignment=ft.MainAxisAlignment.END,
            )
            app_instance.page.dialog = dlg_error_val
            dlg_error_val.open = True
            app_instance.page.update()

    vista = ft.Container(
        content=ft.Column([
            ft.Text("Personalización de Alertas", size=24, weight=ft.FontWeight.BOLD),
            ft.Divider(),
            ft.Text("Establece el umbral para las alertas de retraso de pedidos.", size=16),
            ft.Divider(),
            tiempo_umbral_input,
            ft.ElevatedButton(
                "Guardar Configuración",
                on_click=guardar_configuracion_click,
                style=ft.ButtonStyle(bgcolor=app_instance.PRIMARY, color=ft.Colors.WHITE)
            )
        ]),
        padding=20,
        expand=True
    )

    log.info("Vista de Personalización creada correctamente")
    return vista

# === CLASE: RestauranteGUI (MODIFICADA PARA ALERTAS EN TIEMPO REAL) ===
# Clase principal que maneja la interfaz gráfica y los estados del sistema.
class RestauranteGUI:
    def __init__(self):
        log.info("Iniciando RestauranteGUI - Creando instancia principal")
        self.carpeta_datos = Path.home() / ".restaurantia" / "datos"
        self.carpeta_datos.mkdir(parents=True, exist_ok=True)
        self.archivo_primera_config = self.carpeta_datos / "PRIMERA_CONFIGURACION_COMPLETADA"

        from backend_service import BackendService
        from configuraciones_service import ConfiguracionesService
        self.backend_service = BackendService()
        self.inventory_service = InventoryService()
        self.config_service = ConfiguracionesService()
        self.recetas_service = RecetasService()
        self.page = None
        self.mesas_grid = None
        self.panel_gestion = None
        self.vista_cocina = None
        self.vista_caja = None
        self.vista_admin = None
        self.vista_inventario = None
        self.vista_recetas = None
        self.vista_configuraciones = None
        self.vista_reportes = None
        self.vista_personalizacion = None
        self.menu_cache = None
        self.hilo_sincronizacion = None
        
        # Alertas de stock
        self.hilo_verificacion_stock = None  # Eliminado en la nueva versión
        self.hay_stock_bajo = False
        self.ingredientes_bajos_lista = []
        self.mostrar_detalle_stock = False
        
        # Alertas de retrasos
        self.hilo_verificacion_retrasos = None  # Eliminado en la nueva versión
        self.lista_alertas_retrasos = []
        self.hay_pedidos_atrasados = False
        self.mostrar_detalle_retrasos = False
        
        # Configuración
        self.tiempo_umbral_minutos = 20
        self.umbral_stock_bajo = 5  # Este se usará como fallback si no hay umbral personalizado

        self.menu_cache = None
        # === NUEVO: Caché para optimización de mesas ===
        self.mesas_cache = {}  # {numero_mesa: datos_mesa}
        self.mesas_widgets_cache = {}  # {numero_mesa: ft.Container}
        
        # Colores
        self.PRIMARY = "#6366f1"
        self.PRIMARY_DARK = "#4f46e5"
        self.ACCENT = "#f59e0b"
        self.SUCCESS = "#10b981"
        self.DANGER = "#ef4444"
        self.CARD_BG = "#1a1f35"
        self.CARD_HOVER = "#252b45"
        
        self.reservas_service = ReservasService()
        self.vista_reservas = None
        
        # Atributos para control de verificación en tiempo real
        self.ultimo_check_stock = 0
        self.ultimo_check_retrasos = 0
        self.stock_actual = {}
        self.pedidos_activos_actual = {}
        
        # Cargar configuración al inicio
        self.cargar_configuracion()
        log.info("RestauranteGUI inicializado correctamente")

    # --- FUNCIÓN: cargar_configuracion ---
    def cargar_configuracion(self):
        log.debug("Cargando configuración desde archivo local")
        import json
        from pathlib import Path
        carpeta_datos = Path.home() / ".restaurantia" / "datos"
        carpeta_datos.mkdir(parents=True, exist_ok=True)
        archivo_config = carpeta_datos / "config.json"
        if archivo_config.exists():
            try:
                with open(archivo_config, "r", encoding="utf-8") as f:
                    config = json.load(f)
                self.tiempo_umbral_minutos = config.get("tiempo_umbral_minutos", 20)
                self.umbral_stock_bajo = config.get("umbral_stock_bajo", 5)
                log.info(f"Configuración cargada → Umbral retraso: {self.tiempo_umbral_minutos} min | Umbral stock: {self.umbral_stock_bajo}")
            except Exception as e:
                log.error(f"Error al leer config.json: {e} → Usando valores por defecto")
                self.tiempo_umbral_minutos = 20
                self.umbral_stock_bajo = 5
        else:
            log.info("config.json no existe → Creando con valores por defecto")
            self.guardar_configuracion()

    # --- FUNCIÓN: guardar_configuracion ---
    def guardar_configuracion(self):
        log.debug("Guardando configuración en archivo local")
        import json
        from pathlib import Path
        carpeta_datos = Path.home() / ".restaurantia" / "datos"
        carpeta_datos.mkdir(parents=True, exist_ok=True)
        archivo_config = carpeta_datos / "config.json"
        config = {
            "tiempo_umbral_minutos": self.tiempo_umbral_minutos,
            "umbral_stock_bajo": self.umbral_stock_bajo
        }
        try:
            with open(archivo_config, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=4)
            log.info(f"Configuración guardada → {archivo_config}")
        except Exception as e:
            log.error(f"Error crítico al guardar configuración: {e}")

    # === FUNCIÓN: verificar_stock_real_time (CORREGIDA) ===
    def verificar_stock_real_time(self):
        """Verifica stock en tiempo real detectando cambios de valor Y eliminaciones."""
        try:
            items = self.inventory_service.obtener_inventario()
            nuevo_stock = {item['id']: item for item in items}
            
            # 1. Detectar cambios en la ESTRUCTURA (ítems nuevos o ELIMINADOS)
            ids_anteriores = set(self.stock_actual.keys())
            ids_nuevos = set(nuevo_stock.keys())
            
            # Si los sets de IDs son diferentes, es que se agregó o SE ELIMINÓ algo.
            cambio_estructural = ids_anteriores != ids_nuevos

            # 2. Detectar cambios en los VALORES de los ítems que persisten
            cambio_valor = False
            if not cambio_estructural:
                for item_id, item in nuevo_stock.items():
                    if item_id in self.stock_actual:
                        # Comparar cantidad y umbral
                        cant_old = self.stock_actual[item_id].get('cantidad_disponible')
                        cant_new = item.get('cantidad_disponible')
                        umbral_old = self.stock_actual[item_id].get('cantidad_minima_alerta', 5.0)
                        umbral_new = item.get('cantidad_minima_alerta', 5.0)
                        
                        if cant_old != cant_new or umbral_old != umbral_new:
                            cambio_valor = True
                            break
            
            # Si hubo CUALQUIER cambio (estructura o valores), recalculamos las alertas
            if cambio_estructural or cambio_valor:
                log.debug("Cambio en inventario detectado (valor o eliminación) -> Recalculando alertas")
                
                # Verificar stock bajo usando el umbral personalizado de cada ítem
                ingredientes_bajos = []
                for item in items:
                    # Usar el umbral personalizado, fallback al general si hiciera falta
                    umbral = item.get('cantidad_minima_alerta', self.umbral_stock_bajo)
                    if item['cantidad_disponible'] <= umbral:
                        ingredientes_bajos.append(item)
                
                # Actualizar estado de alertas
                if ingredientes_bajos:
                    nombres = ", ".join([item['nombre'] for item in ingredientes_bajos])
                    self.hay_stock_bajo = True
                    self.ingredientes_bajos_lista = [item['nombre'] for item in ingredientes_bajos]
                    if cambio_estructural: # Log solo si fue algo estructural para no saturar
                        log.warning(f"STOCK BAJO ACTUALIZADO → {len(ingredientes_bajos)} ingredientes: {nombres}")
                else:
                    # Si antes había alerta y ahora no (porque se borró el ítem o se rellenó), limpiamos
                    if self.hay_stock_bajo:
                        log.info("Stock bajo resuelto (alerta limpiada)")
                        self.hay_stock_bajo = False
                        self.ingredientes_bajos_lista = []
                        self.mostrar_detalle_stock = False
                
                # Actualizar cache
                self.stock_actual = nuevo_stock
                
                # Actualizar visibilidad de alertas inmediatamente
                if hasattr(self, 'actualizar_visibilidad_alerta'):
                    self.actualizar_visibilidad_alerta()
                    
        except Exception as e:
            log.error(f"Error en verificación de stock en tiempo real: {e}")

            
    def verificar_retrasos_real_time(self):
        """Verifica retrasos en tiempo real - FUNCIONA SIEMPRE aunque el backend no devuelva updated_at"""
        try:
            pedidos_activos = self.backend_service.obtener_pedidos_activos()
            ahora = datetime.now()

            # Forzar detección de cambios usando ID + estado + items (infalible)
            nuevo_hash = {}
            for p in pedidos_activos:
                items_str = str(sorted([f"{i['nombre']}{i['precio']}" for i in p.get('items', [])]))
                clave = f"{p['id']}_{p.get('estado','')}_{items_str}"
                nuevo_hash[p['id']] = clave

            # Detectar cualquier cambio (aunque no haya updated_at)
            cambios_detectados = (
                set(nuevo_hash.keys()) != set(self.pedidos_activos_actual.keys()) or
                any(nuevo_hash.get(pid) != self.pedidos_activos_actual.get(pid) for pid in nuevo_hash)
            )

            if not cambios_detectados and self.pedidos_activos_actual:
                return  # Solo si realmente no cambió nada

            # === AQUÍ SÍ ENTRA SIEMPRE QUE HAYA UN PEDIDO NUEVO O CAMBIO ===

            activos_relevantes = [
                p for p in pedidos_activos
                if p.get('estado') in ["Pendiente", "En preparacion"] and p.get('items')
            ]

            alertas_nuevas = []
            for pedido in activos_relevantes:
                try:
                    fecha_str = str(pedido.get('fecha_hora', '')).split('.')[0]
                    if not fecha_str or len(fecha_str) < 10:
                        continue
                    fecha_pedido = datetime.strptime(fecha_str, "%Y-%m-%d %H:%M:%S")
                    minutos_transcurridos = (ahora - fecha_pedido).total_seconds() / 60

                    if minutos_transcurridos >= self.tiempo_umbral_minutos:
                        titulo = obtener_titulo_pedido(pedido)
                        alertas_nuevas.append({
                            "id_pedido": pedido['id'],
                            "titulo_pedido": titulo,
                            "estado": pedido['estado'],
                            "tiempo_retraso": round(minutos_transcurridos, 1)
                        })
                        log.warning(f"ALERTA RETRASO → {titulo} | {minutos_transcurridos:.1f} min (umbral: {self.tiempo_umbral_minutos})")

                except Exception as e:
                    log.error(f"Error procesando pedido {pedido.get('id')} para retraso: {e}")

            self.lista_alertas_retrasos = alertas_nuevas
            self.hay_pedidos_atrasados = len(alertas_nuevas) > 0
            self.pedidos_activos_actual = nuevo_hash

            if hasattr(self, 'actualizar_visibilidad_alerta'):
                self.actualizar_visibilidad_alerta()

        except Exception as e:
            log.error(f"Error crítico en verificar_retrasos_real_time: {e}")

    # === FUNCIÓN: verificar_todo_real_time (nueva función central) ===
    def verificar_todo_real_time(self):
        """Verifica todo en tiempo real - Se llama cada vez que se actualiza la UI"""
        # Verificar stock
        self.verificar_stock_real_time()
        # Verificar retrasos  
        self.verificar_retrasos_real_time()

    def iniciar_sincronizacion(self):
        """Inicia la sincronización automática en segundo plano."""
        log.info("Iniciando hilos de sincronización automática")
        
        def actualizar_periodicamente():
            while True:
                try:
                    # Verificar alertas en tiempo real ANTES de actualizar la UI
                    self.verificar_todo_real_time()
                    # Ahora actualizar la UI con los estados de alerta actualizados
                    self.actualizar_ui_completo()
                    time.sleep(3)
                except Exception as e:
                    log.error(f"Error crítico en hilo de sincronización UI: {e}")
                    time.sleep(3)
        
        # Hilo principal de UI
        self.hilo_sincronizacion = threading.Thread(target=actualizar_periodicamente, daemon=True)
        self.hilo_sincronizacion.start()
        log.info("Hilo de sincronización UI iniciado (cada 3s) con verificación de alertas en tiempo real")
        
        # NOTA: Ya no iniciamos los hilos separados de verificación periódica
        # porque ahora se hace en el mismo hilo de actualización de UI

    def main(self, page: ft.Page):
        log.info("main() ejecutado - Iniciando interfaz gráfica RestIA")
        self.page = page
        page.title = "RestIA"
        page.padding = 0
        page.theme_mode = "dark"
        page.bgcolor = "#0a0e1a"
        
        # Asignar la instancia a la página para acceso desde vistas
        page.app_instance = self
        
        reloj = ft.Text("", size=14, weight=ft.FontWeight.BOLD, color=ft.Colors.AMBER_200)
        
        # =================================================================
        # === ASISTENTE DE PRIMERA CONFIGURACIÓN (SOLO SE MUESTRA 1 VEZ) ===
        # =================================================================
        if not self.archivo_primera_config.exists():
            page.title = "RestIA - Configuración Inicial"
            page.bgcolor = "#0f172a"
            from bienvenida_view import BienvenidaConfiguracion
            page.views.clear()
            page.views.append(BienvenidaConfiguracion(self, page).vista)
            page.update()
            log.info("PRIMERA VEZ - Mostrando asistente de configuración inicial")
            return  # ¡¡SUPER IMPORTANTE!! No ejecutar nada más
        # =================================================================
        # === CONFIGURACIÓN YA REALIZADA → CARGAR SISTEMA NORMAL ===
        # =================================================================
        
        log.info("Configuración previa detectada - Cargando sistema completo")
        
        # === CARGA INICIAL DEL MENÚ ===
        try:
            self.menu_cache = self.backend_service.obtener_menu()
            log.info(f"Menú cargado desde backend → {len(self.menu_cache)} ítems")
        except Exception as e:
            log.error(f"Error al cargar menú al iniciar: {e}")
            self.menu_cache = []
        
        # === INDICADORES DE ALERTA ===
        indicador_stock_bajo = ft.Container(
            content=ft.Row([
                ft.Icon(ft.Icons.WARNING, color=ft.Colors.WHITE, size=20),
                ft.Text("Stock Bajo", color=ft.Colors.WHITE, size=14, weight=ft.FontWeight.BOLD)
            ], alignment=ft.MainAxisAlignment.CENTER, spacing=5),
            bgcolor=self.DANGER,
            padding=5,
            border_radius=5,
            width=120,
            height=30,
            visible=False,
            ink=True,
            on_click=self.toggle_detalle_stock_bajo
        )
        indicador_retrasos = ft.Container(
            content=ft.Row([
                ft.Icon(ft.Icons.ALARM, color=ft.Colors.WHITE, size=20),
                ft.Text("Retrasos", color=ft.Colors.WHITE, size=14, weight=ft.FontWeight.BOLD)
            ], alignment=ft.MainAxisAlignment.CENTER, spacing=5),
            bgcolor=self.ACCENT,
            padding=5,
            border_radius=5,
            width=120,
            height=30,
            visible=False,
            ink=True,
            on_click=self.toggle_detalle_retrasos
        )
        panel_detalle_stock = ft.Container(
            content=ft.Column([
                ft.Text("Ingredientes con bajo stock:", size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                ft.ListView(controls=[], spacing=2, padding=5, height=100, width=200, auto_scroll=False)
            ], spacing=5),
            bgcolor=self.CARD_BG,
            padding=10,
            border_radius=5,
            visible=False,
            width=220,
        )
        panel_detalle_retrasos = ft.Container(
            content=ft.Column([
                ft.Text("Pedidos con retraso:", size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                ft.ListView(controls=[], spacing=2, padding=5, height=100, width=200, auto_scroll=False)
            ], spacing=5),
            bgcolor=self.CARD_BG,
            padding=10,
            border_radius=5,
            visible=False,
            width=220,
        )
        
        # === RELOJ EN VIVO ===
        def actualizar_reloj():
            reloj.value = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            page.update()
        def loop_reloj():
            while True:
                actualizar_reloj()
                time.sleep(1)
        hilo_reloj = threading.Thread(target=loop_reloj, daemon=True)
        hilo_reloj.start()
        log.info("Hilo del reloj en vivo iniciado")
        
        # === CARGA INICIAL DEL MENÚ ===
        try:
            self.menu_cache = self.backend_service.obtener_menu()
            log.info(f"Menú cargado desde backend → {len(self.menu_cache)} ítems")
        except Exception as e:
            log.error(f"Error al cargar menú al iniciar: {e}")
            self.menu_cache = []
        
        # === CREACIÓN DE TODAS LAS VISTAS ===
        log.debug("Creando todas las vistas de la aplicación")
        self.mesas_grid = crear_mesas_grid(self.backend_service, self.seleccionar_mesa, self)
        self.panel_gestion = crear_panel_gestion(
            self.backend_service, self.menu_cache, self.actualizar_ui_completo,
            page, self.PRIMARY, self.PRIMARY_DARK
        )
        self.vista_cocina = crear_vista_cocina(self.backend_service, self.actualizar_ui_completo, page)
        self.vista_caja = crear_vista_caja(self.backend_service, self.actualizar_ui_completo, page)
        self.vista_admin = crear_vista_admin(self.backend_service, self.menu_cache, self.actualizar_ui_completo, page)
        self.vista_recetas = crear_vista_recetas(
            self.recetas_service, self.backend_service, self.inventory_service,
            self.actualizar_ui_completo, page
        )
        self.vista_inventario = crear_vista_inventario(self.inventory_service, self.actualizar_ui_completo, page)
        self.vista_configuraciones = crear_vista_configuraciones(
            self.config_service, self.inventory_service, self.backend_service,
            self.actualizar_ui_completo, page
        )
        self.vista_reportes = crear_vista_reportes(self.backend_service, self.actualizar_ui_completo, page)
        self.vista_reservas = crear_vista_reservas(
            self.reservas_service, self.backend_service, self.backend_service,
            self.actualizar_ui_completo, page
        )
        self.vista_personalizacion = crear_vista_personalizacion(self)
        
        log.info("Todas las vistas creadas correctamente - Aplicación lista")
        
        tabs = ft.Tabs(
            selected_index=0,
            animation_duration=300,
            tabs=[
                ft.Tab(text="Mesera", icon=ft.Icons.PERSON, content=self.crear_vista_mesera()),
                ft.Tab(text="Cocina", icon=ft.Icons.RESTAURANT, content=self.vista_cocina),
                ft.Tab(text="Caja", icon=ft.Icons.POINT_OF_SALE, content=self.vista_caja),
                ft.Tab(text="Administracion", icon=ft.Icons.ADMIN_PANEL_SETTINGS, content=self.vista_admin),
                ft.Tab(text="Inventario", icon=ft.Icons.INVENTORY_2, content=self.vista_inventario),
                ft.Tab(text="Recetas", icon=ft.Icons.BOOKMARK_BORDER, content=self.vista_recetas),
                ft.Tab(text="Configuraciones", icon=ft.Icons.SETTINGS, content=self.vista_configuraciones),
                ft.Tab(text="Personalización", icon=ft.Icons.TUNE, content=self.vista_personalizacion),
                ft.Tab(text="Reservas", icon=ft.Icons.CALENDAR_TODAY, content=self.vista_reservas),
                ft.Tab(text="Reportes", icon=ft.Icons.ANALYTICS, content=self.vista_reportes),
            ],
            expand=1
        )
        
        log.info("Pestañas principales creadas - 10 módulos activos")
        
        def actualizar_visibilidad_alerta():
            # Stock bajo
            indicador_stock_bajo.visible = self.hay_stock_bajo
            panel_detalle_stock.visible = self.hay_stock_bajo and self.mostrar_detalle_stock
            lista_detalle_stock = panel_detalle_stock.content.controls[1]
            lista_detalle_stock.controls.clear()
            if self.hay_stock_bajo:
                for ing in self.ingredientes_bajos_lista:
                    lista_detalle_stock.controls.append(ft.Text(f"- {ing}", size=12, color=ft.Colors.WHITE))
            log.debug(f"Indicador Stock Bajo activado → {len(self.ingredientes_bajos_lista)} ingredientes")
            
            # Retrasos
            indicador_retrasos.visible = self.hay_pedidos_atrasados
            panel_detalle_retrasos.visible = self.hay_pedidos_atrasados and self.mostrar_detalle_retrasos
            lista_detalle_retrasos = panel_detalle_retrasos.content.controls[1]
            lista_detalle_retrasos.controls.clear()
            if self.hay_pedidos_atrasados:
                for alerta in self.lista_alertas_retrasos:
                    lista_detalle_retrasos.controls.append(
                        ft.Text(f"- {alerta['titulo_pedido']} ({alerta['tiempo_retraso']} min)", size=12, color=ft.Colors.WHITE)
                    )
            log.debug(f"Indicador Retrasos activado → {len(self.lista_alertas_retrasos)} pedidos atrasados")
            
            page.update()
        
        page.add(
            ft.Stack(
                controls=[
                    tabs,
                    ft.Container(
                        content=ft.Column([
                            ft.Row([
                                indicador_stock_bajo,
                                ft.Text("   ", width=10),
                                indicador_retrasos,
                            ], alignment=ft.MainAxisAlignment.START),
                            ft.Container(
                                content=ft.Column([panel_detalle_stock, panel_detalle_retrasos])
                            )
                        ], spacing=5),
                        top=10,
                        right=10,
                    ),
                    ft.Container(
                        content=reloj,
                        right=20,
                        bottom=50,
                        padding=10,
                        bgcolor=ft.Colors.BLUE_GREY_900,
                        border_radius=8,
                    )
                ],
                expand=True
            )
        )
        
        log.info("Interfaz gráfica principal renderizada - Stack con pestañas y alertas")
        
        # INICIAR TODO
        self.iniciar_sincronizacion()
        self.actualizar_ui_completo()
        actualizar_visibilidad_alerta()
        self.actualizar_visibilidad_alerta = actualizar_visibilidad_alerta
        log.info("¡APLICACIÓN RESTIA INICIADA CORRECTAMENTE! - Todo listo y funcionando")
        log.info("=" * 60)

    def crear_vista_mesera(self):
        log.debug("Creando vista Mesera")
        return ft.Container(
            content=ft.Row(
                controls=[
                    ft.Column(
                        controls=[
                            ft.Text("Mesas del restaurante", size=20, weight=ft.FontWeight.BOLD),
                            self.mesas_grid
                        ],
                        expand=True
                    ),
                    ft.VerticalDivider(),
                    ft.Container(
                        width=400,
                        content=self.panel_gestion,
                        expand=True
                    )
                ],
                expand=True
            ),
            expand=True
        )

    def seleccionar_mesa(self, numero_mesa: int):
        log.info(f"Usuario seleccionó Mesa {numero_mesa}")
        if self.panel_gestion:
            self.panel_gestion.seleccionar_mesa(numero_mesa)

    def actualizar_ui_completo(self):
        log.debug("↻ actualizar_ui_completo() llamado - Iniciando refresco completo de UI")
        
        try:
            self.menu_cache = self.backend_service.obtener_menu()
            if self.panel_gestion and hasattr(self.panel_gestion, 'actualizar_menu'):
                self.panel_gestion.actualizar_menu(self.menu_cache)
            if self.vista_admin and hasattr(self.vista_admin, 'actualizar_menu'):
                self.vista_admin.actualizar_menu(self.menu_cache)
            log.debug(f"Menú recargado y propagado: {len(self.menu_cache)} ítems")
        except Exception as e:
            log.error(f"Error al recargar menú: {e}")

        nuevo_grid = crear_mesas_grid(self.backend_service, self.seleccionar_mesa, self)
        self.mesas_grid.controls = nuevo_grid.controls
        self.mesas_grid.update()
        log.debug("Grid de mesas recreado y actualizado")
        
        if hasattr(self.vista_cocina, 'actualizar'):
            self.vista_cocina.actualizar()
        log.debug("Vista Cocina actualizada")
        
        if hasattr(self.vista_caja, 'actualizar'):
            self.vista_caja.actualizar()
        log.debug("Vista Caja actualizada")
        
        if hasattr(self.vista_admin, 'actualizar_lista_clientes'):
            self.vista_admin.actualizar_lista_clientes()
        log.debug("Lista de clientes en Administración actualizada")
        
        if hasattr(self.vista_recetas, 'actualizar_datos'):
            self.vista_recetas.actualizar_datos()
        log.debug("Vista Recetas actualizada")
        
        if hasattr(self.vista_inventario, 'actualizar_lista'):
            self.vista_inventario.actualizar_lista()
        log.debug("Lista de inventario actualizada")
        
        if hasattr(self, 'actualizar_visibilidad_alerta'):
            self.actualizar_visibilidad_alerta()
        log.debug("Visibilidad de alertas de stock y retrasos actualizada")
        
        self.page.update()
        log.debug("page.update() ejecutado - UI refrescada completamente")
        
        if hasattr(self.vista_reservas, 'cargar_clientes'):
            self.vista_reservas.cargar_clientes()
        log.debug("Vista Reservas lista para actualizar (método disponible)")
        
        log.info("✓ Actualización completa de UI finalizada con éxito")

    # --- FUNCIÓN: actualizar_lista_inventario ---
    def actualizar_lista_inventario(self):
        """Llama a actualizar_lista de la vista de inventario solo si no hay campo en edición."""
        log.debug("actualizar_lista_inventario() llamado")
        if hasattr(self.vista_inventario, 'campo_en_edicion_id') and hasattr(self.vista_inventario, 'actualizar_lista'):
            if getattr(self.vista_inventario, 'campo_en_edicion_id', None) is not None:
                log.info("Actualización de inventario omitida: hay un campo en edición activa")
                print("Hay un campo en edición en la vista de inventario, se omite la actualización.")
                return
        if hasattr(self.vista_inventario, 'actualizar_lista'):
            self.vista_inventario.actualizar_lista()
        log.debug("Lista de inventario forzada a actualizar (sin edición activa)")

    # --- NUEVA FUNCIÓN: toggle_detalle_stock_bajo ---
    def toggle_detalle_stock_bajo(self, e):
        """Alterna la visibilidad del panel de detalles de stock bajo."""
        self.mostrar_detalle_stock = not self.mostrar_detalle_stock
        log.info(f"Detalle de stock bajo {'MOSTRADO' if self.mostrar_detalle_stock else 'OCULTADO'} por el usuario")
        self.actualizar_ui_completo()

    # --- NUEVA FUNCIÓN: toggle_detalle_retrasos ---
    def toggle_detalle_retrasos(self, e):
        """Alterna la visibilidad del panel de detalles de pedidos retrasados."""
        self.mostrar_detalle_retrasos = not self.mostrar_detalle_retrasos
        log.info(f"Detalle de retrasos {'MOSTRADO' if self.mostrar_detalle_retrasos else 'OCULTADO'} por el usuario")
        self.actualizar_ui_completo()

    # === FUNCIÓN: crear_vista_personalizacion ===
    def crear_vista_personalizacion(self, app_instance):
        """
        Crea la vista de personalización para umbrales de alerta.
        Args:
            app_instance (RestauranteGUI): Instancia de la aplicación principal.
        Returns:
            ft.Container: Contenedor con la interfaz de personalización.
        """
        log.debug("Creando vista de Personalización de Alertas")
        tiempo_umbral_input = ft.TextField(
            label="Tiempo umbral para pedidos (minutos)",
            value=str(app_instance.tiempo_umbral_minutos),
            width=300,
            input_filter=ft.NumbersOnlyInputFilter(),
            hint_text="Ej: 20"
        )
        stock_umbral_input = ft.TextField(
            label="Cantidad umbral para stock bajo",
            value=str(app_instance.umbral_stock_bajo),
            width=300,
            input_filter=ft.NumbersOnlyInputFilter(),
            hint_text="Ej: 5"
        )

        def guardar_configuracion_click(e):
            """Guarda los nuevos umbrales ingresados."""
            log.info("Usuario hizo clic en 'Guardar Configuración' en Personalización")
            try:
                nuevo_tiempo_umbral = int(tiempo_umbral_input.value)
                nuevo_stock_umbral = int(stock_umbral_input.value)
                if nuevo_tiempo_umbral <= 0 or nuevo_stock_umbral < 0:
                    log.warning(f"Intento de guardar umbrales inválidos → Tiempo: {nuevo_tiempo_umbral} | Stock: {nuevo_stock_umbral}")
                    def cerrar_alerta(e):
                        app_instance.page.close(dlg_error)
                    dlg_error = ft.AlertDialog(
                        title=ft.Text("Error"),
                        content=ft.Text("Los umbrales deben ser números positivos (tiempo > 0, stock ≥ 0)."),
                        actions=[ft.TextButton("Aceptar", on_click=cerrar_alerta)],
                    )
                    app_instance.page.dialog = dlg_error
                    dlg_error.open = True
                    app_instance.page.update()
                    return

                viejo_tiempo = app_instance.tiempo_umbral_minutos
                viejo_stock = app_instance.umbral_stock_bajo
                app_instance.tiempo_umbral_minutos = nuevo_tiempo_umbral
                app_instance.umbral_stock_bajo = nuevo_stock_umbral
                app_instance.guardar_configuracion()
                log.info(f"CONFIGURACIÓN ACTUALIZADA → Tiempo: {viejo_tiempo}→{nuevo_tiempo_umbral} min | Stock: {viejo_stock}→{nuevo_stock_umbral}")

                def cerrar_alerta_ok(e):
                    app_instance.page.close(dlg_success)
                dlg_success = ft.AlertDialog(
                    title=ft.Text("¡Éxito!", color=ft.Colors.GREEN),
                    content=ft.Text("Configuración guardada correctamente.", color=ft.Colors.GREEN_200),
                    actions=[ft.TextButton("Aceptar", on_click=cerrar_alerta_ok)],
                )
                app_instance.page.dialog = dlg_success
                dlg_success.open = True
                app_instance.page.update()
            except ValueError as ve:
                log.error(f"Error de conversión en personalización: {tiempo_umbral_input.value} | {stock_umbral_input.value}")
                def cerrar_alerta_val(e):
                    app_instance.page.close(dlg_error_val)
                dlg_error_val = ft.AlertDialog(
                    title=ft.Text("Error"),
                    content=ft.Text("Por favor, ingrese solo números enteros."),
                    actions=[ft.TextButton("Aceptar", on_click=cerrar_alerta_val)],
                )
                app_instance.page.dialog = dlg_error_val
                dlg_error_val.open = True
                app_instance.page.update()

        vista = ft.Container(
            content=ft.Column([
                ft.Text("Personalización de Alertas", size=24, weight=ft.FontWeight.BOLD),
                ft.Divider(),
                ft.Text("Establece los umbrales para las alertas de retraso de pedidos y bajo stock.", size=16),
                ft.Divider(),
                tiempo_umbral_input,
                stock_umbral_input,
                ft.ElevatedButton(
                    "Guardar Configuración",
                    on_click=guardar_configuracion_click,
                    style=ft.ButtonStyle(bgcolor=app_instance.PRIMARY, color=ft.Colors.WHITE)
                )
            ]),
            padding=20,
            expand=True
        )
        log.info("Vista de Personalización creada y lista")
        return vista


def main():
    log.info("Iniciando aplicación RestIA - Llamando a ft.app()")
    app = RestauranteGUI()
    ft.app(target=app.main)


if __name__ == "__main__":
    log.info("Ejecución directa detectada (__main__) - Arrancando RestIA")
    main()