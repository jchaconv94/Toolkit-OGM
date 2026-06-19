# Prompts Para Google AI Studio - ToolkitSISMED Web

Estos prompts son para darle contexto a otra IA sobre los cambios necesarios en la app web `jchaconv94/ToolkitSISMED`.

## Prompt 1 - Contexto General

```text
Estoy trabajando en una migracion gradual del sistema Toolkit SISMED.

Actualmente existe una app Desktop llamada Toolkit OGM/Toolkit SISMED que lee archivos DBF del SISMED local y envia stock a Google Sheets mediante Apps Script. La app web ToolkitSISMED consulta esas hojas mediante Apps Script para mostrar stock, filtrar, asignar establecimientos y procesar informacion.

Se esta creando un nuevo modulo Desktop llamado "Sync SISMED 2.0". Este modulo mantiene las mismas columnas y datos que el Sync SISMED actual, pero en vez de enviar a Google Sheets enviara directamente a una API/Edge Function que escribira en Supabase.

El objetivo NO es romper el flujo actual con Google Sheets. El objetivo es agregar soporte Supabase directo en paralelo, y luego adaptar la web para consultar Supabase cuando haya datos disponibles.

La jerarquia actual de la web es:
DIRESA -> OGESS -> UNGET -> Microred -> IPRESS/Establecimiento.

El codigo base de IPRESS es de 5 digitos, por ejemplo 06502. El ALMCOD de SISMED puede representar almacenes/farmacias internas, por ejemplo 06502F01, 06502F02. Por eso el stock debe manejar facility_code=06502 y almcod=06502F01 de forma separada.

Necesito que revises el proyecto web y propongas cambios compatibles, sin eliminar todavia los modulos actuales de Apps Script.
```

## Prompt 2 - Tablas Supabase

```text
Necesito agregar soporte Supabase directo para stock SISMED en la app web ToolkitSISMED.

Disena una migracion SQL compatible con el esquema actual que agregue estas tablas:

1. facility_warehouses
- id uuid primary key
- facility_code text references public.facilities(code)
- almcod text unique not null
- name text
- is_active boolean default true
- created_at timestamptz default now()

2. sync_installations
- id uuid primary key
- token_hash text unique not null
- facility_code text references public.facilities(code)
- allowed_almcods text[]
- pc_name text
- sismed_path text
- toolkit_version text
- is_active boolean default true
- last_seen_at timestamptz
- created_at timestamptz default now()

3. sync_runs
- id uuid primary key
- installation_id uuid references public.sync_installations(id)
- facility_code text
- mode text
- record_count integer
- fecha_equipo text
- started_at timestamptz default now()
- finished_at timestamptz
- status text
- error_message text

4. stock_actual
- id uuid primary key
- facility_code text not null references public.facilities(code)
- almcod text not null
- desc_alm text
- medcod text not null
- codigo_sig text
- xnom text
- lote text not null
- fecha text
- medregsan text
- tipsum text
- tipsum_des text
- ffinan text
- ffinan_des text
- saldo numeric
- precio_det numeric
- preciocab numeric
- fecha_equipo text
- ultima_actualizacion timestamptz default now()

Crear indice unico para reemplazo:
(facility_code, almcod, medcod, lote, fecha, ffinan, tipsum)

Crear indices utiles para consultas por facility_code, almcod, medcod, codigo_sig, xnom y ultima_actualizacion.

Importante:
- No borrar las tablas actuales.
- No eliminar Google Sheets ni facility_stock_assignments todavia.
- Mantener compatibilidad con la app actual.
- RLS debe quedar preparado para seguridad real; si el proyecto actualmente usa politicas temporales, indicar claramente cuales deben endurecerse.
```

## Prompt 3 - Edge Function/API De Recepcion

