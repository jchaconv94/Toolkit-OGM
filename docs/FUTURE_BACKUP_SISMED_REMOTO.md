# Requerimiento futuro: Backup SISMED Remoto Desktop a Desktop

## Objetivo

Implementar en ToolKit SISMED Desktop una herramienta para obtener backups SISMED remotos sin almacenar archivos pesados en Supabase ni en la app web.

La idea es similar a Syncthing, pero enfocada solo en backups SISMED:

- PC del establecimiento: detecta y ofrece el backup mas reciente.
- PC administradora: monitorea y descarga el backup directamente.

## Principio de arquitectura

Supabase no debe almacenar los backups completos.

Supabase podria usarse solo como directorio liviano opcional:

- instalaciones registradas
- establecimiento/IPRESS
- PC
- ultimo backup detectado
- fecha
- tamano
- estado online/offline
- token o datos de conexion

El archivo debe transferirse directo:

```text
PC establecimiento -> PC administradora
```

## Modo recomendado inicial

Usar una red privada tipo Tailscale o VPN para resolver conectividad entre redes distintas.

ToolKit SISMED no deberia intentar implementar P2P completo en la primera version. Primero debe:

1. detectar el backup mas reciente
2. levantar un servidor local seguro solo en red privada
3. permitir descarga desde la PC administradora
4. transferir por partes
5. verificar SHA-256 al finalizar

## Modulo propuesto

Nombre sugerido:

```text
Backup SISMED Remoto
```

Pestanas sugeridas:

- Este equipo
- Mis establecimientos

## Este equipo

Para la PC del establecimiento:

- carpeta backup SISMED
- ultimo backup detectado
- tamano
- fecha
- permitir descargas
- puerto local
- token local de descarga
- estado del servicio

## Mis establecimientos

Para la PC administradora:

- lista de PCs remotas
- establecimiento/IPRESS
- ultimo backup
- estado online/offline
- boton Descargar ultimo backup
- progreso de descarga
- verificacion de integridad

## Reglas importantes

- La app web no debe ser requisito para monitorear o descargar.
- Los backups no deben subirse completos a Supabase.
- La ruta SISMED puede cambiar y debe ser configurable.
- La descarga debe ser bajo demanda, no automatica masiva.
- Debe existir control de permisos/token.
- Se debe evitar exponer puertos publicos a Internet.
- La primera version puede requerir Tailscale/VPN.

## Fases

### Fase 1

Solo detectar y mostrar el ultimo backup local.

### Fase 2

Servidor local seguro para descargar el backup desde red privada.

### Fase 3

Panel administrador desktop para listar PCs y descargar backups.

### Fase 4

Directorio liviano con Supabase para descubrir PCs y estados.

### Fase 5

Reintentos, descarga por partes, hashes y auditoria.
