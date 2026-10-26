# ToolKit SISMED (escritorio)

Herramienta de escritorio para Windows de la **Dirección Regional de Salud San Martín (DIRESA San Martín, Perú)** para las farmacias y almacenes que trabajan con el **SISMED** (Sistema Integrado de Suministro de Medicamentos e Insumos Médico-Quirúrgicos). Lee las tablas del SISMED (archivos DBF) del propio establecimiento y arma reportes, el ICI y correcciones, y mantiene el stock y las copias de seguridad al día para la red de salud.

> **About (English).** ToolKit SISMED is a Windows desktop tool of the Regional Health Directorate of San Martín (Peru) for the pharmacies that use SISMED, the Ministry of Health's medicine supply system. It reads the SISMED tables (DBF files) of the facility, builds reports and the monthly consumption report (ICI), fixes common data problems, synchronizes stock with the regional Google Sheets and uploads SISMED backups for the regional office. It is free and open source under the AGPL-3.0 license.

## Herramientas

**Farmacia**
- **Anexar TFORMDET**: agrega meses nuevos desde otro DBF TFORMDET.
- **Disponibilidad TFORMDET**: reporte de consumos mensuales.
- **Generar ICI**: Informe de Consumo Integrado listo para firmar (Excel y PDF).

**Reportes SISMED**
- **Consulta TFORMDET**: consulta detallada de movimientos.
- **Reporte de guías**: guías por fecha e ítem.
- **Stock SISMED**: stock general y detallado en Excel.
- **Consumo valorizado**: valorizado por establecimiento para SIS, intervención y venta.

**Edición del SISMED**
- **Cambiar estado de medicamentos**: campo MEDEST de MPRODUCTO.DBF.
- **Habilitar guías**: habilita guías anuladas, quita bloqueos y cambia el modo de ingreso en TMOVIM.DBF.

**Herramientas generales**
- **DBF a Excel**, **Unir Excel**, **Formato TFORMDET** y **Editor PDF** (reorganiza, elimina y convierte páginas).

**Conexión con la red de salud**
- **Sync SISMED**: envía el stock del establecimiento a las hojas de Google de su red de salud.
- **Backups SISMED**: sube la copia de seguridad más reciente del SISMED para que la DIRESA pueda recuperarla.

Qué se envía por internet y a dónde está detallado en [CODE_SIGNING.md](CODE_SIGNING.md#privacy-policy).

## Descarga

Las versiones para Windows 10 y 11 (64 bits) se publican gratis en
**https://github.com/jchaconv94/ToolkitSISMED/releases/latest** (`ToolkitOGM-Setup-<versión>.exe`, con su huella SHA-256). Una vez instalado, el Toolkit busca y descarga solo sus actualizaciones.

Cada versión se compila desde este repositorio con GitHub Actions (`.github/workflows/publish-desktop-release.yml`); cómo se arma y se publica está en [packaging/windows/RELEASE_AUTOMATION.md](packaging/windows/RELEASE_AUTOMATION.md), y cómo trabajar con el código en [toolskit/README.md](toolskit/README.md).

## Firma del código

La política de firma de los ejecutables de Windows está en [CODE_SIGNING.md](CODE_SIGNING.md).

## Licencia

ToolKit SISMED es software libre: se distribuye bajo la **GNU Affero General Public License v3.0** ([LICENSE](LICENSE)). Las librerías que usa y sus licencias están en [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).
