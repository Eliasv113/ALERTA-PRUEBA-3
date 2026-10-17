
import os
import json
import requests
import xml.etree.ElementTree as ET

from pathlib import Path
from urllib.parse import urljoin
from datetime import datetime, timezone

# ==================================================
# CONFIGURACION
# ==================================================

RSS_URL = "https://ssl.smn.gob.ar/CAP/AR.php"

LOCALIDADES = {
    "Patquía": (-30.0468, -66.8823),
    "Punta de los Llanos": (-30.1455, -66.5262),
    "Tama": (-30.5058, -66.2952),
    "San Carlos de Bariloche": (-40.7500, -71.5000),
}

TOKEN = os.getenv("8882322196:AAGYo3rXhptjmA4vzkt-hvkKZ6QT8b3T7ZM")
CHAT_ID = os.getenv("-1004459131844")

HISTORIAL = Path("historial_alertas.json")
TIMEOUT = 30

HEADERS = {"User-Agent": "SMN-Telegram-Alertas/1.0"}


# ==================================================
# FUNCIONES GENERALES
# ==================================================

def nombre_tag(elemento):
    return elemento.tag.split("}")[-1]


def hijos(elemento, nombre):
    return [
        e for e in list(elemento)
        if nombre_tag(e) == nombre
    ]


def texto(elemento, nombre, defecto=""):
    encontrados = hijos(elemento, nombre)
    if not encontrados:
        return defecto
    return (encontrados[0].text or "").strip()


def descargar_xml(url):
    respuesta = requests.get(
        url, headers=HEADERS, timeout=TIMEOUT
    )
    respuesta.raise_for_status()
    return ET.fromstring(respuesta.content)


def cargar_historial():
    try:
        with HISTORIAL.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []


def guardar_historial(historial):
    with HISTORIAL.open("w", encoding="utf-8") as f:
        json.dump(
            historial[-5000:],
            f,
            ensure_ascii=False,
            indent=2
        )


# ==================================================
# TELEGRAM
# ==================================================

def enviar_telegram(mensaje):
    if not TOKEN or not CHAT_ID:
        raise RuntimeError(
            "Faltan los secretos de Telegram en GitHub."
        )

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

    respuesta = requests.post(
        url,
        json={
            "chat_id": CHAT_ID,
            "text": mensaje,
            "disable_web_page_preview": True
        },
        timeout=TIMEOUT
    )

    respuesta.raise_for_status()
    resultado = respuesta.json()

    if not resultado.get("ok"):
        raise RuntimeError(f"Error de Telegram: {resultado}")


# ==================================================
# POLIGONOS GEOGRAFICOS
# ==================================================

def punto_en_poligono(lat, lon, puntos):
    if len(puntos) < 3:
        return False

    dentro = False
    x, y = lon, lat
    j = len(puntos) - 1

    for i in range(len(puntos)):
        lat_i, lon_i = puntos[i]
        lat_j, lon_j = puntos[j]

        if (lat_i > y) != (lat_j > y):
            cruce = (
                (lon_j - lon_i) * (y - lat_i)
                / (lat_j - lat_i) + lon_i
            )

            if x < cruce:
                dentro = not dentro

        j = i

    return dentro


def extraer_poligonos(alerta):
    poligonos = []

    for info in hijos(alerta, "info"):
        for area in hijos(info, "area"):
            for elemento in hijos(area, "polygon"):
                puntos = []

                for par in (elemento.text or "").split():
                    partes = par.split(",")

                    if len(partes) != 2:
                        continue

                    try:
                        lat = float(partes[0])
                        lon = float(partes[1])

                        if -90 <= lat <= 90 and -180 <= lon <= 180:
                            puntos.append((lat, lon))
                    except ValueError:
                        continue

                if len(puntos) >= 3:
                    poligonos.append(puntos)

    return poligonos


def localidades_afectadas(alerta):
    poligonos = extraer_poligonos(alerta)
    resultado = []

    for nombre, (lat, lon) in LOCALIDADES.items():
        if any(
            punto_en_poligono(lat, lon, p)
            for p in poligonos
        ):
            resultado.append(nombre)

    return resultado


# ==================================================
# FECHAS
# ==================================================

def formatear_fecha(valor):
    if not valor:
        return "No especificada"

    try:
        fecha = datetime.fromisoformat(
            valor.replace("Z", "+00:00")
        )
        return fecha.strftime("%d/%m/%Y %H:%M UTC")
    except ValueError:
        return valor


