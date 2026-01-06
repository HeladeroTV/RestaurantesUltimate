# === BACKEND_SERVICE.PY ===
# Cliente HTTP para interactuar con la API del backend del sistema de restaurante.

import requests
import logging
from typing import List, Dict, Any
from datetime import datetime, timedelta

# ←←← LOGS PROFESIONALES (la línea mágica) ←←←
log = logging.getLogger("RestaurantIA")

class BackendService:
    def __init__(self, base_url: str = "http://127.0.0.1:8000"):
        self.base_url = base_url.rstrip("/")
        log.info(f"BackendService inicializado → Conectando a: {self.base_url}")

    def _request(self, method: str, endpoint: str, **kwargs) -> requests.Response:
        """
        Método interno para centralizar logs y manejo de errores HTTP.
        ¡Esto es oro puro! Nunca más vas a repetir try/except en cada método.
        """
        url = f"{self.base_url}{endpoint}"
        start_time = datetime.now()
        
        log.debug(f"HTTP {method.upper()} → {url} | Params: {kwargs.get('params')} | Payload: {kwargs.get('json')}")

        try:
            response = requests.request(method, url, timeout=15, **kwargs)
            duration = (datetime.now() - start_time).total_seconds() * 1000
            
            if response.status_code >= 200 and response.status_code < 300:
                log.info(f"HTTP {method.upper()} ← {response.status_code} | {duration:.1f}ms | {endpoint}")
            else:
                log.warning(f"HTTP {method.upper()} ← {response.status_code} | {duration:.1f}ms | {endpoint} | Respuesta: {response.text[:200]}")
            
            response.raise_for_status()
            return response

        except requests.exceptions.Timeout:
            log.error(f"TIMEOUT → {method.upper()} {endpoint} | Más de 15 segundos sin respuesta")
            raise Exception("El servidor tardó demasiado en responder. Revisa si el backend está corriendo.")
        except requests.exceptions.ConnectionError:
            log.error(f"CONEXIÓN FALLIDA → No se pudo conectar a {self.base_url}")
            raise Exception("No se pudo conectar al backend. ¿Está prendido el servidor?")
        except requests.exceptions.HTTPError as e:
            try:
                error_detail = response.json().get("detail", response.text)
            except:
                error_detail = response.text[:200]
            log.error(f"ERROR HTTP {response.status_code} → {endpoint} | Detalle: {error_detail}")
            raise Exception(f"Error del servidor: {error_detail}")
        except Exception as e:
            log.error(f"ERROR DESCONOCIDO en petición → {endpoint}", exc_info=True)
            raise

    # === TODOS LOS MÉTODOS AHORA SON LIMPIOS Y CON LOGS AUTOMÁTICOS ===

    def obtener_menu(self) -> List[Dict[str, Any]]:
        response = self._request("get", "/menu/items")
        return response.json()

    def crear_pedido(self, mesa_numero: int, items: List[Dict[str, Any]], estado: str = "Pendiente", notas: str = "") -> Dict[str, Any]:
        payload = {"mesa_numero": mesa_numero, "items": items, "estado": estado, "notas": notas}
        response = self._request("post", "/pedidos", json=payload)
        resultado = response.json()
        pedido_id = resultado.get("id")
        log.info(f"PEDIDO CREADO DESDE APP → ID #{pedido_id} | Mesa {mesa_numero} | {len(items)} ítems")
        return resultado

    def obtener_pedidos_activos(self) -> List[Dict[str, Any]]:
        response = self._request("get", "/pedidos/activos")
        datos = response.json()
        log.debug(f"Pedidos activos recibidos → {len(datos)} en cocina")
        return datos

    def actualizar_estado_pedido(self, pedido_id: int, nuevo_estado: str) -> Dict[str, Any]:
        response = self._request("patch", f"/pedidos/{pedido_id}/estado", params={"estado": nuevo_estado})
        log.info(f"ESTADO ACTUALIZADO DESDE APP → Pedido #{pedido_id} → '{nuevo_estado}'")
        return response.json()

    def obtener_mesas(self) -> List[Dict[str, Any]]:
        response = self._request("get", "/mesas")
        return response.json()

    def eliminar_ultimo_item(self, pedido_id: int) -> Dict[str, Any]:
        response = self._request("delete", f"/pedidos/{pedido_id}/ultimo_item")
        log.info(f"ÚLTIMO ÍTEM ELIMINADO DESDE APP → Pedido #{pedido_id}")
        return response.json()

    def actualizar_pedido(self, pedido_id: int, mesa_numero: int, items: List[Dict[str, Any]], estado: str = "Pendiente", notas: str = "") -> Dict[str, Any]:
        payload = {"mesa_numero": mesa_numero, "items": items, "estado": estado, "notas": notas}
        response = self._request("put", f"/pedidos/{pedido_id}", json=payload)
        log.info(f"PEDIDO ACTUALIZADO COMPLETAMENTE → ID #{pedido_id} | {len(items)} ítems")
        return response.json()

    def eliminar_pedido(self, pedido_id: int) -> Dict[str, Any]:
        response = self._request("delete", f"/pedidos/{pedido_id}")
        log.warning(f"PEDIDO ELIMINADO COMPLETAMENTE DESDE APP → ID #{pedido_id}")
        return response.json()

    def agregar_item_menu(self, nombre: str, precio: float, tipo: str) -> Dict[str, Any]:
        payload = {"nombre": nombre, "precio": precio, "tipo": tipo}
        response = self._request("post", "/menu/items", json=payload)
        log.info(f"ÍTEM AGREGADO AL MENÚ → '{nombre}' | ${precio}")
        return response.json()

    def eliminar_item_menu(self, nombre: str, tipo: str) -> Dict[str, Any]:
        response = self._request("delete", "/menu/items", params={"nombre": nombre, "tipo": tipo})
        log.warning(f"ÍTEM ELIMINADO DEL MENÚ → '{nombre}' ({tipo})")
        return response.json()

    def obtener_clientes(self) -> List[Dict[str, Any]]:
        response = self._request("get", "/clientes")
        return response.json()

    def agregar_cliente(self, nombre: str, domicilio: str, celular: str) -> Dict[str, Any]:
        payload = {"nombre": nombre, "domicilio": domicilio, "celular": celular}
        response = self._request("post", "/clientes", json=payload)
        log.info(f"CLIENTE AGREGADO → {nombre} | {celular}")
        return response.json()

    def eliminar_cliente(self, cliente_id: int) -> Dict[str, Any]:
        response = self._request("delete", f"/clientes/{cliente_id}")
        log.warning(f"CLIENTE ELIMINADO → ID #{cliente_id}")
        return response.json()

    def crear_respaldo(self) -> Dict[str, Any]:
        log.warning("RESPALDO SOLICITADO DESDE LA APP → Iniciando backup de BD...")
        response = self._request("post", "/backup")
        resultado = response.json()
        log.info(f"RESPALDO CREADO CON ÉXITO → {resultado['file_path']}")
        return resultado

    def obtener_reporte(self, tipo: str, fecha: datetime) -> Dict[str, Any]:
        # ... (tu lógica de fechas queda igual)
        if tipo == "Diario":
            start_date = fecha.strftime("%Y-%m-%d")
            end_date = (fecha + timedelta(days=1)).strftime("%Y-%m-%d")
        # ... resto igual ...

        params = {"tipo": tipo.lower(), "start_date": start_date, "end_date": end_date}
        response = self._request("get", "/reportes/", params=params)
        log.info(f"REPORTE GENERADO → {tipo} | {start_date} → {end_date}")
        return response.json()

    def obtener_analisis_productos(self, start_date: str = None, end_date: str = None) -> Dict[str, Any]:
        params = {}
        if start_date: params["start_date"] = start_date
        if end_date: params["end_date"] = end_date
        response = self._request("get", "/analisis/productos/", params=params)
        return response.json()

    def obtener_ventas_por_hora(self, fecha: str) -> Dict[str, float]:
        response = self._request("get", "/reportes/ventas_por_hora", params={"fecha": fecha})
        log.info(f"VENTAS POR HORA OBTENIDAS → {fecha}")
        return response.json()

    def obtener_eficiencia_cocina(self, tipo: str, fecha: datetime) -> Dict[str, Any]:
        # ... misma lógica de fechas ...
        params = {"tipo": tipo.lower(), "start_date": start_date, "end_date": end_date}
        response = self._request("get", "/reportes/eficiencia_cocina", params=params)
        log.info(f"EFICIENCIA DE COCINA OBTENIDA → {tipo} | Promedio: {response.json().get('promedio_minutos', '?')} min")
        return response.json()

    def crear_mesa(self, numero: int, capacidad: int) -> Dict[str, Any]:
        payload = {"numero": numero, "capacidad": capacidad}
        response = self._request("post", "/mesas", json=payload)
        log.info(f"MESA CREADA → Mesa {numero} | Capacidad: {capacidad} personas")
        return response.json()

    def obtener_eficiencia_cocina(self, tipo: str, fecha: datetime) -> Dict[str, Any]:
        """
        Obtiene datos de eficiencia de cocina para un periodo (diario, semanal, etc.)
        """
        # Calcular fechas según tipo
        if tipo == "Diario":
            start_date = fecha.strftime("%Y-%m-%d")
            end_date = (fecha + timedelta(days=1)).strftime("%Y-%m-%d")
        elif tipo == "Semanal":
            start = fecha - timedelta(days=fecha.weekday())
            end = start + timedelta(days=6)
            start_date = start.strftime("%Y-%m-%d")
            end_date = (end + timedelta(days=1)).strftime("%Y-%m-%d")
        elif tipo == "Mensual":
            start_date = fecha.replace(day=1).strftime("%Y-%m-%d")
            next_month = fecha.replace(day=1) + timedelta(days=32)
            end_date = next_month.replace(day=1).strftime("%Y-%m-%d")
        elif tipo == "Anual":
            start_date = fecha.replace(month=1, day=1).strftime("%Y-%m-%d")
            end_date = fecha.replace(month=12, day=31).strftime("%Y-%m-%d")
        else:
            start_date = end_date = fecha.strftime("%Y-%m-%d")

        response = self._request(
            "get",
            "/reportes/eficiencia_cocina",
            params={"tipo": tipo, "start_date": start_date, "end_date": end_date}
        )
        return response.json()
