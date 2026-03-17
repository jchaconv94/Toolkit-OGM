import requests
import json
from dbfread import DBF
import time
import os
import threading
import traceback
import math

class SismedSyncManager:
    def __init__(self, log_callback=None, on_stop_callback=None):
        self.is_running = False
        self.log_callback = log_callback
        self.on_stop_callback = on_stop_callback
        self.thread = None
        
        # Configuraciones por defecto
        self.apps_script_url = "https://script.google.com/macros/s/AKfycbyAtEQj5huUcEsXHLiMIe2-wzwFtlvYckIAabQQr2Z_g6Aa3o_93DaXaLgmfeYZm5pqCw/exec"
        self.base_dir = r"C:\SISMEDV2"
        self.modo_consolidado = True
        self.intervalo_minutos = 5

    def log(self, message):
        """Envía el mensaje a la interfaz si existe un callback, de lo contrario lo imprime."""
        if self.log_callback:
            self.log_callback(message)
        else:
            print(message)

    def start_sync(self):
        if self.is_running:
            return
        self.is_running = True
        self.log("▶ Iniciando sincronizador AURA SYNC...")
        self.log(f"  Modo Consolidado: {'ACTIVADO' if self.modo_consolidado else 'DESACTIVADO (Detallado)'}")
        self.log(f"  Intervalo: {self.intervalo_minutos} minutos")
        self.log("="*50)
        
        self.thread = threading.Thread(target=self._sync_loop, daemon=True)
        self.thread.start()

    def stop_sync(self):
        if not self.is_running:
            return
        self.is_running = False
        self.log("⏹ Deteniendo sincronizador... (esto puede tardar unos segundos)")

    def _sync_loop(self):
        while self.is_running:
            self.perform_sync()
            
            # Espera inteligente (revisa cada segundo si se detuvo el proceso)
            wait_seconds = self.intervalo_minutos * 60
            self.log(f"  Esperando {self.intervalo_minutos} minutos para la siguiente actualización...")
            for _ in range(wait_seconds):
                if not self.is_running:
                    break
                time.sleep(1)
                
        self.log("❌ Sincronizador completamente detenido.")
        if self.on_stop_callback:
            self.on_stop_callback()

    def perform_sync(self):
        hora = time.strftime('%H:%M:%S')
        self.log(f"[{hora}] Leyendo stock detallado de SISMED...")

        PATH_MEDICAM   = os.path.join(self.base_dir, "DATOS", "MMEDICAM.DBF")
        PATH_STOCK_DET = os.path.join(self.base_dir, "DATOS", "MSTKALMDE.DBF")
        PATH_MALMACEN  = os.path.join(self.base_dir, "DATOS", "MALMACEN.DBF")
        PATH_MTIPSUM   = os.path.join(self.base_dir, "DATOS", "MTIPSUM.DBF")
        PATH_MFFINAN   = os.path.join(self.base_dir, "DATOS", "MFFINAN.DBF")

        try:
            # --- Validaciones de archivos ---
            archivos_requeridos = {"Stock Detallado": PATH_STOCK_DET, "Catálogo": PATH_MEDICAM}
            for nombre, ruta in archivos_requeridos.items():
                if not os.path.exists(ruta):
                    self.log(f"  ⚠ ADVERTENCIA: No se encontró '{nombre}' en: {ruta}")

            # 1. Cargar catálogo de MEDICAMENTOS
            cat_medicam = {}
            if os.path.exists(PATH_MEDICAM):
                for rec in DBF(PATH_MEDICAM, ignore_missing_memofile=True, char_decode_errors='ignore'):
                    cod = str(rec.get('MEDCOD', '')).strip().zfill(5)
                    if cod:
                        nombre  = str(rec.get('MEDNOM', '')).strip()
                        conc    = str(rec.get('MEDCNC', '')).strip()
                        forma   = str(rec.get('MEDFF', '')).strip()
                        partes  = [p for p in [nombre, conc, forma] if p]
                        cat_medicam[cod] = {
                            "xnom": ' - '.join(partes) + (' -' if partes else ''),
                            "codigo_sig": str(rec.get('CODIGO_SIG', '')).strip(),
                        }
            self.log(f"  ✓ Medicamentos cargados: {len(cat_medicam)}")

            # 2. Cargar ALMACENES
            cat_almacen = {}
            if os.path.exists(PATH_MALMACEN):
                for rec in DBF(PATH_MALMACEN, ignore_missing_memofile=True, char_decode_errors='ignore'):
                    alm_cod = str(rec.get('ALMCOD', '')).strip()
                    if alm_cod:
                        cat_almacen[alm_cod] = str(rec.get('ALMDES', '')).strip()

            def buscar_establecimiento(alm_cod):
                if alm_cod in cat_almacen:
                    nombre = cat_almacen[alm_cod]
                    genericos = ['FAR SISMED', 'FAR DONACIONES', 'ALM SISMED', 'FARM SISMED']
                    if any(g in nombre.upper() for g in genericos):
                        for longitud in [8, 5]:
                            if len(alm_cod) > longitud:
                                prefijo = alm_cod[:longitud]
                                if prefijo in cat_almacen:
                                    return cat_almacen[prefijo]
                    return nombre
                for longitud in [8, 10, 5]:
                    if len(alm_cod) >= longitud:
                        prefijo = alm_cod[:longitud]
                        if prefijo in cat_almacen:
                            return cat_almacen[prefijo]
                for clave, desc in sorted(cat_almacen.items(), key=lambda x: len(x[0]), reverse=True):
                    if alm_cod.startswith(clave) and len(clave) >= 4:
                        return desc
                return ''

            # 3. Y 4. Cargar TIPSUM y FFINAN
            cat_tipsum = {}
            if os.path.exists(PATH_MTIPSUM):
                for rec in DBF(PATH_MTIPSUM, ignore_missing_memofile=True, char_decode_errors='ignore'):
                    if str(rec.get('CODSUM', '')).strip():
                        cat_tipsum[str(rec.get('CODSUM', '')).strip()] = str(rec.get('NOMSUM', '')).strip()

            cat_ffinan = {}
            if os.path.exists(PATH_MFFINAN):
                for rec in DBF(PATH_MFFINAN, ignore_missing_memofile=True, char_decode_errors='ignore'):
                    if str(rec.get('CODFF', '')).strip():
                        cat_ffinan[str(rec.get('CODFF', '')).strip()] = str(rec.get('DESFF', '')).strip()

            # 5. Leer STOCK DETALLADO
            payload_data = []
            registros_omitidos = 0
            
            def safe_float(val):
                if val is None: return 0.0
                try:
                    # Limpiamos los espacios en blanco que deja FoxPro
                    clean_str = str(val).strip()
                    if not clean_str: return 0.0
                    return float(clean_str)
                except (ValueError, TypeError):
                    return 0.0


            if os.path.exists(PATH_STOCK_DET):
                for rec in DBF(PATH_STOCK_DET, ignore_missing_memofile=True, char_decode_errors='ignore'):
                    med_id_raw = str(rec.get('MEDCOD', '')).strip()
                    if not med_id_raw:
                        registros_omitidos += 1
                        continue

                    med_id = med_id_raw.zfill(5)
                    alm_cod = str(rec.get('ALMCOD', '')).strip()
                    alm_des = buscar_establecimiento(alm_cod)

                    med_info = cat_medicam.get(med_id, {})
                    
                    fecha_vto_raw = rec.get('MEDFECHVTO')
                    if fecha_vto_raw and hasattr(fecha_vto_raw, 'strftime'):
                        fecha_vto = fecha_vto_raw.strftime('%d/%m/%Y')
                    elif fecha_vto_raw:
                        fecha_vto = str(fecha_vto_raw)
                    else:
                        fecha_vto = ""

                    payload_data.append({
                        "almcod":      alm_cod,
                        "desc_alm":    alm_des,
                        "medcod":      med_id,
                        "codigo_sig":  med_info.get("codigo_sig", ""),
                        "xnom":        med_info.get("xnom", "Sin Nombre"),
                        "lote":        str(rec.get('MEDLOTE', '')).strip(),
                        "fecha":       fecha_vto,
                        "medregsan":   str(rec.get('MEDREGSAN', '')).strip(),
                        "tipsum":      str(rec.get('TIPSUM', '')).strip(),
                        "tipsum_des":  cat_tipsum.get(str(rec.get('TIPSUM', '')).strip(), ""),
                        "ffinan":      str(rec.get('FFINAN', '')).strip(),
                        "ffinan_des":  cat_ffinan.get(str(rec.get('FFINAN', '')).strip(), ""),
                        "saldo":       safe_float(rec.get('STKSALDODE')),
                        "precio_det":  safe_float(rec.get('STKPRED')),
                        "preciocab":   safe_float(rec.get('STKPREO')),
                        "actualizado": time.strftime('%d/%m/%Y %H:%M:%S'),
                    })
            else:
                self.log(f"  ❌ ERROR: No se encontró archivo de stock en: {PATH_STOCK_DET}")
                return

            self.log(f"  ✓ Registros leídos de MSTKALMDE: {len(payload_data)}")

            # 6. Consolidación (Si está activado)
            if self.modo_consolidado:
                self.log(f"  Σ Consolidando stock de sub-almacenes...")
                consolidado = {}
                for item in payload_data:
                    alm_base = item["almcod"][:5]
                    group_key = (alm_base, item["medcod"], item["lote"], item["fecha"], item["ffinan"], item["tipsum"])
                    
                    if group_key not in consolidado:
                        consolidado[group_key] = item.copy()
                        nombre_base = buscar_establecimiento(alm_base)
                        consolidado[group_key]["almcod"] = alm_base + "F01"
                        consolidado[group_key]["desc_alm"] = f"{nombre_base} (CONSOLIDADO)"
                    else:
                        consolidado[group_key]["saldo"] += item["saldo"]
                        consolidado[group_key]["precio_det"] = max(consolidado[group_key]["precio_det"], item["precio_det"])
                        consolidado[group_key]["preciocab"]  = max(consolidado[group_key]["preciocab"], item["preciocab"])

                payload_data = list(consolidado.values())
                self.log(f"  ✓ Stock consolidado: {len(payload_data)} lotes únicos.")
            else:
                self.log(f"  ℹ Modo DETALLADO activo (farmacias por separado).")

            # 7. Enviar a Google Apps Script (Envío Unificado)
            if not payload_data:
                self.log(f"[{time.strftime('%H:%M:%S')}] ⚠ No hay stock para enviar. El archivo DBF analizado está vacío o sin precios.")
                return
                
            self.log(f"[{time.strftime('%H:%M:%S')}] Subiendo a la nube (Google Sheets)...")
            
            try:
                response = requests.post(
                    self.apps_script_url,
                    data=json.dumps(payload_data),
                    headers={'Content-Type': 'application/json'},
                    timeout=300
                )
                
                if response.status_code == 200 and response.text.startswith("OK"):
                    self.log(f"[{time.strftime('%H:%M:%S')}] ✓ ¡Éxito! Stock detallado sincronizado ({response.text.strip()}).")
                else:
                    self.log(f"  ✗ Fallo en la conexión a Google: HTTP {response.status_code}")
                    self.log(f"  Respuesta del servidor: {response.text[:300]}")
                    
            except requests.exceptions.RequestException as req_err:
                self.log(f"  ⚠️ Error de red o sin Internet al enviar datos: Verifica tu conexión.")

        except (PermissionError, OSError) as os_err:
            if getattr(os_err, 'winerror', 0) in [32, 33] or isinstance(os_err, PermissionError):
                self.log(f"[{time.strftime('%H:%M:%S')}] ⚠ El archivo está bloqueado por SISMED u otro proceso. Reintentando próximo ciclo.")
            else:
                self.log(f"[{time.strftime('%H:%M:%S')}] ✗ Error de I/O en Disco: {str(os_err)}")
        except Exception as e:
            self.log(f"[{time.strftime('%H:%M:%S')}] ✗ Error crítico durante la sincronización: {str(e)}")
            self.log(traceback.format_exc())
