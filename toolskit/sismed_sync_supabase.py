import json
import time

import requests

from sismed_sync import SismedSyncManager, _read_toolkit_version


class SismedSyncSupabaseManager(SismedSyncManager):
    """Sync SISMED 2.0: envia el mismo payload de stock a una API/Edge Function."""

    def __init__(self, log_callback=None, on_stop_callback=None):
        super().__init__(log_callback=log_callback, on_stop_callback=on_stop_callback)
        self.backup_connection_supported = False
        self.destination_name = "Supabase"
        self.destination_label = "Supabase"
        self.modo_consolidado = False
        self.supabase_endpoint_url = ""
        self.installation_token = ""
        self.expected_facility_code = ""

    def _dedupe_records_for_supabase(self, payload_data: list[dict]) -> list[dict]:
        deduped: dict[tuple, dict] = {}
        for item in payload_data:
            key = (
                item.get("almcod", ""),
                item.get("medcod", ""),
                item.get("lote", ""),
                item.get("fecha", ""),
                item.get("ffinan", ""),
                item.get("tipsum", ""),
            )
            if key not in deduped:
                deduped[key] = item.copy()
                continue

            current = deduped[key]
            current["saldo"] = float(current.get("saldo") or 0) + float(item.get("saldo") or 0)
            current["precio_det"] = max(float(current.get("precio_det") or 0), float(item.get("precio_det") or 0))
            current["preciocab"] = max(float(current.get("preciocab") or 0), float(item.get("preciocab") or 0))
            for text_field in ("desc_alm", "codigo_sig", "xnom", "medregsan", "tipsum_des", "ffinan_des"):
                if not current.get(text_field) and item.get(text_field):
                    current[text_field] = item.get(text_field)
        return list(deduped.values())

    def _integration_url(self) -> str:
        return (self.supabase_endpoint_url or "").strip()

    def _validate_payload_before_send(self, payload_data: list[dict]) -> tuple[bool, str]:
        expected = self._normalize_code(self.expected_facility_code)
        if not expected:
            return False, (
                "Sync SISMED 2.0 bloqueado: falta configurar el Código IPRESS autorizado "
                "para validar que la ruta SISMED corresponda a esta instalación."
            )

        invalid: dict[str, int] = {}
        detected_facilities: set[str] = set()
        almcods_to_validate = set(self._last_reported_almcods)
        almcods_to_validate.update(
            self._normalize_code(str(item.get("almcod", "")))
            for item in payload_data
            if str(item.get("almcod", "")).strip()
        )

        for almcod in sorted(almcods_to_validate):
            facility = self._facility_from_almcod(almcod)
            detected_facilities.add(facility)
            if facility != expected:
                invalid[almcod] = invalid.get(almcod, 0) + 1

        if invalid:
            examples = ", ".join(f"{code}({count})" for code, count in sorted(invalid.items())[:5])
            extra = f" y {len(invalid) - 5} más" if len(invalid) > 5 else ""
            detected = ", ".join(sorted(detected_facilities)) or "(sin detectar)"
            return False, (
                "Sync SISMED 2.0 bloqueado por posible ruta SISMED incorrecta. "
                f"IPRESS autorizada: {expected}. IPRESS detectadas en ALMCOD: {detected}. "
                f"ALMCOD no permitidos: {examples}{extra}. "
                "Revise la ruta SISMED seleccionada o la clave de instalación."
            )

        self.log(f"  ✓ Validación IPRESS correcta: {expected}")
        return True, ""

    def _request_params(self) -> dict:
        # La clave y el equipo son del script de Google Sheets. Sync SISMED 2.0 se autentica
        # con su token de instalación y no debe mandar la clave a otro servicio.
        params = super()._request_params()
        for key in ("clave", "equipo", "equipo_id"):
            params.pop(key, None)
        return params

    def _send_key_blocks(self, response) -> list[tuple[str, str]]:
        return []

    def _apply_send_key_check(self, payload_data):
        # Sync SISMED 2.0 se autentica con su token de instalación; la clave es solo de Google.
        return payload_data, []

    def _request_headers(self) -> dict:
        headers = {
            "Content-Type": "application/json",
            "X-Toolkit-Version": _read_toolkit_version(),
        }
        token = (self.installation_token or "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
            headers["x-installation-token"] = token
        return headers

    def _request_body(self, payload_data: list[dict]) -> str:
        payload_data = self._dedupe_records_for_supabase(payload_data)
        fecha_equipo = self._host_timestamp()
        return json.dumps({
            "source": "toolkit-sismed-desktop",
            "schema_version": "sismed-stock-v1",
            "toolkit_version": _read_toolkit_version(),
            "sent_at_host": fecha_equipo,
            "sent_at_epoch": int(time.time()),
            "mode": "consolidado" if self.modo_consolidado else "detallado",
            "omit_zero_stock": bool(self.omitir_stock_cero),
            "source_record_count": self._last_source_record_count,
            "zero_stock_omitted": self._last_zero_stock_omitted,
            "reported_almcods": self._last_reported_almcods,
            "reported_facility_codes": self._last_reported_facility_codes,
            "record_count": len(payload_data),
            "fecha_equipo": fecha_equipo,
            "sismed_path": (self.base_dir or "").strip(),
            "records": payload_data,
        }, ensure_ascii=False)

    def _is_success_response(self, response: requests.Response) -> bool:
        if response.status_code not in (200, 201):
            return False
        text = (response.text or "").strip()
        if text.startswith("OK"):
            return True
        try:
            data = response.json()
        except ValueError:
            return False
        return bool(data.get("success") or data.get("ok"))

    def _success_message(self, response: requests.Response, record_count: int) -> str:
        try:
            data = response.json()
        except ValueError:
            data = {}

        received = data.get("records") or data.get("record_count") or data.get("upserted") or record_count
        run_id = data.get("sync_run_id") or data.get("run_id") or ""
        suffix = f"; run={run_id}" if run_id else ""
        return f"Stock detallado sincronizado con Supabase (OK:{received} registros{suffix})."