```text
Necesito crear una Edge Function/API segura en Supabase para recibir stock desde Toolkit Desktop "Sync SISMED 2.0".

El Desktop enviara:

POST <endpoint>
Headers:
Content-Type: application/json
Authorization: Bearer <installation_token>
X-Installation-Token: <installation_token>
X-Toolkit-Version: 1.0.x

Body:
{
  "source": "toolkit-sismed-desktop",
  "schema_version": "sismed-stock-v1",
  "toolkit_version": "1.0.x",
  "sent_at_host": "dd/MM/yyyy HH:mm:ss",
  "sent_at_epoch": 1780000000,
  "mode": "consolidado" | "detallado",
  "record_count": 413,
  "records": [
    {
      "almcod": "06502F01",
      "desc_alm": "...",
      "medcod": "00143",
      "codigo_sig": "...",
      "xnom": "...",
      "lote": "...",
      "fecha": "29/02/2028",
      "medregsan": "...",
      "tipsum": "CN",
      "tipsum_des": "...",
      "ffinan": "DYT",
      "ffinan_des": "...",
      "saldo": 172,
      "precio_det": 0.133875,
      "preciocab": 0.14875,
      "fecha_equipo": "dd/MM/yyyy HH:mm:ss",
      "actualizado": "dd/MM/yyyy HH:mm:ss"
    }
  ]
}

La funcion debe:
1. Leer el token desde Authorization Bearer o X-Installation-Token.
2. Hashear el token y buscarlo en sync_installations.token_hash.
3. Rechazar si la instalacion no existe o no esta activa.
4. Validar que los records sean array y que record_count coincida.
5. Extraer facility_code desde la instalacion o desde los primeros 5 caracteres de almcod.
6. Validar que cada almcod este permitido en allowed_almcods, si esa lista no esta vacia.
7. Crear un sync_run con status processing.
8. Reemplazar stock_actual solo para los almcod enviados por esa instalacion.
9. Insertar los registros nuevos con ultima_actualizacion = now() del servidor.
10. Actualizar sync_runs con status success y finished_at.
11. Actualizar sync_installations.last_seen_at y toolkit_version.
12. Devolver JSON: { "success": true, "sync_run_id": "...", "records": 413 }.

No exponer service_role en el frontend ni en el Desktop.
```

## Prompt 4 - Cambiar Consulta Stock A Supabase

```text
Necesito adaptar el modulo SheetSearchModule.tsx de ToolkitSISMED para que pueda leer stock desde Supabase directo cuando exista, manteniendo Apps Script como fallback temporal.

Actualmente SheetSearchModule.tsx obtiene URLs guardadas en unget_configs, hace fetch a Apps Script, procesa hojas y arma sources/data en memoria. Tambien registra historial en stock_sync_history.

Nuevo objetivo:
- Si existe stock en public.stock_actual para los establecimientos dentro de la jurisdiccion del usuario, cargar desde Supabase.
- Respetar la jerarquia actual de permisos:
  GLOBAL/ADMIN ve todo
  DIRESA ve facilities de su diresa_id
  OGESS ve facilities de su ogess_id
  UNGET ve facilities de su unget_id
  MICRORED ve facilities de su microred_id
  IPRESS/FARMACIA ve solo su facility_code
- Mantener Apps Script como fallback si no hay datos en Supabase directo.
- Mantener columnas visuales equivalentes:
  ALMCOD, DESC_ALM, ID_Producto, CODIGO_SIG, Nombre, Lote, Fec_Vencim, Reg_Sanitario, TIPSUM, DESC_TIPSUM, FFINAN, DESC_FFINAN, Saldo, Precio_Det, Precio_Cab, FECHA_DEL_EQUIPO, Ultima_Actualizacion.
- Mapear desde stock_actual:
  medcod -> ID_Producto
  xnom -> Nombre
  fecha -> Fec_Vencim
  fecha_equipo -> FECHA_DEL_EQUIPO
  ultima_actualizacion -> Ultima_Actualizacion

No eliminar todavia el flujo Apps Script.
```

## Prompt 5 - Modulo IPRESS Stock

```text
Necesito adaptar IpressStockModule.tsx para que use Supabase directo cuando haya datos en stock_actual del facility_code del usuario.

Actualmente IpressStockModule obtiene facility_stock_assignments, usa sheetUrl/sheetName y hace fetch a Apps Script.

Nuevo comportamiento:
1. Obtener facility_code del usuario actual.
2. Consultar stock_actual donde facility_code = facility_code del usuario.
3. Si hay registros, mostrar esos datos agrupados por almcod como vistas internas/farmacias.
4. Si no hay registros en Supabase, usar el flujo actual con facility_stock_assignments y Apps Script como fallback.
5. Conservar filtros, busqueda y columnas visibles.
6. Mostrar ultima actualizacion usando stock_actual.ultima_actualizacion y fecha del equipo usando stock_actual.fecha_equipo.

No romper facility_stock_assignments todavia, porque Google Sheets seguira como respaldo durante la transicion.
```
