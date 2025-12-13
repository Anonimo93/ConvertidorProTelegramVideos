import os
import asyncio
import shutil
import json
import time
import math
import datetime
import subprocess
import re
import sqlite3
import logging
import zipfile
from pyrogram import Client, filters, enums
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from collections import deque
import threading
import psutil

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class Config:
    API_ID = 22788599  
    API_HASH = "6fd904cf42bbe1f6d57f22d8d392e9b4" 
    BOT_TOKEN = "8230649001:AAEpb7ZdkKV9zFo1X3Wojem9g_UOKMv_-UA"  
    
    ADMINISTRADORES = [7400531692]  
    
    MAX_CONCURRENT_PROCESSES = 3
    MAX_FILE_SIZE_MB = 300
    
    DEFAULT_QUALITY = {
        "resolution": "360x240",
        "crf": "30",
        "audio_bitrate": "60k",
        "fps": "18",
        "preset": "veryfast",
        "codec": "libx265"
    }
    
    TEMP_DIR = "temp_files"
    MODO_SOPORTE = False
    
    @classmethod
    def validar_configuracion(cls):
        if not cls.API_ID or cls.API_ID == 12345678:
            raise ValueError("❌ Debes configurar un API_ID válido")
        if not cls.API_HASH or cls.API_HASH == "tu_api_hash_aqui":
            raise ValueError("❌ Debes configurar un API_HASH válido")
        if not cls.BOT_TOKEN or cls.BOT_TOKEN == "tu_bot_token_aqui":
            raise ValueError("❌ Debes configurar un BOT_TOKEN válido")
        
        if not re.match(r'^\d+x\d+$', cls.DEFAULT_QUALITY["resolution"]):
            raise ValueError("❌ Formato de resolución inválido (ej: 1280x720)")
            
        if not 0 <= int(cls.DEFAULT_QUALITY["crf"]) <= 51:
            raise ValueError("❌ CRF debe estar entre 0 y 51")
        
        return True

