# Code signing policy

The Windows releases of ToolKit SISMED are meant to be signed through the **SignPath Foundation** open source program: free code signing provided by [SignPath.io](https://signpath.io), certificate by [SignPath Foundation](https://signpath.org). Until the project is accepted, releases are published unsigned, with a SHA-256 checksum next to each installer.

## What is signed

Only files built from this repository by its GitHub Actions workflow (`.github/workflows/publish-desktop-release.yml`) are signed:

- `ToolkitOGM.exe`, the program;
- `ToolkitUpdateHost.exe`, the helper that installs updates;
- `ToolkitOGM-Setup-<version>.exe`, the installer.

Releases are published at <https://github.com/jchaconv94/ToolkitSISMED/releases>. The small code updates the program downloads between installers (`ToolkitOGM-app-<version>.zip`) are verified by the program with its own Ed25519 signature before they are used.

## Team roles

- Committers and reviewers: [jchaconv94](https://github.com/jchaconv94)
- Approvers: [jchaconv94](https://github.com/jchaconv94)

Every signing request is approved by hand by an approver. Code changes reach the release branch through pull requests; a release is built by the workflow when a commit changes the `VERSION` file on that branch, or when the repository owner starts the workflow by hand.

## Privacy policy

ToolKit SISMED does not collect analytics or telemetry and does not show ads. It only contacts other systems for the following functions:

- **Updates.** It checks the releases of `jchaconv94/ToolkitSISMED` on GitHub and downloads new versions from GitHub. This can be turned off in the program's settings.
- **Sync SISMED** (only when the facility turns it on). It sends the facility's stock of medicines and supplies (codes, batches, balances, expiry dates and prices) to the Google Sheets of its health network through Google Apps Script. If the facility's network blocks Google, the same data goes through the regional relay (`sismed-conexion.jchaconvillacis.workers.dev` or the regional Supabase project), which forwards it to the same Google Sheet.
- **Send key check** (only for facilities with a send key). Before sending stock, it sends to the regional Supabase project the facility code, its send key, an identifier and the name of the PC, the number of records sent and the versions of ToolKit SISMED and SISMED installed, so the regional office can tell which PC sends each facility's stock.
- **Backups SISMED** (only for facilities enabled by the regional office). It keeps a connection with the regional service (`sismed-conexion.jchaconvillacis.workers.dev`) and uploads the most recent backup file made by SISMED to the regional cloud storage, where only authorized users of the regional office can download it.

The regional services belong to the Regional Health Directorate of San Martín (DIRESA San Martín, Peru), which operates this program for its health facilities.

---

## Resumen (español)

Las versiones de Windows se firmarán con el programa de código abierto de **SignPath Foundation** (firma gratuita de SignPath.io, certificado de SignPath Foundation). Mientras no esté aprobado, se publican sin firma y con su huella SHA-256.

- **Se firman** solo `ToolkitOGM.exe`, `ToolkitUpdateHost.exe` y el instalador, compilados desde este repositorio por GitHub Actions. Cada firma la aprueba a mano un aprobador.
- **Responsable** del código, de las revisiones y de aprobar las firmas: jchaconv94.
- **Privacidad:** sin analítica ni publicidad. Solo se conecta para buscar actualizaciones en GitHub; para enviar el stock a las hojas de Google de la red de salud (Sync SISMED, si el establecimiento lo activa); para validar la clave de envío en el Supabase regional, con el código del establecimiento, la PC y las versiones instaladas; y para subir la copia de seguridad del SISMED al almacenamiento de la DIRESA (Backups SISMED, si la DIRESA lo habilita).
