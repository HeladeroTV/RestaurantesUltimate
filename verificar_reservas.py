
import requests
import datetime

BASE_URL = "http://127.0.0.1:8000"

def verificar_reserva():
    print("--- INICIANDO VERIFICACIÓN DE RESERVAS ---")
    
    # 1. Crear un cliente de prueba si no existe
    cliente_data = {
        "nombre": "Cliente Test Verificacion",
        "domicilio": "Calle Pruebas 123",
        "celular": "555-999-888"
    }
    print(f"1. Creando cliente de prueba: {cliente_data['nombre']}")
    resp_cliente = requests.post(f"{BASE_URL}/clientes", json=cliente_data)
    if resp_cliente.status_code != 200:
        print("Error al crear cliente:", resp_cliente.text)
        return
    cliente_id = resp_cliente.json()["id"]
    print(f"   -> Cliente creado con ID: {cliente_id}")

    # 2. Crear una reserva para HOY en la Mesa 3 (para no chocar con la 2 que limpiamos)
    hoy = datetime.datetime.now()
    inicio = hoy + datetime.timedelta(minutes=30) # Dentro de 30 mins
    fin = inicio + datetime.timedelta(hours=1)
    
    reserva_data = {
        "mesa_numero": 3,
        "cliente_id": cliente_id,
        "fecha_hora_inicio": inicio.strftime("%Y-%m-%d %H:%M:%S"),
        "fecha_hora_fin": fin.strftime("%Y-%m-%d %H:%M:%S")
    }
    
    print(f"\n2. Creando reserva para Mesa 3 hoy a las {inicio.strftime('%H:%M')}")
    resp_reserva = requests.post(f"{BASE_URL}/reservas", json=reserva_data)
    
    if resp_reserva.status_code == 200:
        print("   -> Reserva creada EXITOSAMENTE en la Base de Datos.")
        print("\n--- INSTRUCCIONES PARA EL USUARIO ---")
        print("1. Abre la aplicación 'app.py'")
        print("2. Ve a la vista principal (Meseras).")
        print("   -> DEBERÍAS VER: La Mesa 3 de color AZUL, pero SIN TEXTO (sólo 'Mesa 3' y capacidad).")
        print("3. Ve a la pestaña 'Reservas'.")
        print("   -> DEBERÍAS VER: Los detalles de la reserva: 'Mesa 3 - Cliente Test Verificacion', Hora, etc.")
        print("-------------------------------------")
    else:
        print("Error al crear reserva:", resp_reserva.text)

if __name__ == "__main__":
    verificar_reserva()