class DatabaseManager:
    def __init__(self, archivo_db="bot_database.db"):
        self.archivo_db = archivo_db
        self.inicializar_base_datos()
    
    def obtener_conexion(self):
        conn = sqlite3.connect(self.archivo_db)
        conn.row_factory = sqlite3.Row
        return conn
    
    def inicializar_base_datos(self):
        try:
            conn = self.obtener_conexion()
            cursor = conn.cursor()
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS usuarios (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    language_code TEXT,
                    fecha_registro DATETIME DEFAULT CURRENT_TIMESTAMP,
                    fecha_ultimo_uso DATETIME DEFAULT CURRENT_TIMESTAMP,
                    total_conversiones INTEGER DEFAULT 0,
                    es_activo BOOLEAN DEFAULT 1,
                    baneado BOOLEAN DEFAULT 0,
                    razon_baneo TEXT,
                    fecha_baneo DATETIME
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS administradores (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    agregado_por INTEGER,
                    fecha_agregado DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES usuarios (user_id)
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS configuracion_usuario (
                    user_id INTEGER PRIMARY KEY,
                    configuracion TEXT,
                    fecha_actualizacion DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES usuarios (user_id)
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS canales_requeridos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    canal_id TEXT UNIQUE,
                    nombre_canal TEXT,
                    enlace_canal TEXT,
                    agregado_por INTEGER,
                    fecha_agregado DATETIME DEFAULT CURRENT_TIMESTAMP,
                    activo BOOLEAN DEFAULT 1
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS videos_convertidos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    nombre_archivo TEXT,
                    tamano_original INTEGER,
                    tamano_convertido INTEGER,
                    duracion_original TEXT,
                    duracion_convertido TEXT,
                    calidad_config TEXT,
                    tiempo_procesamiento REAL,
                    fecha_conversion DATETIME DEFAULT CURRENT_TIMESTAMP,
                    estado TEXT DEFAULT 'completado',
                    mensaje_error TEXT,
                    FOREIGN KEY (user_id) REFERENCES usuarios (user_id)
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS configuracion_sistema (
                    clave TEXT PRIMARY KEY,
                    valor TEXT,
                    descripcion TEXT,
                    fecha_actualizacion DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            conn.commit()
            
            configuracion_por_defecto = [
                ('limite_peso_mb', str(Config.MAX_FILE_SIZE_MB), 'Límite máximo de tamaño de archivo en MB'),
                ('max_concurrente', str(Config.MAX_CONCURRENT_PROCESSES), 'Máximo de procesos concurrentes'),
                ('calidad_default', json.dumps(Config.DEFAULT_QUALITY), 'Configuración de calidad por defecto'),
                ('mantenimiento', 'false', 'Modo mantenimiento del bot'),
                ('modo_soporte', 'false', 'Modo soporte activo')
            ]
            
            for clave, valor, descripcion in configuracion_por_defecto:
                cursor.execute('''
                    INSERT OR IGNORE INTO configuracion_sistema (clave, valor, descripcion)
                    VALUES (?, ?, ?)
                ''', (clave, valor, descripcion))
            
            for admin_id in Config.ADMINISTRADORES:
                cursor.execute('''
                    INSERT OR IGNORE INTO administradores (user_id, agregado_por)
                    VALUES (?, ?)
                ''', (admin_id, 0))
            
            conn.commit()
            logger.info("✅ Base de datos inicializada correctamente")
            
        except Exception as e:
            logger.error(f"❌ Error inicializando base de datos: {e}")
            raise
        finally:
            conn.close()
    
    def cargar_configuracion_desde_db(self):
        try:
            conn = self.obtener_conexion()
            cursor = conn.cursor()
            
            cursor.execute('SELECT valor FROM configuracion_sistema WHERE clave = ?', ('limite_peso_mb',))
            resultado = cursor.fetchone()
            if resultado:
                Config.MAX_FILE_SIZE_MB = int(resultado['valor'])
            
            cursor.execute('SELECT valor FROM configuracion_sistema WHERE clave = ?', ('calidad_default',))
            resultado = cursor.fetchone()
            if resultado:
                Config.DEFAULT_QUALITY = json.loads(resultado['valor'])
            
            cursor.execute('SELECT valor FROM configuracion_sistema WHERE clave = ?', ('modo_soporte',))
            resultado = cursor.fetchone()
            if resultado:
                Config.MODO_SOPORTE = resultado['valor'].lower() == 'true'
            
            logger.info("✅ Configuración cargada desde base de datos")
            
        except Exception as e:
            logger.error(f"❌ Error cargando configuración: {e}")
        finally:
            conn.close()
    
    def obtener_calidad_usuario(self, user_id):
        try:
            conn = self.obtener_conexion()
            cursor = conn.cursor()
            
            cursor.execute('SELECT configuracion FROM configuracion_usuario WHERE user_id = ?', (user_id,))
            resultado = cursor.fetchone()
            
            if resultado:
                return json.loads(resultado['configuracion'])
            return None
        except Exception as e:
            logger.error(f"❌ Error obteniendo calidad de usuario: {e}")
            return None
        finally:
            conn.close()
    
    def guardar_calidad_usuario(self, user_id, configuracion):
        try:
            conn = self.obtener_conexion()
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO configuracion_usuario (user_id, configuracion, fecha_actualizacion)
                VALUES (?, ?, CURRENT_TIMESTAMP)
            ''', (user_id, json.dumps(configuracion)))
            
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"❌ Error guardando calidad de usuario: {e}")
            return False
        finally:
            conn.close()
    
    def eliminar_calidad_usuario(self, user_id):
        try:
            conn = self.obtener_conexion()
            cursor = conn.cursor()
            
            cursor.execute('DELETE FROM configuracion_usuario WHERE user_id = ?', (user_id,))
            
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"❌ Error eliminando calidad de usuario: {e}")
            return False
        finally:
            conn.close()
    
    def agregar_actualizar_usuario(self, datos_usuario):
        try:
            conn = self.obtener_conexion()
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO usuarios 
                (user_id, username, first_name, last_name, language_code, fecha_ultimo_uso)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ''', (
                datos_usuario['user_id'],
                datos_usuario.get('username'),
                datos_usuario.get('first_name'),
                datos_usuario.get('last_name'),
                datos_usuario.get('language_code')
            ))
            
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"❌ Error agregando usuario: {e}")
            return False
        finally:
            conn.close()
    
    def incrementar_conversion_usuario(self, user_id):
        try:
            conn = self.obtener_conexion()
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE usuarios 
                SET total_conversiones = total_conversiones + 1,
                    fecha_ultimo_uso = CURRENT_TIMESTAMP
                WHERE user_id = ?
            ''', (user_id,))
            
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"❌ Error incrementando conversiones: {e}")
            return False
        finally:
            conn.close()
    
    def obtener_usuario(self, user_id):
        try:
            conn = self.obtener_conexion()
            cursor = conn.cursor()
            
            cursor.execute('SELECT * FROM usuarios WHERE user_id = ?', (user_id,))
            usuario = cursor.fetchone()
            
            return dict(usuario) if usuario else None
        except Exception as e:
            logger.error(f"❌ Error obteniendo usuario: {e}")
            return None
        finally:
            conn.close()
    
    def agregar_video_convertido(self, datos_video):
        try:
            conn = self.obtener_conexion()
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO videos_convertidos 
                (user_id, nombre_archivo, tamano_original, tamano_convertido, 
                 duracion_original, duracion_convertido, calidad_config, tiempo_procesamiento)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                datos_video['user_id'],
                datos_video['nombre_archivo'],
                datos_video['tamano_original'],
                datos_video['tamano_convertido'],
                datos_video.get('duracion_original', ''),
                datos_video.get('duracion_convertido', ''),
                datos_video.get('calidad_config', ''),
                datos_video.get('tiempo_procesamiento', 0)
            ))
            
            self.incrementar_conversion_usuario(datos_video['user_id'])
            
            conn.commit()
            return cursor.lastrowid
        except Exception as e:
            logger.error(f"❌ Error agregando video: {e}")
            return None
        finally:
            conn.close()
    
    def obtener_historial_usuario(self, user_id, limite=10):
        try:
            conn = self.obtener_conexion()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT nombre_archivo, tamano_original, tamano_convertido, 
                       fecha_conversion, tiempo_procesamiento
                FROM videos_convertidos 
                WHERE user_id = ? 
                ORDER BY fecha_conversion DESC 
                LIMIT ?
            ''', (user_id, limite))
            
            historial = []
            for row in cursor.fetchall():
                historial.append({
                    'nombre_archivo': row['nombre_archivo'],
                    'tamano_original': row['tamano_original'],
                    'tamano_convertido': row['tamano_convertido'],
                    'fecha_conversion': row['fecha_conversion'],
                    'tiempo_procesamiento': row['tiempo_procesamiento']
                })
            
            return historial
        except Exception as e:
            logger.error(f"❌ Error obteniendo historial: {e}")
            return []
        finally:
            conn.close()
    
    def obtener_estadisticas_generales(self):
        try:
            conn = self.obtener_conexion()
            cursor = conn.cursor()
            
            cursor.execute('SELECT COUNT(*) FROM usuarios WHERE es_activo = 1 AND baneado = 0')
            total_usuarios = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) FROM usuarios WHERE baneado = 1')
            usuarios_baneados = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) FROM administradores')
            total_admins = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) FROM videos_convertidos')
            total_videos = cursor.fetchone()[0]
            
            cursor.execute('''
                SELECT SUM(tamano_original - tamano_convertido) 
                FROM videos_convertidos 
                WHERE tamano_original > tamano_convertido
            ''')
            espacio_ahorrado = cursor.fetchone()[0] or 0
            
            cursor.execute('SELECT SUM(tiempo_procesamiento) FROM videos_convertidos')
            tiempo_total = cursor.fetchone()[0] or 0
            
            return {
                "total_usuarios": total_usuarios,
                "usuarios_baneados": usuarios_baneados,
                "total_admins": total_admins,
                "total_videos": total_videos,
                "espacio_ahorrado": espacio_ahorrado,
                "tiempo_total_procesamiento": tiempo_total
            }
        except Exception as e:
            logger.error(f"❌ Error obteniendo estadísticas: {e}")
            return {}
        finally:
            conn.close()
    
    def obtener_configuracion(self, clave):
        try:
            conn = self.obtener_conexion()
            cursor = conn.cursor()
            
            cursor.execute('SELECT valor FROM configuracion_sistema WHERE clave = ?', (clave,))
            resultado = cursor.fetchone()
            
            return resultado['valor'] if resultado else None
        except Exception as e:
            logger.error(f"❌ Error obteniendo configuración: {e}")
            return None
        finally:
            conn.close()
    
    def actualizar_configuracion(self, clave, valor):
        try:
            conn = self.obtener_conexion()
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE configuracion_sistema 
                SET valor = ?, fecha_actualizacion = CURRENT_TIMESTAMP
                WHERE clave = ?
            ''', (valor, clave))
            
            conn.commit()
            
            if clave == 'limite_peso_mb':
                Config.MAX_FILE_SIZE_MB = int(valor)
            elif clave == 'calidad_default':
                Config.DEFAULT_QUALITY = json.loads(valor)
            elif clave == 'modo_soporte':
                Config.MODO_SOPORTE = valor.lower() == 'true'
            
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"❌ Error actualizando configuración: {e}")
            return False
        finally:
            conn.close()
    
    def es_administrador(self, user_id):
        try:
            conn = self.obtener_conexion()
            cursor = conn.cursor()
            
            cursor.execute('SELECT 1 FROM administradores WHERE user_id = ?', (user_id,))
            return cursor.fetchone() is not None or user_id in Config.ADMINISTRADORES
        except Exception as e:
            logger.error(f"❌ Error verificando administrador: {e}")
            return False
        finally:
            conn.close()
    
    def agregar_administrador(self, user_id, username, agregado_por):
        try:
            conn = self.obtener_conexion()
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO administradores (user_id, username, agregado_por)
                VALUES (?, ?, ?)
            ''', (user_id, username, agregado_por))
            
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"❌ Error agregando administrador: {e}")
            return False
        finally:
            conn.close()
    
    def eliminar_administrador(self, user_id):
        try:
            conn = self.obtener_conexion()
            cursor = conn.cursor()
            
            cursor.execute('DELETE FROM administradores WHERE user_id = ?', (user_id,))
            
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"❌ Error eliminando administrador: {e}")
            return False
        finally:
            conn.close()
    
    def obtener_administradores(self):
        try:
            conn = self.obtener_conexion()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT a.user_id, a.username, u.first_name, a.fecha_agregado, a.agregado_por
                FROM administradores a
                LEFT JOIN usuarios u ON a.user_id = u.user_id
                ORDER BY a.fecha_agregado
            ''')
            
            admins = []
            for row in cursor.fetchall():
                admins.append({
                    'user_id': row['user_id'],
                    'username': row['username'],
                    'first_name': row['first_name'],
                    'fecha_agregado': row['fecha_agregado'],
                    'agregado_por': row['agregado_por']
                })
            
            return admins
        except Exception as e:
            logger.error(f"❌ Error obteniendo administradores: {e}")
            return []
        finally:
            conn.close()
    
    def banear_usuario(self, user_id, razon, baneado_por):
        try:
            conn = self.obtener_conexion()
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE usuarios 
                SET baneado = 1, razon_baneo = ?, fecha_baneo = CURRENT_TIMESTAMP
                WHERE user_id = ?
            ''', (razon, user_id))
            
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"❌ Error baneando usuario: {e}")
            return False
        finally:
            conn.close()
    
    def desbanear_usuario(self, user_id):
        try:
            conn = self.obtener_conexion()
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE usuarios 
                SET baneado = 0, razon_baneo = NULL, fecha_baneo = NULL
                WHERE user_id = ?
            ''', (user_id,))
            
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"❌ Error desbaneando usuario: {e}")
            return False
        finally:
            conn.close()
    
    def usuario_baneado(self, user_id):
        try:
            conn = self.obtener_conexion()
            cursor = conn.cursor()
            
            cursor.execute('SELECT baneado, razon_baneo FROM usuarios WHERE user_id = ?', (user_id,))
            resultado = cursor.fetchone()
            
            if resultado and resultado['baneado'] == 1:
                return True, resultado['razon_baneo']
            return False, None
        except Exception as e:
            logger.error(f"❌ Error verificando baneo: {e}")
            return False, None
        finally:
            conn.close()
    
    def obtener_usuarios_baneados(self):
        try:
            conn = self.obtener_conexion()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT user_id, username, first_name, razon_baneo, fecha_baneo
                FROM usuarios 
                WHERE baneado = 1
                ORDER BY fecha_baneo DESC
            ''')
            
            baneados = []
            for row in cursor.fetchall():
                baneados.append({
                    'user_id': row['user_id'],
                    'username': row['username'],
                    'first_name': row['first_name'],
                    'razon_baneo': row['razon_baneo'],
                    'fecha_baneo': row['fecha_baneo']
                })
            
            return baneados
        except Exception as e:
            logger.error(f"❌ Error obteniendo baneados: {e}")
            return []
        finally:
            conn.close()
    
    def exportar_backup(self, ruta_backup):
        try:
            shutil.copy2(self.archivo_db, ruta_backup)
            return True
        except Exception as e:
            logger.error(f"❌ Error exportando backup: {e}")
            return False
    
    def importar_backup(self, ruta_backup):
        try:
            shutil.copy2(ruta_backup, self.archivo_db)
            self.cargar_configuracion_desde_db()
            return True
        except Exception as e:
            logger.error(f"❌ Error importando backup: {e}")
            return False
    
    def obtener_todos_videos(self, limite=50, offset=0):
        try:
            conn = self.obtener_conexion()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT v.*, u.username, u.first_name, u.last_name
                FROM videos_convertidos v
                LEFT JOIN usuarios u ON v.user_id = u.user_id
                ORDER BY v.fecha_conversion DESC
                LIMIT ? OFFSET ?
            ''', (limite, offset))
            
            videos = []
            for row in cursor.fetchall():
                videos.append({
                    'id': row['id'],
                    'user_id': row['user_id'],
                    'nombre_archivo': row['nombre_archivo'],
                    'tamano_original': row['tamano_original'],
                    'tamano_convertido': row['tamano_convertido'],
                    'tiempo_procesamiento': row['tiempo_procesamiento'],
                    'fecha_conversion': row['fecha_conversion'],
                    'username': row['username'],
                    'first_name': row['first_name'],
                    'last_name': row['last_name']
                })
            
            cursor.execute('SELECT COUNT(*) FROM videos_convertidos')
            total = cursor.fetchone()[0]
            
            return videos, total
        except Exception as e:
            logger.error(f"❌ Error obteniendo todos los videos: {e}")
            return [], 0
        finally:
            conn.close()
    
    def agregar_canal_requerido(self, canal_id, nombre_canal, enlace_canal, agregado_por):
        try:
            conn = self.obtener_conexion()
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO canales_requeridos 
                (canal_id, nombre_canal, enlace_canal, agregado_por, activo)
                VALUES (?, ?, ?, ?, 1)
            ''', (canal_id, nombre_canal, enlace_canal, agregado_por))
            
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"❌ Error agregando canal requerido: {e}")
            return False
        finally:
            conn.close()
    
    def eliminar_canal_requerido(self, canal_id):
        try:
            conn = self.obtener_conexion()
            cursor = conn.cursor()
            
            cursor.execute('DELETE FROM canales_requeridos WHERE canal_id = ?', (canal_id,))
            
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"❌ Error eliminando canal requerido: {e}")
            return False
        finally:
            conn.close()
    
    def obtener_canales_requeridos(self):
        try:
            conn = self.obtener_conexion()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT canal_id, nombre_canal, enlace_canal, agregado_por, fecha_agregado
                FROM canales_requeridos 
                WHERE activo = 1
                ORDER BY fecha_agregado
            ''')
            
            canales = []
            for row in cursor.fetchall():
                canales.append({
                    'canal_id': row['canal_id'],
                    'nombre_canal': row['nombre_canal'],
                    'enlace_canal': row['enlace_canal'],
                    'agregado_por': row['agregado_por'],
                    'fecha_agregado': row['fecha_agregado']
                })
            
            return canales
        except Exception as e:
            logger.error(f"❌ Error obteniendo canales requeridos: {e}")
            return []
        finally:
            conn.close()
    
    def canal_existe(self, canal_id):
        try:
            conn = self.obtener_conexion()
            cursor = conn.cursor()
            
            cursor.execute('SELECT 1 FROM canales_requeridos WHERE canal_id = ?', (canal_id,))
            return cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"❌ Error verificando canal: {e}")
            return False
        finally:
            conn.close()

db = DatabaseManager()
app = Client(
    "video_converter_bot",
    api_id=Config.API_ID,
    api_hash=Config.API_HASH,
    bot_token=Config.BOT_TOKEN
)

class SistemaColas:
    def __init__(self, max_concurrente=3):
        self.cola_espera = deque()
        self.cola_prioridad = deque()
        self.procesos_activos = {}
        self.max_concurrente = max_concurrente
        self.lock = threading.Lock()
        self.procesos_por_usuario = {}
        self.estadisticas = {
            "procesos_completados": 0,
            "errores": 0,
            "total_tiempo": 0,
            "inicio_sistema": time.time()
        }
        
    def agregar_trabajo(self, user_id, trabajo, es_administrador=False):
        with self.lock:
            if not es_administrador:
                usuario_actual = self.procesos_por_usuario.get(user_id, 0)
                max_por_usuario = 3
                
                if usuario_actual >= max_por_usuario:
                    return "limite_usuario"
            
            if user_id in self.procesos_por_usuario:
                self.procesos_por_usuario[user_id] += 1
            else:
                self.procesos_por_usuario[user_id] = 1
            
            if len(self.procesos_activos) < self.max_concurrente:
                self.procesos_activos[user_id] = trabajo
                return "procesando"
            else:
                if es_administrador:
                    self.cola_prioridad.append((user_id, trabajo))
                    posicion = len(self.cola_prioridad)
                    return f"prioridad_{posicion}"
                else:
                    self.cola_espera.append((user_id, trabajo))
                    posicion = len(self.cola_espera) + len(self.cola_prioridad)
                    return f"encolado_{posicion}"
    
    def trabajo_completado(self, user_id, exito=True, tiempo=0):
        with self.lock:
            if user_id in self.procesos_activos:
                del self.procesos_activos[user_id]
            
            if user_id in self.procesos_por_usuario:
                self.procesos_por_usuario[user_id] -= 1
                if self.procesos_por_usuario[user_id] <= 0:
                    del self.procesos_por_usuario[user_id]
            
            if exito:
                self.estadisticas["procesos_completados"] += 1
            else:
                self.estadisticas["errores"] += 1
            self.estadisticas["total_tiempo"] += tiempo
            
            siguiente_trabajo = None
            siguiente_user_id = None
            
            if self.cola_prioridad and len(self.procesos_activos) < self.max_concurrente:
                siguiente_user_id, siguiente_trabajo = self.cola_prioridad.popleft()
            elif self.cola_espera and len(self.procesos_activos) < self.max_concurrente:
                siguiente_user_id, siguiente_trabajo = self.cola_espera.popleft()
            
            if siguiente_trabajo:
                self.procesos_activos[siguiente_user_id] = siguiente_trabajo
                return siguiente_user_id, siguiente_trabajo
                
            return None, None
    
    def obtener_estado(self, user_id):
        with self.lock:
            if user_id in self.procesos_activos:
                return "procesando"
            
            for i, (uid, trabajo) in enumerate(self.cola_prioridad):
                if uid == user_id:
                    return f"prioridad_{i + 1}"
            
            for i, (uid, trabajo) in enumerate(self.cola_espera):
                if uid == user_id:
                    return f"encolado_{i + 1 + len(self.cola_prioridad)}"
            
            return "no_encontrado"
    
    def obtener_estadisticas(self):
        with self.lock:
            tiempo_promedio = (
                self.estadisticas["total_tiempo"] / self.estadisticas["procesos_completados"] 
                if self.estadisticas["procesos_completados"] > 0 else 0
            )
            uptime = time.time() - self.estadisticas["inicio_sistema"]
            
            return {
                "procesando": len(self.procesos_activos),
                "en_espera": len(self.cola_espera) + len(self.cola_prioridad),
                "prioridad": len(self.cola_prioridad),
                "normal": len(self.cola_espera),
                "max_concurrente": self.max_concurrente,
                "completados": self.estadisticas["procesos_completados"],
                "errores": self.estadisticas["errores"],
                "tiempo_promedio": tiempo_promedio,
                "uptime": uptime
            }
    
    def obtener_detalle_cola(self):
        with self.lock:
            detalle = {
                "procesando": [],
                "prioridad": [],
                "normal": []
            }
            
            for user_id, trabajo in self.procesos_activos.items():
                nombre_archivo = trabajo.get("nombre_archivo", "Desconocido")
                detalle["procesando"].append({
                    "user_id": user_id,
                    "nombre_archivo": nombre_archivo
                })
            
            for user_id, trabajo in self.cola_prioridad:
                nombre_archivo = trabajo.get("nombre_archivo", "Desconocido")
                detalle["prioridad"].append({
                    "user_id": user_id,
                    "nombre_archivo": nombre_archivo
                })
            
            for user_id, trabajo in self.cola_espera:
                nombre_archivo = trabajo.get("nombre_archivo", "Desconocido")
                detalle["normal"].append({
                    "user_id": user_id,
                    "nombre_archivo": nombre_archivo
                })
            
            return detalle

sistema_colas = SistemaColas(max_concurrente=Config.MAX_CONCURRENT_PROCESSES)

def obtener_duracion_video(ruta_video):
    try:
        resultado = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                ruta_video
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
        return float(resultado.stdout.strip())
    except Exception as e:
        logger.error(f"❌ Error al obtener duración: {e}")
        return 0

def formatear_tiempo(segundos):
    if segundos < 0:
        return "00:00"
    
    horas, resto = divmod(int(segundos), 3600)
    minutos, segundos = divmod(resto, 60)
    
    if horas > 0:
        return f"{horas:02d}:{minutos:02d}:{segundos:02d}"
    else:
        return f"{minutos:02d}:{segundos:02d}"

def obtener_duracion_formateada(ruta_video):
    try:
        duracion_segundos = obtener_duracion_video(ruta_video)
        return formatear_tiempo(duracion_segundos)
    except Exception:
        return "Desconocida"

def formatear_tamano(tamano_bytes):
    if tamano_bytes == 0:
        return "0 B"
    tamanos = ["B", "KB", "MB", "GB"]
    i = int(math.floor(math.log(tamano_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(tamano_bytes / p, 2)
    return f"{s} {tamanos[i]}"

def calcular_reduccion(tamano_original, tamano_convertido):
    if tamano_original == 0:
        return "0%"
    reduccion = ((tamano_original - tamano_convertido) / tamano_original) * 100
    if reduccion > 0:
        return f"📉 Reducción: {reduccion:.1f}%"
    elif reduccion < 0:
        return f"📈 Aumento: {abs(reduccion):.1f}%"
    else:
        return "⚖️ Sin cambios"

def es_administrador(user_id):
    return db.es_administrador(user_id)

def generar_thumbnail(ruta_video, ruta_salida, tiempo='00:00:05'):
    try:
        duracion = obtener_duracion_video(ruta_video)
        if duracion <= 0:
            logger.error("No se pudo obtener la duración del video.")
            return False

        ss = min(1, duracion / 2)

        comando = [
            "ffmpeg",
            "-ss", str(ss),
            "-i", ruta_video,
            "-vframes", "1",
            "-q:v", "2",
            "-vf", "scale=320:240",
            ruta_salida,
            "-y"
        ]
        
        subprocess.run(comando, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        return os.path.exists(ruta_salida)
    except Exception as e:
        logger.error(f"❌ Error generando thumbnail: {e}")
        return False

def crear_barra_progreso(porcentaje, longitud=20):
    bloques_llenos = int(porcentaje * longitud / 100)
    bloques_vacios = longitud - bloques_llenos
    return "█" * bloques_llenos + "░" * bloques_vacios

def extraer_error_ffmpeg(salida_error):
    lineas = salida_error.split('\n')
    for linea in reversed(lineas):
        linea = linea.strip()
        if linea and not linea.startswith('ffmpeg version') and not linea.startswith('built with') and not linea.startswith('configuration:'):
            if 'Error' in linea or 'error' in linea.lower() or 'failed' in linea.lower():
                return linea
    return '\n'.join(lineas[-3:]) if len(lineas) > 3 else salida_error

def parsear_tiempo_ffmpeg(cadena_tiempo):
    try:
        partes = cadena_tiempo.split(':')
        if len(partes) == 3:
            horas = int(partes[0])
            minutos = int(partes[1])
            segundos = float(partes[2])
            return horas * 3600 + minutos * 60 + segundos
        elif len(partes) == 2:
            minutos = int(partes[0])
            segundos = float(partes[1])
            return minutos * 60 + segundos
        else:
            return float(cadena_tiempo)
    except:
        return 0

def verificar_modo_soporte():
    return Config.MODO_SOPORTE

def obtener_calidad_para_usuario(user_id):
    config_personal = db.obtener_calidad_usuario(user_id)
    if config_personal:
        return config_personal
    return Config.DEFAULT_QUALITY

async def verificar_suscripcion_canales(user_id):
    try:
        canales = db.obtener_canales_requeridos()
        if not canales:
            return True
        
        for canal in canales:
            try:
                miembro = await app.get_chat_member(canal['canal_id'], user_id)
                if miembro.status not in [enums.ChatMemberStatus.MEMBER, enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER]:
                    return False, canal
            except Exception as e:
                logger.error(f"❌ Error verificando suscripción a {canal['nombre_canal']}: {e}")
                return False, canal
        
        return True, None
    except Exception as e:
        logger.error(f"❌ Error verificando suscripciones: {e}")
        return True, None

async def convertir_video_con_progreso(ruta_entrada, ruta_salida, duracion_total, actualizar_progreso, calidad_config):
    try:
        if not shutil.which("ffmpeg"):
            return False, "FFmpeg no disponible"
        
        codec = calidad_config["codec"]
        
        codec_map = {
            "libx264": "h264",
            "libx265": "hevc",
            "vp9": "vp9",
            "libvpx-vp9": "vp9",
            "aac": "aac"
        }
        
        if codec not in codec_map:
            return False, f"Codec {codec} no soportado"
        
        params_extra = []
        if codec == "libx265":
            params_extra.extend(["-x265-params", "log-level=error"])
        elif codec == "libx264":
            params_extra.extend(["-x264-params", "log-level=error"])
        elif codec == "libvpx-vp9":
            params_extra.extend(["-b:v", "0", "-crf", "30"])
        
        try:
            probe_cmd = [
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=codec_name",
                "-of", "default=noprint_wrappers=1:nokey=1",
                ruta_entrada
            ]
            
            resultado = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=10)
            codec_original = resultado.stdout.strip().lower()
            
            if codec_original in ["h264", "libx264"] and codec == "libx264":
                logger.info(f"✅ Video ya en {codec}, usando stream copy")
                return await convertir_con_copy(ruta_entrada, ruta_salida, duracion_total, actualizar_progreso)
                
        except Exception as e:
            logger.warning(f"⚠️ No se pudo detectar codec original: {e}")
        
        comando = [
            'ffmpeg',
            '-i', ruta_entrada,
            '-c:v', codec,
            '-preset', calidad_config["preset"],
            '-crf', calidad_config["crf"],
            '-vf', f'scale={calidad_config["resolution"]}:force_original_aspect_ratio=decrease',
            '-c:a', 'aac',
            '-b:a', calidad_config["audio_bitrate"],
            '-movflags', '+faststart',
            '-threads', '0',
            '-max_muxing_queue_size', '1024',
            '-progress', 'pipe:1',
            '-nostats',
            '-loglevel', 'error',
            '-y',
            ruta_salida
        ]
        
        comando.extend(params_extra)
        
        proceso = await asyncio.create_subprocess_exec(
            *comando,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        buffer_error = ""
        ultima_actualizacion = 0
        
        while True:
            chunk = await proceso.stderr.read(1024)
            if not chunk:
                break
                
            linea = chunk.decode('utf-8', errors='ignore')
            buffer_error += linea
            
            if 'out_time_ms' in linea:
                match = re.search(r'out_time_ms=(\d+)', linea)
                if match and duracion_total > 0:
                    tiempo_actual_ms = int(match.group(1))
                    tiempo_actual = tiempo_actual_ms / 1000000
                    
                    porcentaje = min(95, (tiempo_actual / duracion_total) * 100)
                    
                    ahora = time.time()
                    if ahora - ultima_actualizacion > 2:
                        await actualizar_progreso(porcentaje, formatear_tiempo(tiempo_actual))
                        ultima_actualizacion = ahora
        
        await proceso.wait()
        
        if proceso.returncode == 0 and os.path.exists(ruta_salida) and os.path.getsize(ruta_salida) > 0:
            return True, "✅ Conversión completada"
        else:
            error_real = extraer_error_ffmpeg(buffer_error)
            return False, f"❌ FFmpeg error: {error_real}"
            
    except asyncio.TimeoutError:
        return False, "⏱️ Tiempo de conversión excedido"
    except Exception as e:
        return False, f"❌ Error del sistema: {str(e)}"

async def convertir_con_copy(ruta_entrada, ruta_salida, duracion_total, actualizar_progreso):
    try:
        comando = [
            'ffmpeg',
            '-i', ruta_entrada,
            '-c', 'copy',
            '-movflags', '+faststart',
            '-progress', 'pipe:1',
            '-nostats',
            '-loglevel', 'error',
            '-y',
            ruta_salida
        ]
        
        proceso = await asyncio.create_subprocess_exec(
            *comando,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        buffer_error = ""
        ultima_actualizacion = 0
        
        while True:
            chunk = await proceso.stderr.read(1024)
            if not chunk:
                break
                
            linea = chunk.decode('utf-8', errors='ignore')
            buffer_error += linea
            
            if 'out_time_ms' in linea:
                match = re.search(r'out_time_ms=(\d+)', linea)
                if match and duracion_total > 0:
                    tiempo_actual_ms = int(match.group(1))
                    tiempo_actual = tiempo_actual_ms / 1000000
                    
                    porcentaje = min(95, (tiempo_actual / duracion_total) * 100)
                    
                    ahora = time.time()
                    if ahora - ultima_actualizacion > 2:
                        await actualizar_progreso(porcentaje, formatear_tiempo(tiempo_actual))
                        ultima_actualizacion = ahora
        
        await proceso.wait()
        
        if proceso.returncode == 0:
            return True, "✅ Conversión completada (stream copy)"
        else:
            error_real = extraer_error_ffmpeg(buffer_error)
            return False, f"❌ FFmpeg error: {error_real}"
            
    except Exception as e:
        return False, f"❌ Error en stream copy: {str(e)}"

async def procesar_video(cliente, mensaje, ruta_video, ruta_convertido, user_id):
    tiempo_inicio = time.time()
    mensaje_estado = None
    ruta_thumbnail = None
    
    async def actualizar_progreso(porcentaje, tiempo_actual=""):
        nonlocal mensaje_estado
        try:
            barra = crear_barra_progreso(porcentaje)
            texto_progreso = (
                f"🎬 **Convirtiendo Video**\n\n"
                f"📊 **Progreso:** {porcentaje:.1f}%\n"
                f"`{barra}`\n"
                f"⏱️ **Tiempo:** `{tiempo_actual}`\n\n"
                f"🔄 **Procesando...**"
            )
            if mensaje_estado:
                await mensaje_estado.edit_text(texto_progreso)
        except Exception:
            pass
    
    try:
        tamano_original = os.path.getsize(ruta_video)
        nombre_original = mensaje.video.file_name if mensaje.video else mensaje.document.file_name or "video"
        duracion_total = obtener_duracion_video(ruta_video)
        
        calidad_config = obtener_calidad_para_usuario(user_id)
        
        mensaje_estado = await mensaje.reply_text(
            "🎬 **Iniciando Conversión**\n\n"
            f"📁 **Archivo:** `{nombre_original[:25]}...`\n"
            f"📊 **Tamaño:** `{formatear_tamano(tamano_original)}`\n"
            f"⏱️ **Duración:** `{formatear_tiempo(duracion_total)}`\n"
            "🔄 **Preparando...**"
        )
        
        await actualizar_progreso(5, "00:00:00")
        
        exito, log = await convertir_video_con_progreso(
            ruta_video, ruta_convertido, duracion_total, actualizar_progreso, calidad_config
        )
        
        tiempo_procesamiento = time.time() - tiempo_inicio

        if not exito:
            mensaje_error = ""
            if "Permission denied" in log:
                mensaje_error = "❌ **Error de Permisos**\nNo se puede acceder a los archivos temporales."
            elif "Invalid data" in log or "Unsupported codec" in log:
                mensaje_error = "❌ **Formato No Soportado**\nEl formato de video no es compatible."
            elif "Cannot allocate memory" in log:
                mensaje_error = "❌ **Memoria Insuficiente**\nEl sistema no tiene suficiente memoria."
            else:
                mensaje_error = f"❌ **Error en Conversión**\n\n`{log}`"
            
            await mensaje_estado.edit_text(mensaje_error)
            sistema_colas.trabajo_completado(user_id, False, tiempo_procesamiento)
            return

        await actualizar_progreso(100, "✅ Completado")
        
        tamano_convertido = os.path.getsize(ruta_convertido)
        duracion_convertido = obtener_duracion_formateada(ruta_convertido)
        reduccion = calcular_reduccion(tamano_original, tamano_convertido)

        await mensaje_estado.edit_text(
            "✅ **Conversión Exitosa**\n\n"
            "📤 **Subiendo resultado...**\n"
            "🎉 **¡Casi listo!**"
        )

        db.agregar_video_convertido({
            'user_id': user_id,
            'nombre_archivo': nombre_original,
            'tamano_original': tamano_original,
            'tamano_convertido': tamano_convertido,
            'duracion_original': formatear_tiempo(duracion_total),
            'duracion_convertido': duracion_convertido,
            'calidad_config': json.dumps(calidad_config),
            'tiempo_procesamiento': tiempo_procesamiento
        })

        caption = (
            "✨ **Video Convertido** ✨\n\n"
            f"📁 **Archivo:** `{nombre_original[:30]}...`\n"
            f"📊 **Tamaño:** `{formatear_tamano(tamano_original)} → {formatear_tamano(tamano_convertido)}`\n"
            f"{reduccion}\n"
            f"⏱️ **Tiempo:** `{formatear_tiempo(tiempo_procesamiento)}`\n"
            f"🎯 **Calidad:** `{calidad_config['resolution']}`\n\n"
            f"🤖 @{cliente.me.username}"
        )

        if tamano_convertido > 10 * 1024 * 1024:
            ruta_thumbnail = f"thumb_{user_id}_{int(time.time())}.jpg"
            if await asyncio.to_thread(generar_thumbnail, ruta_convertido, ruta_thumbnail):
                with open(ruta_thumbnail, 'rb') as thumb:
                    await mensaje.reply_video(
                        video=ruta_convertido,
                        caption=caption,
                        supports_streaming=True,
                        thumb=thumb
                    )
            else:
                await mensaje.reply_video(
                    video=ruta_convertido,
                    caption=caption,
                    supports_streaming=True
                )
        else:
            await mensaje.reply_video(
                video=ruta_convertido,
                caption=caption,
                supports_streaming=True
            )

        await mensaje_estado.delete()
        sistema_colas.trabajo_completado(user_id, True, tiempo_procesamiento)

    except Exception as e:
        mensaje_error = f"❌ **Error en Procesamiento**\n\n`{str(e)[:100]}`"
        try:
            if mensaje_estado:
                await mensaje_estado.edit_text(mensaje_error)
            else:
                await mensaje.reply_text(mensaje_error)
        except:
            pass
        sistema_colas.trabajo_completado(user_id, False, time.time() - tiempo_inicio)
    finally:
        if ruta_thumbnail and os.path.exists(ruta_thumbnail):
            try:
                os.remove(ruta_thumbnail)
            except:
                pass

def registrar_usuario(func):
    async def wrapper(cliente, mensaje):
        user_id = mensaje.from_user.id
        
        if verificar_modo_soporte() and not es_administrador(user_id):
            await mensaje.reply_text(
                "🔧 **Modo Soporte Activado**\n\n"
                "🤖 El bot está en mantenimiento temporal.\n"
                "⏳ Por favor, vuelve más tarde.\n\n"
                "🙏 Gracias por tu comprensión."
            )
            return
        
        baneado, razon = db.usuario_baneado(user_id)
        if baneado:
            await mensaje.reply_text(
                f"🚫 **Usuario Baneado**\n\n"
                f"📝 **Razón:** {razon}\n\n"
                f"📞 **Contacta con un administrador**\n"
                f"si crees que es un error."
            )
            return
        
        suscrito, canal_no_suscrito = await verificar_suscripcion_canales(user_id)
        if not suscrito:
            canales = db.obtener_canales_requeridos()
            keyboard = InlineKeyboardMarkup([])
            
            for canal in canales:
                if canal['enlace_canal']:
                    keyboard.inline_keyboard.append([
                        InlineKeyboardButton(
                            f"📢 Unirse a {canal['nombre_canal']}",
                            url=canal['enlace_canal']
                        )
                    ])
            
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(
                    "✅ Verificar Suscripción",
                    callback_data="verificar_suscripcion"
                )
            ])
            
            await mensaje.reply_text(
                "📢 **Suscripción Requerida**\n\n"
                "🔒 Para usar este bot, debes estar unido a los siguientes canales:\n\n"
                + "\n".join([f"• {canal['nombre_canal']}" for canal in canales]) + "\n\n"
                "👇 **Únete a los canales y verifica tu suscripción:**",
                reply_markup=keyboard
            )
            return
        
        db.agregar_actualizar_usuario({
            'user_id': user_id,
            'username': mensaje.from_user.username,
            'first_name': mensaje.from_user.first_name,
            'last_name': mensaje.from_user.last_name,
            'language_code': mensaje.from_user.language_code
        })
        
        return await func(cliente, mensaje)
    return wrapper

def solo_administrador(func):
    async def wrapper(cliente, mensaje):
        user_id = mensaje.from_user.id
        
        if not es_administrador(user_id):
            await mensaje.reply_text(
                "🚫 **Acceso Denegado**\n\n"
                "👑 Este comando está disponible solo para administradores.\n"
                "📞 Contacta con un administrador si necesitas ayuda."
            )
            return
        
        return await func(cliente, mensaje)
    return wrapper

@app.on_message(filters.video | filters.document)
@registrar_usuario
async def manejar_video(cliente: Client, mensaje: Message):
    user_id = mensaje.from_user.id
    
    try:
        if mensaje.document and not mensaje.document.mime_type.startswith('video'):
            await mensaje.reply_text(
                "❌ **Formato No Soportado**\n\n"
                "📁 **Envía un archivo de video válido:**\n"
                "🎥 MP4, AVI, MKV, MOV, etc."
            )
            return

        es_admin = es_administrador(user_id)
        
        limite_bytes = Config.MAX_FILE_SIZE_MB * 1024 * 1024
        if mensaje.video:
            tamano_video = mensaje.video.file_size
        else:
            tamano_video = mensaje.document.file_size
            
        if not es_admin and tamano_video > limite_bytes:
            await mensaje.reply_text(
                "📏 **Límite Excedido**\n\n"
                f"📊 **Tu archivo:** `{formatear_tamano(tamano_video)}`\n"
                f"⚖️ **Límite permitido:** `{Config.MAX_FILE_SIZE_MB} MB`\n\n"
                "💡 **Reduce el tamaño del video**"
            )
            return

        ruta_video = await mensaje.download()
        ruta_convertido = f"convertido_{user_id}_{int(time.time())}.mp4"

        nombre_original = mensaje.video.file_name if mensaje.video else mensaje.document.file_name or "video"
        
        trabajo = {
            "cliente": cliente,
            "mensaje": mensaje,
            "ruta_video": ruta_video,
            "ruta_convertido": ruta_convertido,
            "user_id": user_id,
            "nombre_archivo": nombre_original
        }

        estado = sistema_colas.agregar_trabajo(user_id, trabajo, es_admin)
        
        if estado == "limite_usuario":
            await mensaje.reply_text(
                "⏳ **Límite Alcanzado**\n\n"
                "📊 **Solo puedes tener 3 videos en procesamiento/cola.**\n"
                "🕐 **Espera a que se completen algunos.**"
            )
            if os.path.exists(ruta_video):
                os.remove(ruta_video)
            return
        
        estadisticas = sistema_colas.obtener_estadisticas()
        
        if estado == "procesando":
            await mensaje.reply_text(
                "⚡ **Procesamiento Inmediato**\n\n"
                f"🎬 **Tu video ha comenzado a procesarse**\n"
                f"⚡ **Procesos activos:** `{estadisticas['procesando']}/{estadisticas['max_concurrente']}`\n"
                "⏳ **Recibirás el resultado pronto...**"
            )
            asyncio.create_task(
                procesar_y_limpiar(cliente, mensaje, ruta_video, ruta_convertido, user_id)
            )
        elif estado.startswith("prioridad"):
            posicion = estado.split('_')[1]
            await mensaje.reply_text(
                "⭐ **Video en Cola Prioritaria**\n\n"
                f"🎯 **Posición en cola:** `#{posicion}`\n"
                f"⚡ **Procesos activos:** `{estadisticas['procesando']}/{estadisticas['max_concurrente']}`\n"
                "🕐 **Será procesado con prioridad**"
            )
        else:
            posicion = estado.split('_')[1]
            await mensaje.reply_text(
                "📥 **Video Agregado a la Cola**\n\n"
                f"🎯 **Posición en cola:** `#{posicion}`\n"
                f"⚡ **Procesos activos:** `{estadisticas['procesando']}/{estadisticas['max_concurrente']}`\n"
                f"📊 **En espera:** `{estadisticas['en_espera']}`\n\n"
                "🕐 **Será procesado en orden de llegada**"
            )
        
    except Exception as e:
        await mensaje.reply_text(
            "❌ **Error al Procesar**\n\n"
            f"📝 **Detalles:** `{str(e)[:100]}`\n\n"
            "🆘 **Usa** `/help` **si el problema persiste**"
        )

async def procesar_y_limpiar(cliente, mensaje, ruta_video, ruta_convertido, user_id):
    try:
        await procesar_video(cliente, mensaje, ruta_video, ruta_convertido, user_id)
    except Exception as e:
        logger.error(f"❌ Error en procesamiento: {e}")
    finally:
        for archivo in [ruta_video, ruta_convertido]:
            if archivo and os.path.exists(archivo):
                try:
                    os.remove(archivo)
                except:
                    pass
        
        siguiente_user_id, siguiente_trabajo = sistema_colas.trabajo_completado(user_id)
        if siguiente_trabajo:
            asyncio.create_task(
                procesar_y_limpiar(
                    siguiente_trabajo["cliente"],
                    siguiente_trabajo["mensaje"],
                    siguiente_trabajo["ruta_video"],
                    siguiente_trabajo["ruta_convertido"],
                    siguiente_user_id
                )
            )

@app.on_callback_query(filters.regex("verificar_suscripcion"))
async def verificar_suscripcion_callback(cliente, callback_query):
    user_id = callback_query.from_user.id
    
    suscrito, canal_no_suscrito = await verificar_suscripcion_canales(user_id)
    
    if suscrito:
        await callback_query.answer(
            "✅ ¡Ya estás suscrito a todos los canales! Ahora puedes usar el bot.",
            show_alert=True
        )
        await callback_query.message.delete()
        
        await callback_query.message.reply_text(
            "🎉 **¡Bienvenido!**\n\n"
            "✅ **Verificación completada exitosamente.**\n"
            "🤖 **Ahora puedes usar el bot normalmente.**\n\n"
            "📤 **Envía cualquier video para comenzar.**"
        )
    else:
        await callback_query.answer(
            f"❌ Aún no estás suscrito a: {canal_no_suscrito['nombre_canal']}",
            show_alert=True
        )

@app.on_message(filters.command("start"))
@registrar_usuario
async def comando_inicio(cliente: Client, mensaje: Message):
    estadisticas = sistema_colas.obtener_estadisticas()
    estadisticas_bot = db.obtener_estadisticas_generales()
    
    canales = db.obtener_canales_requeridos()
    info_canales = ""
    if canales:
        info_canales = "\n\n📢 **Canales requeridos:**\n"
        for canal in canales:
            info_canales += f"• {canal['nombre_canal']}\n"
    
    texto = (
        "🤖 **Bienvenido al Conversor de Videos**\n\n"
        f"👋 **Hola {mensaje.from_user.first_name}!**\n\n"
        "🎯 **Características principales:**\n"
        "✨ Conversión a MP4 HD\n"
        "⚡ Compresión inteligente\n"
        "📊 Sistema de colas avanzado\n"
        "🎨 Calidad personalizable\n\n"
        f"📏 **Límite por archivo:** `{Config.MAX_FILE_SIZE_MB} MB`\n"
        f"⚡ **Procesos simultáneos:** `{estadisticas['max_concurrente']}`\n"
        f"📈 **Videos convertidos:** `{estadisticas_bot['total_videos']}`"
        f"{info_canales}\n\n"
        "🚀 **Para comenzar:** Simplemente envía cualquier video"
    )
    
    await mensaje.reply_text(texto)

@app.on_message(filters.command("help"))
@registrar_usuario
async def comando_ayuda(cliente: Client, mensaje: Message):
    texto = (
        "📚 **Centro de Ayuda** 🤖\n\n"
        
        "🎬 **Proceso de conversión:**\n"
        "1. 📤 Envía cualquier archivo de video\n"
        "2. ⚙️ Procesamiento automático\n"
        "3. 📊 Barra de progreso en tiempo real\n"
        "4. 📥 Recibe el video convertido en MP4\n\n"
        
        "⚡ **Sistema de colas:**\n"
        "• Máximo 3 videos por usuario\n"
        "• Los administradores tienen prioridad\n"
        "• Verifica tu posición con /cola\n\n"
        
        "⚙️ **Comandos disponibles:**\n"
        "• /start - Información básica\n"
        "• /help - Este mensaje de ayuda\n"
        "• /info - Estado del sistema\n"
        "• /cola - Tu posición en la cola\n"
        "• /historial - Tus conversiones\n"
        "• /calidad - Configurar calidad\n\n"
        
        "🔧 **Configuración actual:**\n"
        f"• 📏 Límite: `{Config.MAX_FILE_SIZE_MB} MB`\n"
        f"• 🎨 Resolución: `{Config.DEFAULT_QUALITY['resolution']}`\n"
        f"• ⚡ CRF: `{Config.DEFAULT_QUALITY['crf']}`\n"
        f"• 🔊 Audio: `{Config.DEFAULT_QUALITY['audio_bitrate']}`\n\n"
        
        "💡 **Consejo:** Usa /calidad para personalizar tu experiencia"
    )
    
    await mensaje.reply_text(texto)

@app.on_message(filters.command("info"))
@registrar_usuario
async def comando_info(cliente: Client, mensaje: Message):
    try:
        uso_cpu = psutil.cpu_percent()
        memoria = psutil.virtual_memory()
        disco = psutil.disk_usage('/')
        
        estadisticas = sistema_colas.obtener_estadisticas()
        estadisticas_bot = db.obtener_estadisticas_generales()
        
        tipo_usuario = "👑 Administrador" if es_administrador(mensaje.from_user.id) else "👤 Usuario"
        
        texto_info = (
            "📊 **Estado Completo del Sistema**\n\n"
            
            "👤 **Información de Usuario**\n"
            f"• 🏷️ **Nombre:** {mensaje.from_user.first_name}\n"
            f"• 🔢 **ID:** `{mensaje.from_user.id}`\n"
            f"• 👥 **Tipo:** {tipo_usuario}\n\n"
            
            "🤖 **Estadísticas Globales**\n"
            f"• 👥 **Usuarios registrados:** `{estadisticas_bot['total_usuarios']}`\n"
            f"• 🚫 **Usuarios baneados:** `{estadisticas_bot['usuarios_baneados']}`\n"
            f"• 👑 **Administradores:** `{estadisticas_bot['total_admins']}`\n"
            f"• 🎬 **Videos convertidos:** `{estadisticas_bot['total_videos']}`\n"
            f"• 💾 **Espacio ahorrado:** `{formatear_tamano(estadisticas_bot['espacio_ahorrado'])}`\n\n"
            
            "⚡ **Sistema de Colas**\n"
            f"• ⚙️ **Procesando ahora:** `{estadisticas['procesando']}/{estadisticas['max_concurrente']}`\n"
            f"• 📥 **En espera:** `{estadisticas['en_espera']}`\n"
            f"• ⭐ **Cola prioritaria:** `{estadisticas['prioridad']}`\n"
            f"• 📊 **Cola normal:** `{estadisticas['normal']}`\n"
            f"• ✅ **Completados (sesión):** `{estadisticas['completados']}`\n"
            f"• ❌ **Errores (sesión):** `{estadisticas['errores']}`\n"
            f"• ⏱️ **Tiempo promedio:** `{formatear_tiempo(estadisticas['tiempo_promedio'])}`\n\n"
            
            "🖥️ **Estado del Servidor**\n"
            f"• 🖥️ **Uso de CPU:** `{uso_cpu:.1f}%`\n"
            f"• 💾 **Uso de memoria:** `{memoria.percent:.1f}%`\n"
            f"• 📀 **Uso de almacenamiento:** `{disco.percent:.1f}%`\n"
            f"• 💿 **Espacio libre:** `{formatear_tamano(disco.free)}`\n\n"
            
            f"🔧 **Modo soporte:** {'🟢 Activado' if Config.MODO_SOPORTE else '🔴 Desactivado'}"
        )
        
    except Exception as e:
        logger.error(f"❌ Error en info: {e}")
        estadisticas = sistema_colas.obtener_estadisticas()
        texto_info = (
            "📊 **Información del Sistema**\n\n"
            f"👤 **Usuario:** {mensaje.from_user.first_name}\n"
            f"📏 **Límite:** {Config.MAX_FILE_SIZE_MB}MB\n"
            f"⚡ **Procesos:** {estadisticas['procesando']}/{estadisticas['max_concurrente']}\n"
            f"📥 **En cola:** {estadisticas['en_espera']}\n"
            f"✅ **Completados:** {estadisticas['completados']}\n\n"
            "🟢 **Sistema operativo**"
        )
    
    await mensaje.reply_text(texto_info)

@app.on_message(filters.command("cola"))
@registrar_usuario
async def comando_cola(cliente: Client, mensaje: Message):
    estadisticas = sistema_colas.obtener_estadisticas()
    estado_usuario = sistema_colas.obtener_estado(mensaje.from_user.id)
    detalle_cola = sistema_colas.obtener_detalle_cola()
    
    es_admin = es_administrador(mensaje.from_user.id)
    
    if estado_usuario == "procesando":
        emoji_estado = "⚡"
        texto_estado = "Tu video se está procesando ahora mismo"
        tiempo_estimado = f"⏱️ **Tiempo estimado:** `{formatear_tiempo(estadisticas['tiempo_promedio'])}`"
    elif estado_usuario.startswith("prioridad"):
        posicion = estado_usuario.split('_')[1]
        emoji_estado = "⭐"
        texto_estado = f"Tu video está en cola prioritaria (posición #{posicion})"
        tiempo_estimado = f"⏱️ **Tiempo estimado:** `{formatear_tiempo(int(posicion) * estadisticas['tiempo_promedio'])}`"
    elif estado_usuario.startswith("encolado"):
        posicion = estado_usuario.split('_')[1]
        emoji_estado = "📥"
        texto_estado = f"Tu video está en cola normal (posición #{posicion})"
        tiempo_estimado = f"⏱️ **Tiempo estimado:** `{formatear_tiempo(int(posicion) * estadisticas['tiempo_promedio'])}`"
    else:
        emoji_estado = "✅"
        texto_estado = "No tienes videos en procesamiento"
        tiempo_estimado = "📤 Puedes enviar un video para comenzar"
    
    texto = (
        "📊 **Estado de la Cola de Procesamiento**\n\n"
        f"{emoji_estado} **Tu estado:** {texto_estado}\n"
        f"{tiempo_estimado}\n\n"
        
        "📈 **Estadísticas de la Cola**\n"
        f"• ⚡ **Procesando actualmente:** `{estadisticas['procesando']}/{estadisticas['max_concurrente']}`\n"
        f"• 📥 **Videos en espera:** `{estadisticas['en_espera']}`\n"
        f"• ⭐ **En cola prioritaria:** `{estadisticas['prioridad']}`\n"
        f"• 📊 **En cola normal:** `{estadisticas['normal']}`\n"
        f"• ⏱️ **Tiempo promedio:** `{formatear_tiempo(estadisticas['tiempo_promedio'])}`\n\n"
    )
    
    if es_admin:
        texto += "👑 **Detalle Completo de la Cola**\n"
        
        if detalle_cola["procesando"]:
            texto += "⚡ **Procesando ahora:**\n"
            for trabajo in detalle_cola["procesando"]:
                texto += f"  • 👤 **ID:** `{trabajo['user_id']}` - 📁 **Archivo:** `{trabajo['nombre_archivo'][:20]}...`\n"
            texto += "\n"
        
        if detalle_cola["prioridad"]:
            texto += "⭐ **Cola prioritaria:**\n"
            for i, trabajo in enumerate(detalle_cola["prioridad"], 1):
                texto += f"  {i}. 👤 **ID:** `{trabajo['user_id']}` - 📁 **Archivo:** `{trabajo['nombre_archivo'][:20]}...`\n"
            texto += "\n"
        
        if detalle_cola["normal"]:
            texto += "📥 **Cola normal:**\n"
            for i, trabajo in enumerate(detalle_cola["normal"], 1):
                texto += f"  {i}. 👤 **ID:** `{trabajo['user_id']}` - 📁 **Archivo:** `{trabajo['nombre_archivo'][:20]}...`\n"
            texto += "\n"
    
    texto += "🚀 **¿Listo para convertir otro video?**"
    
    await mensaje.reply_text(texto)

@app.on_message(filters.command("historial"))
@registrar_usuario
async def comando_historial(cliente: Client, mensaje: Message):
    user_id = mensaje.from_user.id
    historial = db.obtener_historial_usuario(user_id, limite=10)
    usuario = db.obtener_usuario(user_id)
    
    if not historial:
        await mensaje.reply_text(
            "📝 **Tu Historial de Conversiones**\n\n"
            "📭 **Aún no has convertido videos**\n\n"
            "🚀 **Para comenzar:**\n"
            "📤 Envía cualquier archivo de video\n"
            "⚙️ El bot lo procesará automáticamente\n"
            "📥 Recibirás el resultado en MP4\n\n"
            "🎯 **Formatos soportados:**\n"
            "🎥 MP4, AVI, MKV, MOV, WMV, FLV, WebM\n\n"
            "✨ **¡Tu historial aparecerá aquí después de tu primera conversión!**"
        )
        return
    
    texto = f"📝 **Tu Historial de Conversiones**\n\n"
    texto += f"👤 **Usuario:** {mensaje.from_user.first_name}\n"
    texto += f"📊 **Total de conversiones:** `{usuario['total_conversiones'] if usuario else len(historial)}`\n\n"
    
    total_ahorro = 0
    for i, conversion in enumerate(historial, 1):
        reduccion = conversion['tamano_original'] - conversion['tamano_convertido']
        porcentaje = (reduccion / conversion['tamano_original']) * 100 if conversion['tamano_original'] > 0 else 0
        total_ahorro += max(0, reduccion)
        
        texto += (
            f"**{i}. {conversion['nombre_archivo'][:20]}...**\n"
            f"   📊 **Tamaño:** `{formatear_tamano(conversion['tamano_original'])} → {formatear_tamano(conversion['tamano_convertido'])}`\n"
            f"   📅 **Fecha:** `{conversion['fecha_conversion'][:16]}`\n\n"
        )
    
    texto += f"💾 **Espacio total ahorrado:** `{formatear_tamano(total_ahorro)}`"
    
    await mensaje.reply_text(texto)

@app.on_message(filters.command("calidad"))
@registrar_usuario
async def comando_calidad(cliente: Client, mensaje: Message):
    user_id = mensaje.from_user.id
    es_admin = es_administrador(user_id)
    texto = mensaje.text.split()
    
    if len(texto) == 1:
        calidad_actual = obtener_calidad_para_usuario(user_id)
        es_personal = db.obtener_calidad_usuario(user_id) is not None
        
        tipo_config = "personalizada" if es_personal else "global (por defecto)"
        alcance = "solo para ti" if not es_admin and es_personal else "para todos los usuarios" if es_admin else "para todos los usuarios (global)"
        
        respuesta = (
            f"⚙️ **Configuración de Calidad**\n\n"
            f"📋 **Tipo de configuración:** {tipo_config}\n"
            f"🎯 **Alcance:** {alcance}\n\n"
            f"📊 **Valores actuales:**\n"
            f"• 🎨 **Resolución:** `{calidad_actual['resolution']}`\n"
            f"• ⚡ **Calidad CRF:** `{calidad_actual['crf']}` (0-51, menor es mejor)\n"
            f"• 🔊 **Audio:** `{calidad_actual['audio_bitrate']}`\n"
            f"• 📺 **FPS:** `{calidad_actual['fps']}`\n"
            f"• 🛠️ **Preset:** `{calidad_actual['preset']}`\n"
            f"• 🔧 **Codec:** `{calidad_actual['codec']}`\n\n"
        )
        
        if es_admin:
            respuesta += (
                "👑 **Como administrador:**\n"
                "• 🔄 Tus cambios afectan a TODOS los usuarios\n"
                "• 🔄 Usa '/calidad reset' para restaurar valores globales\n\n"
                "🔄 **Para modificar:**\n"
                "`/calidad parametro=valor`\n\n"
                "💡 **Ejemplos:**\n"
                "• `/calidad resolution=1920x1080`\n"
                "• `/calidad crf=18 audio_bitrate=192k`\n"
                "• `/calidad preset=fast codec=libx265`\n\n"
                "📋 **Parámetros disponibles:**\n"
                "`resolution, crf, audio_bitrate, fps, preset, codec`"
            )
        else:
            respuesta += (
                "👤 **Como usuario:**\n"
                "• 🔄 Tus cambios solo te afectan a TI\n"
                "• 🔄 Usa '/calidad reset' para usar valores globales\n\n"
                "🔄 **Para modificar:**\n"
                "`/calidad parametro=valor`\n\n"
                "💡 **Ejemplos:**\n"
                "• `/calidad resolution=1280x720`\n"
                "• `/calidad crf=25`\n"
                "• `/calidad audio_bitrate=192k`\n\n"
                "📋 **Parámetros disponibles:**\n"
                "`resolution, crf, audio_bitrate, fps, preset, codec`"
            )
        
        await mensaje.reply_text(respuesta)
        return
    
    if texto[1].lower() == 'reset':
        if es_admin:
            Config.DEFAULT_QUALITY = {
                "resolution": "1280x720",
                "crf": "23",
                "audio_bitrate": "128k",
                "fps": "30",
                "preset": "medium",
                "codec": "libx264"
            }
            db.actualizar_configuracion('calidad_default', json.dumps(Config.DEFAULT_QUALITY))
            await mensaje.reply_text("✅ **Configuración Global Restaurada**\n\n🔄 Se han restablecido los valores por defecto para TODOS los usuarios.")
        else:
            db.eliminar_calidad_usuario(user_id)
            await mensaje.reply_text("✅ **Configuración Personal Restaurada**\n\n🔄 Has vuelto a usar la configuración global por defecto.")
        return
    
    try:
        parametros = " ".join(texto[1:]).split()
        cambios = []
        
        if es_admin:
            config_a_modificar = Config.DEFAULT_QUALITY.copy()
        else:
            config_personal = db.obtener_calidad_usuario(user_id)
            if config_personal:
                config_a_modificar = config_personal.copy()
            else:
                config_a_modificar = Config.DEFAULT_QUALITY.copy()
        
        for param in parametros:
            if '=' in param:
                key, value = param.split('=', 1)
                if key in config_a_modificar:
                    valor_anterior = config_a_modificar[key]
                    config_a_modificar[key] = value
                    cambios.append(f"• **{key}:** `{valor_anterior}` → `{value}`")
        
        if cambios:
            if es_admin:
                if db.actualizar_configuracion('calidad_default', json.dumps(config_a_modificar)):
                    Config.DEFAULT_QUALITY = config_a_modificar
                    respuesta = "✅ **Configuración Global Actualizada**\n\n"
                else:
                    respuesta = "❌ **Error actualizando configuración global**\n\n"
            else:
                if db.guardar_calidad_usuario(user_id, config_a_modificar):
                    respuesta = "✅ **Configuración Personal Actualizada**\n\n"
                else:
                    respuesta = "❌ **Error actualizando configuración personal**\n\n"
            
            respuesta += "📊 **Cambios realizados:**\n" + "\n".join(cambios) + "\n\n"
            
            if es_admin:
                respuesta += "👥 **Alcance:** Todos los usuarios\n⚡ **Estado:** Aplicado inmediatamente"
            else:
                respuesta += "👤 **Alcance:** Solo tus conversiones\n⚡ **Estado:** Aplicado en tu próximo video"
            
        else:
            respuesta = "❌ **Sin Cambios Válidos**\n\n📝 No se encontraron parámetros válidos para modificar.\n\n📋 **Parámetros aceptados:**\n`resolution, crf, audio_bitrate, fps, preset, codec`"
        
        await mensaje.reply_text(respuesta)
        
    except Exception as e:
        await mensaje.reply_text(f"❌ **Error en la Configuración**\n\n📝 **Detalles:** `{str(e)[:100]}`")

@app.on_message(filters.command("addchannel"))
@solo_administrador
async def comando_addchannel(cliente: Client, mensaje: Message):
    texto = mensaje.text.split()
    
    if len(texto) < 3:
        await mensaje.reply_text(
            "📢 **Agregar Canal Requerido**\n\n"
            "🔄 **Uso:**\n"
            "`/addchannel @nombre_canal enlace_del_canal`\n\n"
            "💡 **Ejemplo:**\n"
            "`/addchannel @ProyectNexuscanal https://t.me/ProyectNexuscanal`\n\n"
            "📋 **Canales actuales:**\n"
        )
        
        canales = db.obtener_canales_requeridos()
        if canales:
            for canal in canales:
                await mensaje.reply_text(
                    f"• **Nombre:** {canal['nombre_canal']}\n"
                    f"• **ID:** {canal['canal_id']}\n"
                    f"• **Enlace:** {canal['enlace_canal']}\n"
                    f"• **Agregado por:** {canal['agregado_por']}\n"
                    f"• **Fecha:** {canal['fecha_agregado'][:16]}"
                )
        else:
            await mensaje.reply_text("📭 No hay canales requeridos configurados.")
        
        return
    
    try:
        nombre_canal = texto[1]
        enlace_canal = texto[2]
        agregado_por = mensaje.from_user.id
        
        if not nombre_canal.startswith('@'):
            await mensaje.reply_text("❌ **Error:** El nombre del canal debe comenzar con @")
            return
        
        if db.canal_existe(nombre_canal):
            await mensaje.reply_text("❌ **Este canal ya está en la lista de requeridos.**")
            return
        
        if db.agregar_canal_requerido(nombre_canal, nombre_canal, enlace_canal, agregado_por):
            await mensaje.reply_text(
                f"✅ **Canal Agregado Correctamente**\n\n"
                f"📢 **Canal:** {nombre_canal}\n"
                f"🔗 **Enlace:** {enlace_canal}\n"
                f"👑 **Agregado por:** {agregado_por}\n\n"
                f"⚠️ **Nota:** Ahora los usuarios deberán estar unidos a este canal para usar el bot."
            )
        else:
            await mensaje.reply_text("❌ **Error al agregar el canal.**")
            
    except Exception as e:
        await mensaje.reply_text(f"❌ **Error:** `{str(e)[:100]}`")

@app.on_message(filters.command("delchannel"))
@solo_administrador
async def comando_delchannel(cliente: Client, mensaje: Message):
    texto = mensaje.text.split()
    
    if len(texto) != 2:
        canales = db.obtener_canales_requeridos()
        
        if not canales:
            await mensaje.reply_text("📭 **No hay canales requeridos configurados.**")
            return
        
        lista_canales = "📋 **Canales Requeridos**\n\n"
        for i, canal in enumerate(canales, 1):
            lista_canales += (
                f"{i}. **Canal:** {canal['nombre_canal']}\n"
                f"   **ID:** {canal['canal_id']}\n"
                f"   **Enlace:** {canal['enlace_canal']}\n"
                f"   **Agregado:** {canal['fecha_agregado'][:16]}\n\n"
            )
        
        lista_canales += "🗑️ **Para eliminar un canal:**\n`/delchannel @nombre_canal`"
        
        await mensaje.reply_text(lista_canales)
        return
    
    try:
        nombre_canal = texto[1]
        
        if not nombre_canal.startswith('@'):
            await mensaje.reply_text("❌ **Error:** El nombre del canal debe comenzar con @")
            return
        
        if db.eliminar_canal_requerido(nombre_canal):
            await mensaje.reply_text(
                f"✅ **Canal Eliminado Correctamente**\n\n"
                f"🗑️ **Canal eliminado:** {nombre_canal}\n\n"
                f"⚠️ **Nota:** Los usuarios ya NO necesitarán estar unidos a este canal para usar el bot."
            )
        else:
            await mensaje.reply_text("❌ **Canal no encontrado.**")
            
    except Exception as e:
        await mensaje.reply_text(f"❌ **Error:** `{str(e)[:100]}`")

@app.on_message(filters.command("channels"))
async def comando_channels(cliente: Client, mensaje: Message):
    canales = db.obtener_canales_requeridos()
    
    if not canales:
        await mensaje.reply_text(
            "📭 **No hay canales requeridos**\n\n"
            "🔓 Actualmente no es necesario unirse a ningún canal para usar el bot."
        )
        return
    
    keyboard = InlineKeyboardMarkup([])
    
    for canal in canales:
        if canal['enlace_canal']:
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(
                    f"📢 Unirse a {canal['nombre_canal']}",
                    url=canal['enlace_canal']
                )
            ])
    
    keyboard.inline_keyboard.append([
        InlineKeyboardButton(
            "✅ Verificar Suscripción",
            callback_data="verificar_suscripcion"
        )
    ])
    
    lista_canales = "\n".join([f"• {canal['nombre_canal']}" for canal in canales])
    
    await mensaje.reply_text(
        "📢 **Canales Requeridos**\n\n"
        f"🔒 Para usar este bot, debes estar unido a los siguientes canales:\n\n"
        f"{lista_canales}\n\n"
        "👇 **Haz clic en los botones para unirte y luego verifica tu suscripción:**",
        reply_markup=keyboard
    )

@app.on_message(filters.command("allvideos"))
@solo_administrador
async def comando_allvideos(cliente: Client, mensaje: Message):
    texto = mensaje.text.split()
    
    pagina = 1
    if len(texto) > 1:
        try:
            pagina = int(texto[1])
            if pagina < 1:
                pagina = 1
        except:
            pass
    
    limite = 10
    offset = (pagina - 1) * limite
    
    videos, total = db.obtener_todos_videos(limite, offset)
    
    if not videos:
        await mensaje.reply_text("📭 **No hay videos registrados en la base de datos.**")
        return
    
    total_paginas = math.ceil(total / limite)
    
    texto_respuesta = f"📊 **Todos los Videos Convertidos**\n\n"
    texto_respuesta += f"📈 **Total:** `{total}` videos\n"
    texto_respuesta += f"📑 **Página:** `{pagina}/{total_paginas}`\n\n"
    
    for i, video in enumerate(videos, offset + 1):
        usuario_info = f"👤 `{video['user_id']}`"
        if video['username']:
            usuario_info += f" (@{video['username']})"
        elif video['first_name']:
            usuario_info += f" ({video['first_name']})"
        
        texto_respuesta += (
            f"**{i}. {video['nombre_archivo'][:25]}...**\n"
            f"   {usuario_info}\n"
            f"   📊 `{formatear_tamano(video['tamano_original'])} → {formatear_tamano(video['tamano_convertido'])}`\n"
            f"   ⏱️ `{formatear_tiempo(video['tiempo_procesamiento'])}`\n"
            f"   📅 `{video['fecha_conversion'][:16]}`\n\n"
        )
    
    if total_paginas > 1:
        keyboard = []
        if pagina > 1:
            keyboard.append(InlineKeyboardButton("◀️ Anterior", callback_data=f"allvideos_{pagina-1}"))
        if pagina < total_paginas:
            keyboard.append(InlineKeyboardButton("Siguiente ▶️", callback_data=f"allvideos_{pagina+1}"))
        
        reply_markup = InlineKeyboardMarkup([keyboard]) if keyboard else None
        await mensaje.reply_text(texto_respuesta, reply_markup=reply_markup)
    else:
        await mensaje.reply_text(texto_respuesta)

@app.on_callback_query(filters.regex(r"^allvideos_(\d+)$"))
async def manejar_paginacion_videos(cliente, callback_query):
    user_id = callback_query.from_user.id
    
    if not es_administrador(user_id):
        await callback_query.answer("🚫 Solo para administradores", show_alert=True)
        return
    
    try:
        pagina = int(callback_query.data.split('_')[1])
        
        limite = 10
        offset = (pagina - 1) * limite
        
        videos, total = db.obtener_todos_videos(limite, offset)
        
        if not videos:
            await callback_query.answer("❌ No hay más videos", show_alert=True)
            return
        
        total_paginas = math.ceil(total / limite)
        
        texto_respuesta = f"📊 **Todos los Videos Convertidos**\n\n"
        texto_respuesta += f"📈 **Total:** `{total}` videos\n"
        texto_respuesta += f"📑 **Página:** `{pagina}/{total_paginas}`\n\n"
        
        for i, video in enumerate(videos, offset + 1):
            usuario_info = f"👤 `{video['user_id']}`"
            if video['username']:
                usuario_info += f" (@{video['username']})"
            elif video['first_name']:
                usuario_info += f" ({video['first_name']})"
            
            texto_respuesta += (
                f"**{i}. {video['nombre_archivo'][:25]}...**\n"
                f"   {usuario_info}\n"
                f"   📊 `{formatear_tamano(video['tamano_original'])} → {formatear_tamano(video['tamano_convertido'])}`\n"
                f"   ⏱️ `{formatear_tiempo(video['tiempo_procesamiento'])}`\n"
                f"   📅 `{video['fecha_conversion'][:16]}`\n\n"
            )
        
        keyboard = []
        if pagina > 1:
            keyboard.append(InlineKeyboardButton("◀️ Anterior", callback_data=f"allvideos_{pagina-1}"))
        if pagina < total_paginas:
            keyboard.append(InlineKeyboardButton("Siguiente ▶️", callback_data=f"allvideos_{pagina+1}"))
        
        reply_markup = InlineKeyboardMarkup([keyboard]) if keyboard else None
        
        await callback_query.message.edit_text(texto_respuesta, reply_markup=reply_markup)
        await callback_query.answer()
        
    except Exception as e:
        await callback_query.answer(f"❌ Error: {str(e)[:50]}", show_alert=True)

@app.on_message(filters.command("database"))
@solo_administrador
async def comando_database(cliente: Client, mensaje: Message):
    
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📤 Exportar DB", callback_data="export_db"),
            InlineKeyboardButton("📥 Importar DB", callback_data="import_db")
        ],
        [
            InlineKeyboardButton("📊 Estadísticas DB", callback_data="db_stats")
        ]
    ])
    
    await mensaje.reply_text(
        "🗄️ **Gestión de Base de Datos**\n\n"
        "📁 **Selecciona una opción:**\n\n"
        "📤 **Exportar DB** - Descarga copia de seguridad\n"
        "📥 **Importar DB** - Restaura desde backup\n"
        "📊 **Estadísticas** - Información de la DB",
        reply_markup=keyboard
    )

@app.on_callback_query(filters.regex(r"^(export_db|import_db|db_stats)$"))
async def manejar_botones_db(cliente, callback_query):
    user_id = callback_query.from_user.id
    
    if not es_administrador(user_id):
        await callback_query.answer("🚫 Solo para administradores", show_alert=True)
        return
    
    data = callback_query.data
    
    if data == "export_db":
        try:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = f"backup_db_{timestamp}.db"
            zip_file = f"{backup_file}.zip"
            
            if db.exportar_backup(backup_file):
                with zipfile.ZipFile(zip_file, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    zipf.write(backup_file, os.path.basename(backup_file))
                
                with open(zip_file, 'rb') as f:
                    await cliente.send_document(
                        chat_id=user_id,
                        document=f,
                        caption=f"📤 **Backup Exportado**\n🗓️ **Fecha:** {timestamp}"
                    )
                
                os.remove(backup_file)
                os.remove(zip_file)
                
                await callback_query.answer("✅ Backup exportado", show_alert=True)
            else:
                await callback_query.answer("❌ Error exportando", show_alert=True)
                
        except Exception as e:
            await callback_query.answer(f"❌ Error: {str(e)[:50]}", show_alert=True)
    
    elif data == "import_db":
        await callback_query.answer(
            "📥 **Para importar un backup:**\n\n"
            "1. 📎 Envía el archivo .db o .zip\n"
            "2. 🔄 Responde al archivo con /restore_db\n\n"
            "⚠️ **Advertencia:** Esto sobrescribirá la base de datos actual",
            show_alert=True
        )
    
    elif data == "db_stats":
        try:
            conn = sqlite3.connect("bot_database.db")
            cursor = conn.cursor()
            
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tablas = cursor.fetchall()
            
            stats_text = "📊 **Estadísticas de la Base de Datos**\n\n"
            
            for tabla in tablas:
                tabla_nombre = tabla[0]
                cursor.execute(f"SELECT COUNT(*) FROM {tabla_nombre}")
                cantidad = cursor.fetchone()[0]
                
                cursor.execute(f"PRAGMA table_info({tabla_nombre})")
                columnas = len(cursor.fetchall())
                
                stats_text += f"📋 **{tabla_nombre}**\n"
                stats_text += f"   📈 **Registros:** `{cantidad}`\n"
                stats_text += f"   🏗️ **Columnas:** `{columnas}`\n\n"
            
            conn.close()
            
            tamano_db = os.path.getsize("bot_database.db")
            
            stats_text += f"💾 **Tamaño total:** `{formatear_tamano(tamano_db)}`"
            
            await callback_query.message.edit_text(stats_text)
            
        except Exception as e:
            await callback_query.answer(f"❌ Error: {str(e)[:50]}", show_alert=True)

@app.on_message(filters.command("restore_db"))
@solo_administrador
async def comando_restore_db(cliente: Client, mensaje: Message):
    
    if not mensaje.reply_to_message or not mensaje.reply_to_message.document:
        await mensaje.reply_text(
            "📥 **Restaurar Backup de Base de Datos**\n\n"
            "📋 **Procedimiento:**\n"
            "1. 📎 Envía el archivo .db o .zip\n"
            "2. 🔄 Responde al archivo con /restore_db\n\n"
            "⚠️ **Advertencia importante:**\n"
            "Esta acción sobrescribirá la base de datos actual.\n"
            "Se creará un backup automático antes de restaurar."
        )
        return
    
    try:
        archivo = await mensaje.reply_to_message.download()
        
        if archivo.endswith('.zip'):
            with zipfile.ZipFile(archivo, 'r') as zipf:
                db_files = [f for f in zipf.namelist() if f.endswith('.db')]
                if not db_files:
                    await mensaje.reply_text("❌ No se encontró archivo .db en el ZIP")
                    return
                
                zipf.extract(db_files[0], '.')
                archivo_db = db_files[0]
        elif archivo.endswith('.db'):
            archivo_db = archivo
        else:
            await mensaje.reply_text("❌ Formato no válido. Usa .db o .zip")
            return
        
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_actual = f"backup_pre_restore_{timestamp}.db"
        shutil.copy2("bot_database.db", backup_actual)
        
        shutil.copy2(archivo_db, "bot_database.db")
        
        global db
        db = DatabaseManager()
        db.cargar_configuracion_desde_db()
        
        if os.path.exists(archivo):
            os.remove(archivo)
        if archivo.endswith('.zip') and os.path.exists(archivo_db):
            os.remove(archivo_db)
        
        await mensaje.reply_text(
            "✅ **Base de Datos Restaurada Correctamente**\n\n"
            f"🗄️ **Backup anterior guardado como:** `{backup_actual}`\n"
            "🔄 **Sistema recargado**\n"
            "🎯 **Configuración actualizada**\n\n"
            "✨ **La base de datos ha sido restaurada exitosamente.**"
        )
        
    except Exception as e:
        await mensaje.reply_text(f"❌ **Error Restaurando Backup**\n\n📝 **Detalles:** `{str(e)[:100]}`")

@app.on_message(filters.command("max"))
@solo_administrador
async def comando_max(cliente: Client, mensaje: Message):
    texto = mensaje.text.split()
    
    if len(texto) != 2:
        await mensaje.reply_text(
            f"📏 **Gestión de Límites**\n\n"
            f"⚖️ **Límite actual:** `{Config.MAX_FILE_SIZE_MB} MB`\n\n"
            "🔄 **Para modificar el límite:**\n"
            "`/max <nuevo_límite_en_MB>`\n\n"
            "💡 **Ejemplos:**\n"
            "• `/max 500` - 500 MB\n"
            "• `/max 100` - 100 MB\n"
            "• `/max 2000` - 2 GB\n\n"
            "⚠️ **Límites permitidos:**\n"
            "• 📏 **Mínimo:** 10 MB\n"
            "• 📏 **Máximo:** 5000 MB\n\n"
            "👑 **Nota:** Los administradores no tienen límite de tamaño."
        )
        return
    
    try:
        nuevo_limite = int(texto[1])
        
        if nuevo_limite < 10:
            await mensaje.reply_text("❌ **Error:** El mínimo permitido es 10 MB")
            return
            
        if nuevo_limite > 5000:
            await mensaje.reply_text("❌ **Error:** El máximo permitido es 5000 MB")
            return
        
        if db.actualizar_configuracion('limite_peso_mb', str(nuevo_limite)):
            Config.MAX_FILE_SIZE_MB = nuevo_limite
            await mensaje.reply_text(
                f"✅ **Límite Actualizado Exitosamente**\n\n"
                f"📊 **Cambios realizados:**\n"
                f"• 📏 **Límite anterior:** `{Config.MAX_FILE_SIZE_MB} MB`\n"
                f"• 📏 **Nuevo límite:** `{nuevo_limite} MB`\n\n"
                f"👥 **Alcance:** Todos los usuarios\n"
                f"⚡ **Estado:** Aplicado inmediatamente\n"
                f"💾 **Persistencia:** Guardado en base de datos"
            )
        else:
            await mensaje.reply_text("❌ **Error:** No se pudo actualizar el límite en la base de datos")
        
    except ValueError:
        await mensaje.reply_text(
            "❌ **Error de Formato**\n\n"
            "📝 El límite debe ser un número entero.\n\n"
            "💡 **Ejemplo correcto:**\n"
            "`/max 500`\n\n"
            "🔢 Solo se permiten números sin decimales."
        )

@app.on_message(filters.command("addadmin"))
@solo_administrador
async def comando_addadmin(cliente: Client, mensaje: Message):
    texto = mensaje.text.split()
    
    if len(texto) != 2:
        await mensaje.reply_text(
            "👑 **Agregar Administrador**\n\n"
            "📝 **Uso:**\n"
            "`/addadmin <user_id>`\n\n"
            "💡 **Ejemplo:**\n"
            "`/addadmin 123456789`\n\n"
            "📋 **Administradores actuales:**\n"
            f"• 👑 **Desde configuración:** {len(Config.ADMINISTRADORES)}\n"
            f"• 📊 **Desde base de datos:** {len(db.obtener_administradores())}"
        )
        return
    
    try:
        nuevo_admin_id = int(texto[1])
        agregado_por = mensaje.from_user.id
        username = mensaje.from_user.username or "N/A"
        
        if db.es_administrador(nuevo_admin_id):
            await mensaje.reply_text("❌ **Este usuario ya es administrador.**")
            return
        
        if db.agregar_administrador(nuevo_admin_id, username, agregado_por):
            await mensaje.reply_text(
                f"✅ **Administrador Agregado**\n\n"
                f"👤 **ID del usuario:** `{nuevo_admin_id}`\n"
                f"📛 **Username:** @{username}\n"
                f"👑 **Agregado por:** `{agregado_por}`\n\n"
                f"🔓 **Permisos otorgados:**\n"
                f"• 👑 Comandos de administrador\n"
                f"• 👥 Gestión de usuarios\n"
                f"• ⚙️ Configuración del bot\n"
                f"• ⭐ Prioridad en colas\n"
                f"• 📏 Sin límite de tamaño de archivos"
            )
        else:
            await mensaje.reply_text("❌ **Error al agregar el administrador.**")
            
    except ValueError:
        await mensaje.reply_text("❌ **Error:** El ID debe ser un número entero.")
    except Exception as e:
        await mensaje.reply_text(f"❌ **Error:** `{str(e)[:100]}`")

@app.on_message(filters.command("deladmin"))
@solo_administrador
async def comando_deladmin(cliente: Client, mensaje: Message):
    texto = mensaje.text.split()
    
    if len(texto) != 2:
        admins = db.obtener_administradores()
        
        if not admins:
            await mensaje.reply_text("📭 **No hay administradores adicionales en la base de datos.**")
            return
        
        lista_admins = "📋 **Lista de Administradores**\n\n"
        for i, admin in enumerate(admins, 1):
            lista_admins += (
                f"{i}. 👤 **ID:** `{admin['user_id']}`\n"
                f"   📛 **Username:** @{admin['username'] or 'N/A'}\n"
                f"   📅 **Agregado:** {admin['fecha_agregado'][:16]}\n\n"
            )
        
        lista_admins += "🗑️ **Para eliminar un administrador:**\n`/deladmin <user_id>`"
        
        await mensaje.reply_text(lista_admins)
        return
    
    try:
        admin_id = int(texto[1])
        eliminado_por = mensaje.from_user.id
        
        admins = db.obtener_administradores()
        if admin_id == eliminado_por and len(admins) <= 1 and eliminado_por not in Config.ADMINISTRADORES:
            await mensaje.reply_text("❌ **No puedes eliminarte a ti mismo si eres el único administrador.**")
            return
        
        if db.eliminar_administrador(admin_id):
            await mensaje.reply_text(
                f"✅ **Administrador Eliminado**\n\n"
                f"👤 **ID del usuario:** `{admin_id}`\n"
                f"👑 **Eliminado por:** `{eliminado_por}`\n\n"
                f"🔒 **Permisos revocados:**\n"
                f"• 👑 Comandos de administrador\n"
                f"• 👥 Gestión de usuarios\n"
                f"• ⚙️ Configuración del bot\n"
                f"• ⭐ Prioridad en colas\n"
                f"• 📏 Sin límite de tamaño de archivos"
            )
        else:
            await mensaje.reply_text("❌ **Administrador no encontrado.**")
            
    except ValueError:
        await mensaje.reply_text("❌ **Error:** El ID debe ser un número entero.")
    except Exception as e:
        await mensaje.reply_text(f"❌ **Error:** `{str(e)[:100]}`")

@app.on_message(filters.command("ban"))
@solo_administrador
async def comando_ban(cliente: Client, mensaje: Message):
    texto = mensaje.text.split()
    
    if len(texto) < 2:
        baneados = db.obtener_usuarios_baneados()
        
        if not baneados:
            await mensaje.reply_text("📭 **No hay usuarios baneados actualmente.**")
            return
        
        lista_baneados = "🚫 **Usuarios Baneados**\n\n"
        for i, usuario in enumerate(baneados, 1):
            lista_baneados += (
                f"{i}. 👤 **ID:** `{usuario['user_id']}`\n"
                f"   🏷️ **Nombre:** {usuario['first_name'] or usuario['username'] or 'N/A'}\n"
                f"   📅 **Fecha:** {usuario['fecha_baneo'][:16]}\n"
                f"   📝 **Razón:** {usuario['razon_baneo'] or 'No especificada'}\n\n"
            )
        
        lista_baneados += "🚫 **Para banear un usuario:**\n`/ban <user_id> [razón]`"
        
        await mensaje.reply_text(lista_baneados)
        return
    
    try:
        user_id = int(texto[1])
        razon = " ".join(texto[2:]) if len(texto) > 2 else "Sin razón especificada"
        baneado_por = mensaje.from_user.id
        
        if db.es_administrador(user_id):
            await mensaje.reply_text("❌ **No puedes banear a un administrador.**")
            return
        
        baneado, _ = db.usuario_baneado(user_id)
        if baneado:
            await mensaje.reply_text("❌ **Este usuario ya está baneado.**")
            return
        
        if db.banear_usuario(user_id, razon, baneado_por):
            await mensaje.reply_text(
                f"✅ **Usuario Baneado**\n\n"
                f"👤 **ID del usuario:** `{user_id}`\n"
                f"📝 **Razón:** {razon}\n"
                f"👑 **Baneado por:** `{baneado_por}`\n\n"
                f"🚫 **Consecuencias:**\n"
                f"• ❌ El usuario no podrá usar el bot\n"
                f"• 📤 No podrá enviar videos\n"
                f"• 📝 No podrá usar comandos"
            )
        else:
            await mensaje.reply_text("❌ **Error al banear al usuario.**")
            
    except ValueError:
        await mensaje.reply_text("❌ **Error:** El ID debe ser un número entero.")
    except Exception as e:
        await mensaje.reply_text(f"❌ **Error:** `{str(e)[:100]}`")

@app.on_message(filters.command("unban"))
@solo_administrador
async def comando_unban(cliente: Client, mensaje: Message):
    texto = mensaje.text.split()
    
    if len(texto) != 2:
        await mensaje.reply_text(
            "🔄 **Desbanear Usuario**\n\n"
            "📝 **Uso:**\n"
            "`/unban <user_id>`\n\n"
            "💡 **Ejemplo:**\n"
            "`/unban 123456789`\n\n"
            "📋 **Para ver la lista de baneados:**\n"
            "Usa el comando `/ban` sin argumentos."
        )
        return
    
    try:
        user_id = int(texto[1])
        
        if db.desbanear_usuario(user_id):
            await mensaje.reply_text(
                f"✅ **Usuario Desbaneado**\n\n"
                f"👤 **ID del usuario:** `{user_id}`\n\n"
                f"🔄 **Consecuencias:**\n"
                f"• ✅ El usuario puede volver a usar el bot\n"
                f"• 📤 Puede enviar videos nuevamente\n"
                f"• 📝 Puede usar todos los comandos"
            )
        else:
            await mensaje.reply_text("❌ **Usuario no encontrado o no estaba baneado.**")
            
    except ValueError:
        await mensaje.reply_text("❌ **Error:** El ID debe ser un número entero.")
    except Exception as e:
        await mensaje.reply_text(f"❌ **Error:** `{str(e)[:100]}`")

@app.on_message(filters.command("soporte"))
@solo_administrador
async def comando_soporte(cliente: Client, mensaje: Message):
    texto = mensaje.text.split()
    
    estado_actual = "🟢 Desactivado" if not Config.MODO_SOPORTE else "🔴 Activado"
    
    if len(texto) != 2:
        await mensaje.reply_text(
            f"🔧 **Modo Soporte**\n\n"
            f"📊 **Estado actual:** {estado_actual}\n\n"
            "🔄 **Para cambiar el estado:**\n"
            "• `/soporte on` - Activar modo soporte\n"
            "• `/soporte off` - Desactivar modo soporte\n\n"
            "⚡ **Efectos del modo soporte:**\n"
            "• 👑 Solo los administradores pueden usar el bot\n"
            "• 👤 Los usuarios ven un mensaje de mantenimiento\n"
            "• 🛠️ Útil para mantenimiento o actualizaciones"
        )
        return
    
    comando = texto[1].lower()
    
    if comando not in ['on', 'off']:
        await mensaje.reply_text("❌ **Error:** Usa `/soporte on` o `/soporte off`")
        return
    
    nuevo_estado = comando == 'on'
    
    if db.actualizar_configuracion('modo_soporte', str(nuevo_estado).lower()):
        Config.MODO_SOPORTE = nuevo_estado
        
        if nuevo_estado:
            await mensaje.reply_text(
                "🔧 **Modo Soporte Activado**\n\n"
                "📊 **Estado:** 🔴 Activado\n"
                "👥 **Impacto:** Solo administradores\n"
                "👤 **Usuarios ven:** Mensaje de mantenimiento\n\n"
                "⚠️ **El bot está ahora en modo mantenimiento.**"
            )
        else:
            await mensaje.reply_text(
                "🔧 **Modo Soporte Desactivado**\n\n"
                "📊 **Estado:** 🟢 Desactivado\n"
                "👥 **Impacto:** Todos los usuarios\n"
                "⚡ **Funcionamiento:** Normal\n\n"
                "✅ **El bot está ahora operativo para todos.**"
            )
    else:
        await mensaje.reply_text("❌ **Error al actualizar el modo soporte.**")

def inicializar_sistema():
    try:
        Config.validar_configuracion()
    except ValueError as e:
        logger.error(f"❌ Error de configuración: {e}")
        raise
    
    db.cargar_configuracion_desde_db()
    
    os.makedirs(Config.TEMP_DIR, exist_ok=True)
    
    logger.info("🎬 Bot de Conversión de Videos - INICIADO")
    logger.info(f"👑 Administradores: {len(Config.ADMINISTRADORES)}")
    logger.info(f"📏 Límite: {Config.MAX_FILE_SIZE_MB}MB")
    logger.info(f"⚡ Procesos: {Config.MAX_CONCURRENT_PROCESSES}")
    logger.info(f"🎨 Calidad: {Config.DEFAULT_QUALITY['resolution']}")
    logger.info(f"🔧 Modo Soporte: {Config.MODO_SOPORTE}")
    logger.info("🗄️ Base de datos inicializada")
    logger.info("🟢 Sistema operativo")

if __name__ == "__main__":
    inicializar_sistema()
    app.run()
