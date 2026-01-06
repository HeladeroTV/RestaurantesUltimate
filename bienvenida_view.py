# bienvenida_view.py
import flet as ft
from pathlib import Path

class BienvenidaConfiguracion:
    def __init__(self, app_instance, page):
        self.app = app_instance
        self.page = page
        self.mesas = []
        self.categorias = []  # Lista de dicts: {"nombre": "Bebidas", "platillos": []}
        self.vista = self.crear_vista()

    def crear_vista(self):
        # === PASO 1: MESAS ===
        lista_mesas = ft.Column(scroll="auto", height=250)
        
        def agregar_mesa(e):
            try:
                num = int(txt_numero.value)
                cap = int(txt_capacidad.value)
                if num > 0 and cap > 0 and num not in [m["numero"] for m in self.mesas]:
                    self.mesas.append({"numero": num, "capacidad": cap})
                    lista_mesas.controls.append(
                        ft.ListTile(
                            title=ft.Text(f"Mesa {num}"),
                            subtitle=ft.Text(f"Capacidad: {cap} personas"),
                            trailing=ft.IconButton(ft.Icons.DELETE, on_click=lambda e, n=num: eliminar_mesa(n))
                        )
                    )
                    txt_numero.value = ""
                    txt_capacidad.value = ""
                    self.page.update()
            except: pass
        
        def eliminar_mesa(numero):
            self.mesas = [m for m in self.mesas if m["numero"] != numero]
            self.actualizar_lista_mesas(lista_mesas)
        
        txt_numero = ft.TextField(label="Número de mesa", width=120)
        txt_capacidad = ft.TextField(label="Capacidad", width=120, input_filter=ft.NumbersOnlyInputFilter())
        
        # === PASO 2: CATEGORÍAS Y PLATILLOS ===
        lista_categorias = ft.Column(scroll="auto", height=400)
        
        txt_categoria = ft.TextField(label="Nueva categoría", width=300)
        
        def agregar_categoria(e):
            cat = txt_categoria.value.strip()
            if cat and cat not in [c["nombre"] for c in self.categorias]:
                self.categorias.append({"nombre": cat, "platillos": []})
                txt_categoria.value = ""
                self.actualizar_lista_categorias(lista_categorias)
        
        def agregar_platillo(e, categoria_nombre):
            nombre = e.control.parent.controls[0].value.strip()
            precio = e.control.parent.controls[1].value.strip()
            if nombre and precio:
                try:
                    precio_float = float(precio)
                    for cat in self.categorias:
                        if cat["nombre"] == categoria_nombre:
                            cat["platillos"].append({"nombre": nombre, "precio": precio_float})
                            e.control.parent.controls[0].value = ""
                            e.control.parent.controls[1].value = ""
                            self.actualizar_lista_categorias(lista_categorias)
                            break
                except: pass
        
        def eliminar_categoria(self, cat_nombre, lista):
            self.categorias = [c for c in self.categorias if c["nombre"] != cat_nombre]
            self.actualizar_lista_categorias(lista)
        
        # === FINALIZAR ===
        def finalizar(e):
            if not self.mesas:
                self.mostrar_error("Debes agregar al menos una mesa")
                return
            if not self.categorias:
                self.mostrar_error("Debes agregar al menos una categoría")
                return
            
            try:
                # Limpiar datos antiguos
                self.app.backend_service._request("delete", "/mesas/limpiar_fisicas")
                self.app.backend_service._request("delete", "/menu/todo")
                
                # Insertar mesas
                for mesa in self.mesas:
                    self.app.backend_service.crear_mesa(mesa["numero"], mesa["capacidad"])
                
                # Insertar menú
                for cat in self.categorias:
                    for platillo in cat["platillos"]:
                        self.app.backend_service.agregar_item_menu(
                            nombre=platillo["nombre"],
                            precio=platillo["precio"],
                            tipo=cat["nombre"]
                        )
                
                # Marcar como configurado
                carpeta = Path.home() / ".restaurantia" / "datos"
                carpeta.mkdir(parents=True, exist_ok=True)
                (carpeta / "PRIMERA_CONFIGURACION_COMPLETADA").write_text("SI")
                
                self.page.snack_bar = ft.SnackBar(ft.Text("¡Configuración completada! Bienvenido a RestIA"), bgcolor=ft.Colors.GREEN_700)
                self.page.snack_bar.open = True
                self.page.update()
                
                # RECARGAR SISTEMA
                self.app.actualizar_ui_completo()
                self.page.go("/")  # O recargar la app normal
                
            except Exception as ex:
                self.mostrar_error(f"Error: {ex}")
        
        # === VISTA FINAL ===
        return ft.View(
            "/",
            [
                ft.Container(
                    content=ft.Column([
                        ft.Text("¡Bienvenido a RestIA!", size=36, weight=ft.FontWeight.BOLD, text_align="center"),
                        ft.Text("Configuración inicial del sistema", size=20, text_align="center"),
                        ft.Divider(height=40),
                        
                        ft.Text("1. Configura tus mesas", size=22, weight=ft.FontWeight.BOLD),
                        ft.Row([txt_numero, txt_capacidad, ft.ElevatedButton("Agregar", on_click=agregar_mesa)]),
                        ft.Container(lista_mesas, bgcolor=ft.Colors.BLUE_GREY_900, padding=20, border_radius=10),
                        
                        ft.Divider(height=40),
                        ft.Text("2. Configura categorías y platillos", size=22, weight=ft.FontWeight.BOLD),
                        ft.Row([txt_categoria, ft.ElevatedButton("Agregar categoría", on_click=agregar_categoria)]),
                        ft.Container(lista_categorias, bgcolor=ft.Colors.BLUE_GREY_900, padding=20, border_radius=10),
                        
                        ft.Divider(height=40),
                        ft.ElevatedButton(
                            "¡FINALIZAR Y EMPEZAR!",
                            icon=ft.Icons.CHECK_CIRCLE_OUTLINE,
                            height=60,
                            style=ft.ButtonStyle(bgcolor=ft.Colors.GREEN_700),
                            on_click=finalizar
                        )
                    ], scroll="auto"),
                    padding=40,
                    expand=True
                )
            ]
        )
    
    def actualizar_lista_mesas(self, lista):
        lista.controls.clear()
        for mesa in self.mesas:
            lista.controls.append(
                ft.ListTile(
                    title=ft.Text(f"Mesa {mesa['numero']}"),
                    subtitle=ft.Text(f"Capacidad: {mesa['capacidad']} personas"),
                    trailing=ft.IconButton(ft.Icons.DELETE, on_click=lambda e, n=mesa['numero']: self.eliminar_mesa(n, lista))
                )
            )
        self.page.update()
    
    def eliminar_mesa(self, numero, lista):
        self.mesas = [m for m in self.mesas if m["numero"] != numero]
        self.actualizar_lista_mesas(lista)
    
    def actualizar_lista_categorias(self, lista):
        lista.controls.clear()
        
        def agregar_platillo_local(e, categoria_nombre):
            # Buscar los TextField en el Row del botón
            row = e.control.parent
            nombre_field = row.controls[0]
            precio_field = row.controls[1]
            
            nombre = nombre_field.value.strip()
            precio_str = precio_field.value.strip()
            
            if not nombre or not precio_str:
                return
                
            try:
                precio = float(precio_str)
                # Agregar platillo a la categoría
                for cat in self.categorias:
                    if cat["nombre"] == categoria_nombre:
                        cat["platillos"].append({"nombre": nombre, "precio": precio})
                        nombre_field.value = ""
                        precio_field.value = ""
                        self.actualizar_lista_categorias(lista)  # Recargar
                        self.page.update()
                        break
            except ValueError:
                pass

        for cat in self.categorias:
            platillos_col = ft.Column()
            for p in cat["platillos"]:
                platillos_col.controls.append(
                    ft.Text(f"• {p['nombre']} - ${p['precio']:.2f}")
                )
            
            lista.controls.append(
                ft.Container(
                    content=ft.Column([
                        ft.Row([
                            ft.Text(cat["nombre"], weight=ft.FontWeight.BOLD, size=16),
                            ft.IconButton(
                                ft.Icons.DELETE,
                                on_click=lambda e, c=cat["nombre"]: self.eliminar_categoria(c, lista),
                                tooltip="Eliminar categoría"
                            )
                        ], alignment="spaceBetween"),
                        
                        ft.Row([
                            ft.TextField(label="Nombre platillo", width=280),
                            ft.TextField(label="Precio $", width=120, input_filter=ft.NumbersOnlyInputFilter()),
                            ft.ElevatedButton(
                                "Agregar",
                                on_click=lambda e, c=cat["nombre"]: agregar_platillo_local(e, c)
                            )
                        ]),
                        
                        platillos_col
                    ]),
                    bgcolor=ft.Colors.BLUE_GREY_800,
                    padding=15,
                    border_radius=10,
                    margin=ft.margin.only(bottom=10)
                )
            )
        self.page.update()
    
    def mostrar_error(self, mensaje):
        self.page.snack_bar = ft.SnackBar(ft.Text(mensaje), bgcolor=ft.Colors.RED_700)
        self.page.snack_bar.open = True
        self.page.update()