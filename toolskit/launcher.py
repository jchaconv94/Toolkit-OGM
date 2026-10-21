"""Arranque del Toolkit instalado: elige el código (el del instalador o una actualización ya descargada)
y lo abre. Va dentro de ToolkitOGM.exe y casi nunca cambia; ver app_loader."""

import app_loader

update = app_loader.prepare()
app_loader.run_main(app_loader.import_main(update), update)