def esta_vencida(alerta):
    infos = hijos(alerta, "info")
    ahora = datetime.now(timezone.utc)

    for info in infos:
        fin = texto(info, "expires")

        if not fin:
            continue

        try:
            fecha_fin = datetime.fromisoformat(
                fin.replace("Z", "+00:00")
            )

            if fecha_fin.tzinfo is None:
                fecha_fin = fecha_fin.replace(
                    tzinfo=timezone.utc
                )

            if fecha_fin <= ahora:
                return True

        except ValueError:
            pass

    return False


# ==================================================
# PROCESAR UNA ALERTA CAP
# ==================================================

def procesar_cap(alerta, historial):
    identificador = texto(alerta, "identifier")
    enviado = texto(alerta, "sent")
    estado = texto(alerta, "status", "Actual")
    tipo = texto(alerta, "msgType", "Alert")

    if not identificador:
        print("CAP sin identificador. Se omite.")
        return

    if estado.lower() != "actual":
        print(f"CAP no actual: {identificador}")
        return

    if tipo.lower() not in ("alert", "update"):
        print(f"Tipo CAP ignorado: {tipo}")
        return

    if esta_vencida(alerta):
        print(f"Alerta vencida: {identificador}")
        return

    clave = f"{identificador}|{enviado}"

    if clave in historial:
        print(f"Ya notificada: {identificador}")
        return

    localidades = localidades_afectadas(alerta)

    if not localidades:
        print(f"Sin localidades coincidentes: {identificador}")
        return

    infos = hijos(alerta, "info")

    if not infos:
        print(f"CAP sin bloque info: {identificador}")
        return

    # Construir y enviar el mensaje por cada bloque info.
    for info in infos:
        titulo = texto(
            info, "headline",
            texto(info, "event", "Alerta meteorológica")
        )
        descripcion = texto(
            info, "description", "Sin descripción disponible."
        )
        severidad = texto(info, "severity", "No especificada")
        certeza = texto(info, "certainty", "No especificada")
        urgencia = texto(info, "urgency", "No especificada")
        inicio = texto(info, "onset") or texto(info, "effective")
        fin = texto(info, "expires")

        mensaje = (
            f"🚨 ALERTA DEL SMN\n\n"
            f"🌦️ {titulo}\n"
            f"📍 Zonas afectadas: {', '.join(localidades)}\n\n"
            f"Severidad: {severidad}\n"
            f"Certeza: {certeza}\n"
            f"Urgencia: {urgencia}\n"
            f"Inicio: {formatear_fecha(inicio)}\n"
            f"Fin: {formatear_fecha(fin)}\n\n"
            f"{descripcion}\n\n"
            f"Fuente: https://www.smn.gob.ar/alertas"
        )

        enviar_telegram(mensaje)

    # Solo marcar como notificada después de enviar correctamente.
    historial.append(clave)
    guardar_historial(historial)

    print(
        f"ENVIADA: {identificador} - "
        f"{', '.join(localidades)}"
    )


# ==================================================
# LEER EL FEED OFICIAL
# ==================================================

def obtener_documentos(feed):
    # Algunos endpoints pueden devolver un CAP directamente.
    if nombre_tag(feed) == "alert":
        return [feed]

    documentos = []

    # Compatibilidad con RSS y Atom.
    for elemento in feed.iter():
        if nombre_tag(elemento) not in ("item", "entry"):
            continue

        enlace = ""

        for link in list(elemento):
            if nombre_tag(link) == "link":
                enlace = (
                    link.attrib.get("href", "")
                    or (link.text or "").strip()
                )

                if enlace:
                    break

        if enlace:
            documentos.append(urljoin(RSS_URL, enlace))

    return list(dict.fromkeys(documentos))


def procesar_alertas():
    print("====================================")
    print("CONSULTANDO ALERTAS DEL SMN")
    print(datetime.now(timezone.utc).isoformat())
    print("====================================")

    historial = cargar_historial()

    feed = descargar_xml(RSS_URL)
    documentos = obtener_documentos(feed)

    print(f"Documentos CAP encontrados: {len(documentos)}")

    errores = 0

    for documento in documentos:
        try:
            if isinstance(documento, str):
                alerta = descargar_xml(documento)
            else:
                alerta = documento

            if nombre_tag(alerta) != "alert":
                print(f"El enlace no devolvió un CAP: {documento}")
                continue

            procesar_cap(alerta, historial)

        except Exception as error:
            errores += 1
            print(f"ERROR en {documento}: {error}")

    print(f"Finalizado. Errores: {errores}")


if __name__ == "__main__":
    procesar_alertas()
