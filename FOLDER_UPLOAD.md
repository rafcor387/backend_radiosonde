# Cargar una carpeta anual de radiosondeos

Nuevo endpoint: `POST /feature/radiosondes/upload-folder/`.
Requiere autenticación JWT, igual que la carga individual.

## Petición

Formato `multipart/form-data`:

- `year`: año de la carpeta, por ejemplo `2018`.
- `files`: varios archivos TSV, repitiendo este campo por archivo.

Puede utilizarse desde Swagger (`/swagger/`) con su selector de varios archivos.
Una carpeta del equipo no se envía como una ruta de disco al backend: se envían
sus archivos. El comando incluido permite seleccionar la carpeta completa.

Cada lote admite hasta **50 archivos y 50 MiB en total**. Cada TSV mantiene el
límite individual de **10 MiB**. Para carpetas grandes se envían varios lotes.
Los límites del proxy/servidor de despliegue también deben permitir el tamaño
elegido; el comando usa 20 archivos por lote y acepta `--batch-size`.

## Carpeta completa desde PowerShell

Con Django iniciado, desde `backend_radiosonde`:

```powershell
# Revisar el plan; no envía nada y no pide credenciales.
.\venv\Scripts\python.exe scripts\upload_radiosonde_folder.py --folder ..\radiosonde_files\2018 --dry-run

# Enviar la carpeta. Solicita el token de acceso JWT sin mostrarlo ni guardarlo.
.\venv\Scripts\python.exe scripts\upload_radiosonde_folder.py --folder ..\radiosonde_files\2018
```

Para otro año cambia la carpeta. El año se obtiene de su nombre; no se limita
a una lista fija de años. `--api-url` permite indicar otra dirección del backend.
También puede proporcionarse el token mediante `RADIOSONDE_UPLOAD_TOKEN`.

El comando crea un informe JSON en `output/uploads/`. Con `--report` se elige
otra ubicación. Puede ejecutarse de nuevo: las claves ya registradas se omiten.
Los errores de transporte dejan el informe como `incomplete`; los lotes anteriores
siguen guardados y pueden revisarse antes de reintentar.

## Almacenamiento y validación

- Bucket: `radiosondes`.
- Clave: `2018/14052018EDT.tsv`, conservando el nombre original saneado.
- Tabla: `radiosonde_profile`, con fecha, hora sinóptica, lanzamiento UTC,
  bucket y clave exacta. El identificador se genera automáticamente.
- El año del encabezado `Launch time` debe coincidir con `year`.
- Se reutilizan las validaciones de estación de La Paz, formato y tamaño.
- Un archivo inválido no revierte los demás. Cada TSV tiene su propia transacción.
- La carga individual existente conserva sus claves sin prefijo y su contrato.

## Duplicados

Una clave ya registrada se omite sin sobrescribirla. El contenido idéntico con
otro nombre también se omite: se compara SHA-256 con los perfiles del mismo
lanzamiento, o del mismo día si el registro antiguo no tiene `observed_at`.
Para nuevas cargas se utiliza el hash guardado en los metadatos de R2. Si un
registro antiguo no tiene hash, se recupera su objeto para compararlo.
Esto permite reconocer copias antiguas guardadas en la raíz del mismo bucket.

Si la clave existe en R2 sin registro de catálogo, se informa un fallo con
`storage_object_without_catalog`. No se sobrescribe ni se registra a ciegas.

## Respuesta

HTTP 200 indica que se procesó el lote. Revisa siempre `uploaded`, `skipped`,
`failed` y cada elemento de `results`. `status` es `completed` o
`completed_with_errors`.

Cada resultado contiene `filename`, `object_key`, `status` y los metadatos
creados o la razón del rechazo. Los motivos incluyen `duplicate_content`,
`already_registered`, `invalid_file` y `storage_error`.

## Verificación local sin Cloudflare ni PostgreSQL reales

```powershell
.\venv\Scripts\python.exe -B manage.py test feature.test_bulk_upload feature.tests.RadiosondeUploadViewTests --settings=radiosonde.test_settings --noinput
```

Estas pruebas usan SQLite en memoria y un cliente R2 de prueba. No realizan
subidas reales. No se requieren migraciones adicionales para este endpoint.

este es el comando para obtener y cargar los radisondeos tanto en la base de datos como en cloudflare
python scripts\upload_radiosonde_folder.py --folder ..\radiosonde_files\2018