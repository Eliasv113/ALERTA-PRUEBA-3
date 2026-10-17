import os
import json
import requests
from datetime import datetime

# Diccionario con las localidades y sus coordenadas (Latitud, Longitud)
LOCALIDADES = {
    "Patquía": (-30.0468, -66.8823),
    "Punta de los Llanos": (-30.1455, -66.5262),
    "Tama": (-30.5058, -66.2952),
    "San Carlos de Bariloche": (-40.7500, -71.5000) # Coordenada de prueba
}

# Endpoint oficial de alertas del SMN en JSON
API_URL = 'https://www.smn.gob.ar/api/v1/alertas'

TELEGRAM_BOT_TOKEN = '8882322196:AAGYo3rXhptjmA4vzkt-hvkKZ6QT8b3T7ZM'
TELEGRAM_CHANNEL_ID = '-1004459131844'
HISTORIAL_FILE = 'historial_alerta_prueba_polygon.json'

def cargar_historial():
    if os.path.exists(HISTORIAL_FILE):
        with open(HISTORIAL_FILE, 'r', encoding='utf-8') as f:
            try: return json.load(f)
            except: return []
    return []

def guardar_historial(historial):
    with open(HISTORIAL_FILE, 'w', encoding='utf-8') as f:
        json.dump(historial, f, ensure_ascii=False, indent=4)

def enviar_telegram_texto(mensaje):
    url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
    requests.post(url, json={'chat_id': TELEGRAM_CHANNEL_ID, 'text': mensaje})

def punto_en_poligono(latitud, longitud, poligono):
    x, y = longitud, latitud
    adentro = False
    n = len(poligono)
    if n == 0: return False
    p1_y, p1_x = poligono[0]
    for i in range(1, n + 1):
        p2_y, p2_x = poligono[i % n]
        if min(p1_y, p2_y) < y <= max(p1_y, p2_y):
            if x <= max(p1_x, p2_x):
                if p1_y != p2_y:
                    xinters = (y - p1_y) * (p2_x - p1_x) / (p2_y - p1_y) + p1_x
                if p1_x == p2_x or x <= xinters:
                    adentro = not adentro
        p1_x, p1_y = p2_x, p2_y
    return adentro

def formatear_fecha(fecha_str):
    try:
        dt = datetime.fromisoformat(fecha_str.replace('Z', '+00:00'))
        return dt.strftime('%d/%m/%Y %H:%M')
    except:
        return fecha_str

def procesar_alertas():
    historial = cargar_historial()
    
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        respuesta = requests.get(API_URL, headers=headers, timeout=15)
        datos = respuesta.json()
    except Exception as e:
        print(f"Error al conectar con la API del SMN: {e}")
        return

    print("Conexión exitosa con la API del SMN.")

    # La API devuelve una lista de alertas activas
    alertas = datos if isinstance(datos, list) else [datos]
    print(f"Se encontraron {len(alertas)} alertas para procesar.")

    for alerta in alertas:
        alerta_id = str(alerta.get('id', alerta.get('NroAlerta', '')))
        titulo = alerta.get('fenomeno', alerta.get('title', 'Alerta Meteorológica'))
        
        if not alerta_id:
            alerta_id = titulo + str(alerta.get('Certeza', ''))

        print(f"\n--- Analizando: {titulo} ---")
        
        if alerta_id in historial:
            print("Resultado: IGNORADA (Ya está en el historial).")
            continue

        # Buscamos el polígono en la estructura JSON oficial
        polygons = alerta.get('poligono', alerta.get('polygon', []))
        
        localidades_afectadas = set()
        
        # Procesamos polígonos si vienen en formato de lista de coordenadas o texto
        if polygons:
            # Si el SMN provee una lista de puntos
            puntos = []
            if isinstance(polygons, str):
                pares = polygons.split()
                for par in pares:
                    partes = par.split(',')
                    if len(partes) == 2:
                        try: puntos.append((float(partes[0]), float(partes[1])))
                        except: pass
            elif isinstance(polygons, list):
                for p in polygons:
                    try: puntos.append((float(p.get('lat', p.get('latitud', 0))), float(p.get('lon', p.get('longitud', 0)))))
                    except: pass

            if puntos:
                for nombre_pueblo, (lat, lon) in LOCALIDADES.items():
                    if punto_en_poligono(lat, lon, puntos):
                        localidades_afectadas.add(nombre_pueblo)

        if localidades_afectadas:
            print(f"Resultado: ¡ALERTA POSITIVA para {localidades_afectadas}! Enviando a Telegram...")
            
            certeza = alerta.get('certeza', 'No especificada')
            inicio = formatear_fecha(alerta.get('inicio', ''))
            fin = formatear_fecha(alerta.get('fin', ''))
            descripcion = alerta.get('descripcion', alerta.get('description', 'Sin descripción'))
            
            pueblos_str = ", ".join(sorted(localidades_afectadas))
            
            mensaje = (
                f"🚨 Alerta de {titulo}\n"
                f"📍 Zonas afectadas: {pueblos_str}\n\n"
                f"Certeza: {certeza}\n\n"
                f"Inicio: {inicio}\n"
                f"Fin: {fin}\n\n"
                f"{descripcion}\n\n"
                f"Fuente: https://www.smn.gob.ar/alertas"
            )
            
            enviar_telegram_texto(mensaje)
            historial.append(alerta_id)
            guardar_historial(historial)
        else:
            print("Resultado: No afecta a las localidades configuradas.")

if __name__ == '__main__':
    procesar_alertas()
