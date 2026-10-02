# Sync SISMED 2.0 - Supabase

> **Retirado el 2026-10-02.** La herramienta Sync SISMED 2.0 (envío de stock a Supabase) se eliminó del Toolkit de escritorio (`sync_sismed2_tool.py` y `sismed_sync_supabase.py`). Este documento se conserva solo como referencia histórica. El Sync SISMED vigente es el de Google Sheets (`sismed_sync.py`).

## Objetivo

Sync SISMED 2.0 envia el stock detallado del SISMED Desktop directamente a una API/Edge Function que escribe en Supabase.

El modulo mantiene las mismas validaciones del Sync SISMED clasico:

- valida directorio SISMED y carpeta `DATOS`
- valida archivos obligatorios `MMEDICAM.DBF` y `MSTKALMDE.DBF`
- lee catalogos DBF desde snapshot temporal para evitar bloqueos
- registra calidad DBF y aborta si hay demasiados registros corruptos
- soporta modo consolidado y modo detallado
- valida DNS/conectividad antes de enviar
- reintenta fallos DNS/conexion cada 20 segundos hasta 6 intentos
- conserva `fecha_equipo` y `actualizado` para compatibilidad

## Flujo Recomendado

```text
Toolkit Desktop -> Edge Function/API segura -> Supabase -> ToolkitSISMED Web
```

No se debe guardar `service_role` ni claves secretas de Supabase en el instalador Desktop.
El Desktop solo debe guardar una `clave de instalacion`.

## Request Del Desktop

`POST <SYNC2_ENDPOINT_URL>`

Headers:

```http
Content-Type: application/json
Authorization: Bearer <installation_token>
x-installation-token: <installation_token>
X-Toolkit-Version: 1.0.x
```

Body:

```json
{
  "source": "toolkit-sismed-desktop",
  "schema_version": "sismed-stock-v1",
  "toolkit_version": "1.0.x",
  "sent_at_host": "18/06/2026 09:30:00",
  "sent_at_epoch": 1780000000,
  "mode": "detallado",
  "record_count": 413,
  "fecha_equipo": "18/06/2026 09:30:00",
  "records": [
    {
      "almcod": "06502F01",
      "desc_alm": "FARM - C.S. EJEMPLO",
      "medcod": "00143",
      "codigo_sig": "582400320003",
      "xnom": "ACICLOVIR - 200 mg - TABLET -",
      "lote": "20203344",
      "fecha": "29/02/2028",
      "medregsan": "EN04199",
      "tipsum": "CN",
      "tipsum_des": "SISMED-COMPRA NACIONAL (CN)",
      "ffinan": "DYT",
      "ffinan_des": "Donaciones y Transferencias (DYT)",
      "saldo": 172,
      "precio_det": 0.133875,
      "preciocab": 0.14875,
      "fecha_equipo": "18/06/2026 09:30:00",
      "actualizado": "18/06/2026 09:30:00"
    }
  ]
}
```

## Response Esperada

El Desktop considera exitoso:

- HTTP `200` o `201`
- respuesta texto que empieza con `OK`
- o JSON con `success: true` u `ok: true`

Respuesta recomendada:

```json
{
  "success": true,
  "sync_run_id": "uuid",
  "records": 413
}
```

## Tablas Recomendadas

`facility_warehouses`

- `id uuid primary key`
- `facility_code text references facilities(code)`
- `almcod text unique not null`
- `name text`
- `is_active boolean default true`

`sync_installations`

- `id uuid primary key`
- `token_hash text unique not null`
- `facility_code text references facilities(code)`
- `allowed_almcods text[]`
- `pc_name text`
- `sismed_path text`
- `toolkit_version text`
- `is_active boolean default true`
- `last_seen_at timestamptz`

`sync_runs`

- `id uuid primary key`
- `installation_id uuid references sync_installations(id)`
- `facility_code text`
- `mode text`
- `record_count integer`
- `fecha_equipo text`
- `started_at timestamptz default now()`
- `finished_at timestamptz`
- `status text`
- `error_message text`

`stock_actual`

- `facility_code text not null`
- `almcod text not null`
- `desc_alm text`
- `medcod text not null`
- `codigo_sig text`
- `xnom text`
- `lote text not null`
- `fecha text`
- `medregsan text`
- `tipsum text`
- `tipsum_des text`
- `ffinan text`
- `ffinan_des text`
- `saldo numeric`
- `precio_det numeric`
- `preciocab numeric`
- `fecha_equipo text`
- `ultima_actualizacion timestamptz default now()`

Clave unica sugerida para reemplazo:

```sql
(facility_code, almcod, medcod, lote, fecha, ffinan, tipsum)
```

## Reemplazo De Stock

La Edge Function debe reemplazar el stock actual por establecimiento/almacen:

1. validar token de instalacion
2. validar que la instalacion este activa
3. extraer `facility_code` desde `almcod.substring(0, 5)` o desde la instalacion
4. validar `allowed_almcods`
5. borrar `stock_actual` de los `almcod` enviados
6. insertar los registros nuevos
7. crear/actualizar `sync_runs`
8. devolver `{ success: true, records, sync_run_id }`
