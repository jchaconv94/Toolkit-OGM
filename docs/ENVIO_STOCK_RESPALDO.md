# Envío de stock por camino de respaldo (desde 2.3.2)

Algunas redes de establecimientos (PRONATEL) bloquean `script.google.com`: desvían su DNS a una
IP interna (`10.254.30.102`) y cortan la conexión por nombre. Pasó en PUERTORICO (06474) y en
CONSUELO (06506). Desde la versión 2.3.2, Sync SISMED prueba en orden:

1. **Google directo**, como siempre.
2. **Respaldo Cloudflare**: `sismed-conexion` (el mismo servicio de Backups SISMED), ruta `/stock`.
3. **Respaldo Supabase**: función `stock-relay`, como mucho una vez cada 30 minutos.

Los respaldos pasan el mismo envío al mismo Apps Script de la UNGET; no guardan nada y solo
aceptan una PC con clave de envío vigente. El código del reenvío, las reglas completas y los
casos de falla están en el repositorio ToolkitSISMED: `docs/ENVIO_STOCK_RESPALDO.md`.

En este repositorio:

- `toolskit/stock_routes.py`: direcciones de los respaldos, detección del DNS desviado, lectura
  de la respuesta del respaldo y limpieza del registro.
- `toolskit/sismed_sync.py`: `_post_payload_with_retries` y `_post_by_routes` eligen el camino.
- `tests/test_stock_routes.py`: los casos (DNS desviado, TLS cortado, Google lento, clave
  rechazada, respaldo caído, límite de Supabase, registro sin secretos).

**Registro sin secretos:** la consola de Sync SISMED y su archivo de registro ya no muestran la
clave de envío (`06506-****`), el `equipo_id` ni la dirección del Apps Script (`/macros/s/***/exec`).
