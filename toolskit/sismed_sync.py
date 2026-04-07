import requests
import json
import time
import os
import sys
import threading
import tempfile
import traceback

from dbf_utils import DbfReadMetrics, iter_dbf_records, open_dbf, snapshot_dbf
from tools.app_config import set_many, update_runtime_status

SYNC_DBF_ABORT_MIN_BAD_RECORDS = 15
SYNC_DBF_ABORT_BAD_RATIO = 0.05

class SismedSyncManager:
    def __init__(self, log_callback=None, on_stop_callback=None):
        self.is_running = False
        self.log_callback = log_callback
        self.on_stop_callback = on_stop_callback
        self.thread = None
        self._state_lock = threading.RLock()
        self._stop_event = threading.Event()
        self.run_state = "idle"
        self.last_cycle_status = "never-run"
        self.last_cycle_message = ""
        self.last_cycle_error_kind = ""
        self.last_http_status = ""
        
        # Configuraciones por defecto
        self.apps_script_url = "https://script.google.com/macros/s/AKfycbyAtEQj5huUcEsXHLiMIe2-wzwFtlvYckIAabQQr2Z_g6Aa3o_93DaXaLgmfeYZm5pqCw/exec"
        self.base_dir = r"C:\SISMEDV2"
        self.modo_consolidado = True
        self.intervalo_minutos = 5

    def _set_run_state(self, state: str, detail: str = ""):
        with self._state_lock:
            self.run_state = state
            self.is_running = state in {"starting", "running", "stopping"}

        set_many({
            "runtime_sync_run_state": state,
            "runtime_sync_run_state_detail": detail,
            "runtime_sync_run_state_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        })

    def _record_cycle_result(
        self,
        status: str,
        message: str,
        *,
        error_kind: str = "",
        http_status: int | str | None = None,
        records: int = 0,
        success: bool = False,
    ):
        self.last_cycle_status = status
        self.last_cycle_message = message
        self.last_cycle_error_kind = error_kind or ""
        self.last_http_status = "" if http_status in (None, "") else str(http_status)

        update_runtime_status("sync_cycle", status, message)

        updates = {
            "runtime_last_sync_cycle_records": max(0, int(records or 0)),
            "runtime_last_sync_error_kind": self.last_cycle_error_kind,
            "runtime_last_sync_http_status": self.last_http_status,
        }

        if success:
            updates["runtime_last_sync_success_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            updates["runtime_last_sync_success_records"] = max(0, int(records or 0))

        set_many(updates)

    def _classify_request_exception(self, req_err: requests.exceptions.RequestException) -> tuple[str, str]:
        if isinstance(req_err, requests.exceptions.SSLError):
            return (
                "tls-error",
                "Error TLS/SSL al enviar datos a Google. Revisa certificados del sistema, fecha/hora del equipo o inspeccion HTTPS.",
            )

        if isinstance(req_err, requests.exceptions.ProxyError):
            return (
                "proxy-error",
                "Error de proxy al enviar datos a Google. Revisa la configuracion de red del equipo.",
            )

        if isinstance(req_err, (requests.exceptions.ConnectTimeout, requests.exceptions.ReadTimeout, requests.exceptions.Timeout)):
            return (
                "timeout",
                "La conexion a Google excedio el tiempo de espera. Revisa conectividad o saturacion de red.",
            )

        if isinstance(req_err, requests.exceptions.ConnectionError):
            detail = str(req_err).lower()
            dns_markers = (
                "nameresolutionerror",
                "temporary failure in name resolution",
                "failed to resolve",
                "getaddrinfo failed",
                "name or service not known",
                "no address associated",
                "nodename nor servname",
            )
            if any(marker in detail for marker in dns_markers):
                return (
                    "dns-error",
                    "No se pudo resolver el servidor de Google. Revisa DNS, proxy o conectividad.",
                )

            return (
                "connection-error",
                "No se pudo establecer conexion con Google. Revisa red, firewall o acceso a Internet.",
            )

        return (
            "request-error",
            f"Error de red al enviar datos a Google: {type(req_err).__name__}.",
        )

    def _persist_dbf_quality(self, metrics_list: list[DbfReadMetrics]):
        relevant_metrics = [
            metric for metric in metrics_list
            if metric.total_records or metric.field_fallbacks or metric.omitted_records
        ]

        if not relevant_metrics:
            set_many({
                "runtime_last_sync_dbf_source": "",
                "runtime_last_sync_dbf_problem_records": 0,
                "runtime_last_sync_dbf_problem_ratio": 0.0,
                "runtime_last_sync_dbf_corrupted_records": 0,
                "runtime_last_sync_dbf_omitted_records": 0,
                "runtime_last_sync_dbf_field_fallbacks": 0,
                "runtime_last_sync_dbf_summary": "",
            })
            return

        worst_metric = max(
            relevant_metrics,
            key=lambda metric: (
                metric.problem_records,
                metric.problem_ratio,
                metric.field_fallbacks,
                metric.total_records,
            ),
        )

        set_many({
            "runtime_last_sync_dbf_source": worst_metric.label,
            "runtime_last_sync_dbf_problem_records": worst_metric.problem_records,
            "runtime_last_sync_dbf_problem_ratio": round(worst_metric.problem_ratio, 6),
            "runtime_last_sync_dbf_corrupted_records": worst_metric.corrupted_records,
            "runtime_last_sync_dbf_omitted_records": worst_metric.omitted_records,
            "runtime_last_sync_dbf_field_fallbacks": worst_metric.field_fallbacks,
            "runtime_last_sync_dbf_summary": " | ".join(metric.summary() for metric in relevant_metrics),
        })

    def _log_dbf_metrics(self, metrics_list: list[DbfReadMetrics]):
        for metric in metrics_list:
            if metric.total_records or metric.field_fallbacks or metric.omitted_records:
                self.log(f"  ℹ Calidad DBF {metric.summary()}")

    def _should_abort_for_dbf_quality(self, metrics: DbfReadMetrics) -> bool:
        if metrics.total_records <= 0:
            return False
        if metrics.problem_records < SYNC_DBF_ABORT_MIN_BAD_RECORDS:
            return False
        return metrics.problem_ratio >= SYNC_DBF_ABORT_BAD_RATIO

    def _dbf_quality_abort_message(self, metrics: DbfReadMetrics) -> str:
        return (
            f"Se abortó la sincronización por calidad insuficiente en {metrics.label}: "
            f"{metrics.problem_records}/{metrics.total_records} registros problemáticos "
            f"({metrics.problem_ratio:.2%}). Umbral activo: al menos "
            f"{SYNC_DBF_ABORT_MIN_BAD_RECORDS} registros y {SYNC_DBF_ABORT_BAD_RATIO:.0%} del archivo."
        )

    def log(self, message):
        """Envía el mensaje a la interfaz si existe un callback, de lo contrario lo imprime."""
        if self.log_callback:
            self.log_callback(message)
        else:
            try:
                print(message)
            except UnicodeEncodeError:
                encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
                safe_message = str(message).encode(encoding, errors="replace").decode(encoding, errors="replace")
                print(safe_message)

    def start_sync(self):
        with self._state_lock:
            if self.run_state in {"starting", "running", "stopping"}:
                return False
            self._stop_event.clear()

        self._set_run_state("starting", "Inicializando hilo de sincronizacion")
        self.log("▶ Iniciando sincronizador SISMED SYNC...")
        self.log(f"  Modo Consolidado: {'ACTIVADO' if self.modo_consolidado else 'DESACTIVADO (Detallado)'}")
        self.log(f"  Intervalo: {self.intervalo_minutos} minutos")
        self.log("="*50)
        
        self.thread = threading.Thread(target=self._sync_loop, daemon=True)
        self.thread.start()
        return True

    def stop_sync(self):
        with self._state_lock:
            if self.run_state in {"idle", "stopping"}:
                return False
            self._stop_event.set()

        self._set_run_state("stopping", "Detencion solicitada por el usuario")
        self.log("⏹ Deteniendo sincronizador... (esto puede tardar unos segundos)")
        return True

    def _sync_loop(self):
        self._set_run_state("running", "Hilo de sincronizacion activo")
        try:
            while not self._stop_event.is_set():
                self.perform_sync()

                if self._stop_event.is_set():
                    break

                wait_seconds = max(1, int(self.intervalo_minutos)) * 60
                self.log(f"  Esperando {self.intervalo_minutos} minutos para la siguiente actualización...")
                if self._stop_event.wait(wait_seconds):
                    break
        finally:
            self._set_run_state("idle", "Hilo de sincronizacion detenido")
            self.log("❌ Sincronizador completamente detenido.")
            if self.on_stop_callback:
                self.on_stop_callback()

    def perform_sync(self):
        hora = time.strftime('%H:%M:%S')
        self.log(f"[{hora}] Leyendo stock detallado de SISMED...")
        self._persist_dbf_quality([])

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

            with tempfile.TemporaryDirectory(prefix="toolkit_sync_") as snapshot_dir:
                PATH_MEDICAM_READ = snapshot_dbf(PATH_MEDICAM, snapshot_dir)
                PATH_STOCK_DET_READ = snapshot_dbf(PATH_STOCK_DET, snapshot_dir)
                PATH_MALMACEN_READ = snapshot_dbf(PATH_MALMACEN, snapshot_dir)
                PATH_MTIPSUM_READ = snapshot_dbf(PATH_MTIPSUM, snapshot_dir)
                PATH_MFFINAN_READ = snapshot_dbf(PATH_MFFINAN, snapshot_dir)

                medicam_metrics = DbfReadMetrics("MMEDICAM.DBF")
                stock_metrics = DbfReadMetrics("MSTKALMDE.DBF")
                almacen_metrics = DbfReadMetrics("MALMACEN.DBF")
                tipsum_metrics = DbfReadMetrics("MTIPSUM.DBF")
                ffinan_metrics = DbfReadMetrics("MFFINAN.DBF")

                # 1. Cargar catálogo de MEDICAMENTOS
                cat_medicam = {}
                if os.path.exists(PATH_MEDICAM_READ):
                    for rec in iter_dbf_records(open_dbf(PATH_MEDICAM_READ, metrics=medicam_metrics), medicam_metrics):
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
                if os.path.exists(PATH_MALMACEN_READ):
                    for rec in iter_dbf_records(open_dbf(PATH_MALMACEN_READ, metrics=almacen_metrics), almacen_metrics):
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
                if os.path.exists(PATH_MTIPSUM_READ):
                    for rec in iter_dbf_records(open_dbf(PATH_MTIPSUM_READ, metrics=tipsum_metrics), tipsum_metrics):
                        if str(rec.get('CODSUM', '')).strip():
                            cat_tipsum[str(rec.get('CODSUM', '')).strip()] = str(rec.get('NOMSUM', '')).strip()

                cat_ffinan = {}
                if os.path.exists(PATH_MFFINAN_READ):
                    for rec in iter_dbf_records(open_dbf(PATH_MFFINAN_READ, metrics=ffinan_metrics), ffinan_metrics):
                        if str(rec.get('CODFF', '')).strip():
                            cat_ffinan[str(rec.get('CODFF', '')).strip()] = str(rec.get('DESFF', '')).strip()

                # 5. Leer STOCK DETALLADO
                payload_data = []
                registros_omitidos = 0
                
                def safe_float(val):
                    if val is None:
                        return 0.0
                    try:
                        clean_str = str(val).strip()
                        if not clean_str:
                            return 0.0
                        return float(clean_str)
                    except (ValueError, TypeError):
                        return 0.0


                if os.path.exists(PATH_STOCK_DET_READ):
                    for rec in iter_dbf_records(open_dbf(PATH_STOCK_DET_READ, metrics=stock_metrics), stock_metrics):
                        med_id_raw = str(rec.get('MEDCOD', '')).strip()
                        if not med_id_raw:
                            registros_omitidos += 1
                            stock_metrics.note_omission("missing-medcod")
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
                    message = f"No se encontró archivo de stock en: {PATH_STOCK_DET}"
                    self.log(f"  ❌ ERROR: {message}")
                    self._record_cycle_result(
                        "missing-stock-dbf",
                        message,
                        error_kind="missing-stock-dbf",
                    )
                    return

                self.log(f"  ✓ Registros leídos de MSTKALMDE: {len(payload_data)}")
                if registros_omitidos:
                    self.log(f"  ℹ Registros omitidos por claves incompletas: {registros_omitidos}")

                dbf_metrics = [
                    medicam_metrics,
                    almacen_metrics,
                    tipsum_metrics,
                    ffinan_metrics,
                    stock_metrics,
                ]
                self._log_dbf_metrics(dbf_metrics)
                self._persist_dbf_quality(dbf_metrics)

                for critical_metrics in (medicam_metrics, stock_metrics):
                    if self._should_abort_for_dbf_quality(critical_metrics):
                        message = self._dbf_quality_abort_message(critical_metrics)
                        self.log(f"[{time.strftime('%H:%M:%S')}] ⚠ {message}")
                        self._record_cycle_result(
                            "dbf-quality-abort",
                            message,
                            error_kind="dbf-quality-abort",
                            records=len(payload_data),
                        )
                        return

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
                            consolidado[group_key]["preciocab"] = max(consolidado[group_key]["preciocab"], item["preciocab"])

                    payload_data = list(consolidado.values())
                    self.log(f"  ✓ Stock consolidado: {len(payload_data)} lotes únicos.")
                else:
                    self.log(f"  ℹ Modo DETALLADO activo (farmacias por separado).")

                # 7. Enviar a Google Apps Script (Envío Unificado)
                if not payload_data:
                    message = "No hay stock para enviar. El archivo DBF analizado está vacío o sin precios."
                    self.log(f"[{time.strftime('%H:%M:%S')}] ⚠ {message}")
                    self._record_cycle_result(
                        "no-data",
                        message,
                        records=0,
                    )
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
                        success_message = f"Stock detallado sincronizado ({response.text.strip()})."
                        self.log(f"[{time.strftime('%H:%M:%S')}] ✓ ¡Éxito! {success_message}")
                        self._record_cycle_result(
                            "success",
                            f"{success_message} Registros={len(payload_data)}; omitidos={registros_omitidos}; problemas_dbf={stock_metrics.problem_records}",
                            http_status=response.status_code,
                            records=len(payload_data),
                            success=True,
                        )
                    else:
                        response_preview = response.text[:300].strip()
                        failure_message = f"HTTP {response.status_code} al sincronizar con Google."
                        self.log(f"  ✗ Fallo en la conexión a Google: HTTP {response.status_code}")
                        if response_preview:
                            self.log(f"  Respuesta del servidor: {response_preview}")
                        self._record_cycle_result(
                            "http-error",
                            f"{failure_message} {response_preview}".strip(),
                            error_kind="http-error",
                            http_status=response.status_code,
                            records=len(payload_data),
                        )
                        
                except requests.exceptions.RequestException as req_err:
                    error_kind, user_message = self._classify_request_exception(req_err)
                    technical_detail = f"{type(req_err).__name__}: {req_err}"
                    self.log(f"  ⚠️ {user_message}")
                    self.log(f"  Detalle técnico: {technical_detail}")
                    self._record_cycle_result(
                        error_kind,
                        f"{user_message} | {technical_detail}",
                        error_kind=error_kind,
                        records=len(payload_data),
                    )

        except (PermissionError, OSError) as os_err:
            if getattr(os_err, 'winerror', 0) in [32, 33] or isinstance(os_err, PermissionError):
                message = "El archivo está bloqueado por SISMED u otro proceso. Reintentando próximo ciclo."
                self.log(f"[{time.strftime('%H:%M:%S')}] ⚠ {message}")
                self._record_cycle_result(
                    "dbf-locked",
                    message,
                    error_kind="dbf-locked",
                )
            else:
                message = f"Error de I/O en disco: {str(os_err)}"
                self.log(f"[{time.strftime('%H:%M:%S')}] ✗ {message}")
                self._record_cycle_result(
                    "io-error",
                    message,
                    error_kind="io-error",
                )
        except Exception as e:
            message = f"Error crítico durante la sincronización: {str(e)}"
            self.log(f"[{time.strftime('%H:%M:%S')}] ✗ {message}")
            self.log(traceback.format_exc())
            self._record_cycle_result(
                "unexpected-error",
                message,
                error_kind=type(e).__name__,
            )
