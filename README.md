[ 🇪🇸 Castellano ](README.md) | [ 🇺🇸 English ](README_EN.md)

# SmartMule 🫏

### El Bibliotecario Inteligente para el Ecosistema P2P

**SmartMule** es un servicio automatizado de organización y seguridad diseñado para transformar el caos de las descargas P2P (eMule, aMule, etc.) en una biblioteca perfectamente estructurada. Utiliza vigilancia del sistema de archivos, hashing criptográfico (ED2K) e Inteligencia Artificial para clasificar, limpiar y proteger tu equipo de amenazas camufladas.

![SmartMule](/images/SmartMule_Logo_Oficial.png)

![Terminal](/images/terminal.png)

![alt text](images/pop_up.png)

---

## ¿Es realmente necesario?

Por defecto, eMule deposita todas las descargas finalizadas en una única carpeta `Incoming`. Con el tiempo, este directorio se convierte en un caos de películas, software, música y archivos con nombres crípticos. 

**SmartMule** soluciona este problema identificando, limpiando y moviendo cada archivo a su categoría temática correspondiente de forma automática, manteniendo tu biblioteca organizada sin esfuerzo manual.

---

## Características Principales

*   **Vigilancia Activa (Watchdog)**: Detecta archivos nuevos en tu carpeta `Incoming` al instante.

*   **Doble Capa de Verificación**: Identifica archivos por su nombre (IA) y por su contenido (Hash ED2K / Fingerprint). 

*   **Soporte de Directorios (Folder Grouping)**: SmartMule detecta si una descarga es una carpeta (ej: película con subtítulos). Identifica el archivo principal para el hashing y los metadatos, pero mueve y renombra **toda la carpeta** como una única unidad funcional.

*   **Antimalware Semántico (Triaje de Élite)**: Inspección profunda de archivos sin extracción usando **VirusTotal**. SmartMule no se fía de nadie:
    -   **Análisis de Macros**: Detecta documentos de Office con macros (`.xlsm`, `.docm`, etc.) y formatos antiguos (`.doc`, `.xls`) tratándolos como ejecutables.
    -   **Vigilancia de PDF**: Escaneo automático de archivos PDF ante scripts maliciosos.
    -   **Inspección de Contenedores**: El `ArchiveInspector` analiza archivos `.zip`, `.rar` y `.7z` buscando inconsistencias (ej: un `.exe` disfrazado de película) y mostrando el contenido sospechoso en los logs.
    -   **Puntuaciones Críticas**: Si un archivo tiene más de 5 detecciones en VT (priorizando motores TOP como Microsoft o Kaspersky), lo mueve a **Review** para evitar riesgos.

*   **Desempate Inteligente (Tie-Breaking)**: Usa la duración real de los videos para distinguir entre películas homónimas (ej: Solaris 1972 vs Solaris 2002).

*   **Triaje Automático**: 
    -   `MALICIOUS`: Borrado automático destructivo.
    -   `SUSPICIOUS`: Cuarentena para revisión manual.
    -   `SAFE`: Organización temática automatizada.

    ![alt text](/images/suspicious.png)
    ![alt text](/images/antimalware.png)


*   **Privacidad**: Compatible con modelos locales (LM Studio) para procesar nombres sin subirlos a la nube.

*  **Gasto de recursos muy bajo**: SmartMule está diseñado para ejecutarse en segundo plano sin interferir con el uso normal del PC. Para ello, establece una prioridad de I/O (`IOPRIO_VERYLOW`) y CPU (`IDLE_PRIORITY_CLASS`) mínimas, de forma que el SO solo asigna recursos al proceso cuando no hay otras aplicaciones demandándolos.

---

### 📂 Estrategias de Organización (`ORGANIZER_MODE`)

SmartMule permite elegir cómo se gestionan los archivos físicamente mediante la variable `ORGANIZER_MODE` en el archivo `.env`:

| Modo | Soporta _Seeding_ (eMule) | Descripción |
| :--- | :--- | :--- |
| **`hardlink`** (Por defecto) | ✅ **Sí** | Crea un vínculo físico. El archivo aparece en `Incoming` y `Library` pero **solo ocupa espacio una vez**. Ideal para seguir compartiendo mientras mantienes tu biblioteca limpia. |
| **`move`** | ❌ **No** | Mueve el archivo de una carpeta a otra. Es instantáneo pero eMule dejará de compartirlo al no encontrarlo en la ruta original. |
| **`copy`** | ✅ **Sí** | Duplica el archivo. Es el más lento y **consume el doble de espacio**, pero es el único que funciona entre discos duros físicos distintos. |

>[!TIP]
> Usa **`hardlink`** siempre que `Incoming` y `Library` estén en el mismo disco duro.
---

## 🛠️ Requisitos del Sistema

### 1. Dependencias de Python

Instala las librerías necesarias con:
```bash
pip install -r requirements.txt
```

### 2. Herramientas de Sistema (OBLIGATORIO)

Para el análisis de archivos y desempate de películas, SmartMule requiere:

*   **FFmpeg (ffprobe)**: Necesario para extraer la duración y resolución de los videos.
    -   **Windows**: Descarga de [ffmpeg.org](https://ffmpeg.org/download.html), extrae el `.zip` y añade la carpeta `bin` al `PATH` de tu sistema.
    -   **Linux**: `sudo apt install ffmpeg`

*   **7-Zip / Patool**: Necesario para inspeccionar archivos comprimidos.
    -   **Windows**: Instala [7-Zip](https://www.7-zip.org/) y asegúrate de que esté en el `PATH`.
    -   **Linux**: `sudo apt install p7zip-full`

---

## Cómo funciona (El Pipeline de Datos)

1.  **Monitorización**: El `Watcher` detecta el archivo e inicia una espera de desbloqueo (_I/O unlock_).

2.  **Caché Inteligente**: Se calcula una "Fingerprint" rápida. Si el archivo ya existe y el `mtime` (_modification time_) no ha cambiado, se reutilizan los metadatos para ahorrar APIs.

3.  **Análisis Semántico**: Si es un contenedor, el `ArchiveInspector` busca amenazas antes de que el usuario lo abra.

4.  **Capa IA (LLM)**: Limpia el nombre "sucio" de la _Scene_ y detecta el tipo de medio (Cine, Música, Libros, Software, etc.).

5.  **Enriquecimiento (API)**: Consulta **TMDB** u **OpenLibrary** usando el año y la duración para un emparejamiento perfecto.

6.  **Organización**: El `LibraryOrganizer` mueve el archivo a su destino final (ej: `/Library/Movies_and_Series/Matrix (1999).mkv`).

---

## Daemon (Ejecución en Segundo Plano)

SmartMule está diseñado para ejecutarse una sola vez y quedarse vigilando permanentemente de forma completamente invisible.

*   **Arrancar (Modo Invisible)**: Haz doble clic en el archivo `smartmule_launcher.vbs`. Esto levantará el proceso en segundo plano. Recomiendo crear un acceso directo a este archivo y colocarlo en tu carpeta de *Autoinicio de Windows* (`shell:startup`) para que arranque solo al encender el PC.

*   **Detener**: Si necesitas pararlo, abre una terminal cualquiera (CMD o PowerShell) y ejecuta `python main.py stop`. SmartMule detectará el proceso oculto y lo cerrará limpiamente.

    ![stop_pid](/images/stop_pid.png)

*   **Auditoría**: Toda la actividad silenciosa quedará registrada en el archivo `smartmule.log` (en la raíz del proyecto). Puedes seguirlo en tiempo real en la terminal ejecutando:
    ```powershell
    Get-Content smartmule.log -Wait -Encoding UTF8
    ```

    ![alt text](/images/logs.png)

*   **Inventario y Estadísticas**: Para ver rápidamente qué archivos tienes registrados en la biblioteca y el desglose por categorías (Películas, Libros, etc.), usa la flag `--list`:
    ```bash
    python main.py --list
    ```

    ![alt text](/images/inventory.png)
 
---

## Mantenimiento y Purga (_Smart Deletion_)

_Cuando usas el modo `hardlink` (predeterminado), borrar un archivo de tu biblioteca no lo borra físicamente del disco si aún existe en la carpeta `Incoming` (y viceversa). Esto es necesario para seguir compartiendo como cliente eMule (y ganar créditos en la red), pero puede ser tedioso de limpiar_. 

Para facilitar la limpieza total, SmartMule incluye un comando de purga/eliminación de archivos:

*   **Purga Selectiva**: Busca archivos por nombre, comodines (_Wildcards_) o expresiones regulares (_Regex_). 
    ```bash
    python main.py --purge "nombre*"  # Encuentra archivos que empiecen por "nombre"
    python main.py --purge ".*\.mkv$" # Encuentra todos los archivos con extensión .mkv
    ```

*   **Explorador Interactivo**: Si ejecutas el comando sin términos de búsqueda, SmartMule te mostrará la lista completa de tu biblioteca para que elijas qué eliminar.
    ```bash
    python main.py --purge
    ```

Ejemplo de uso:
![alt text](images/purge.png)

*   **Modo Destructivo (Limpieza Total)**: ⚠️⚠️ Borra absolutamente todos los archivos registrados en la base de datos de un solo golpe.
    ```bash
    python main.py --purge --all --no-preserve
    ```
    *Nota: Este comando requiere una confirmación de texto (escribir "BORRAR TODO") por seguridad.*

### 🚀 Purga en un solo clic (Windows)
Para mayor comodidad, SmartMule despliega automáticamente una herramienta llamada **`Purga_Interactiva.bat`** dentro de tu carpeta de biblioteca (`LIBRARY_PATH`). 

Solo tienes que hacer doble clic en ella para buscar y eliminar archivos sin tener que abrir la terminal ni recordar comandos:
![alt text](images/purge_script.png)

---

## Configuración en eMule (IMPORTANTE)

Para no perder visibilidad en la red ni dejar de ganar créditos tras la organización de tus archivos, sigue estos pasos:

1.  **Compartir Biblioteca**: Ve a eMule > **Opciones** > **Directorios** y marca la carpeta `Library` como directorio compartido (asegúrate de incluir sus subcarpetas).

![shared_folders](/images/shared_folders.png)

2.  **Privacidad**: No compartas la carpeta raíz de SmartMule, solo la carpeta `Library`. SmartMule guarda su base de datos en una carpeta oculta (`.data`) para que eMule no la indexe.

3.  **Mantener Créditos**: Tus créditos están asociados a tu *User Identification* (Hash), no a los nombres de los archivos. Al compartir la `Library` con los archivos ya limpios y renombrados, eMule reconocerá que tienes el mismo contenido (mismo Hash ED2K) y seguirás sumando prioridad de subida.

---

## Configuración para Torrents (BitTorrent, uTorrent, qBittorrent)

SmartMule es totalmente compatible con gestores de descargas Torrent. Debido a que las redes Torrent detienen el *seeding* (compartir) si cambias el archivo de sitio, SmartMule usa por defecto la creación de **Hardlinks** para los archivos de estas redes, asegurando que puedas seguir compartiendo (_Seeding_) los archivos sin interrupciones.

1.  **Ajustes de Extensiones (Crucial)**: Para prevenir que SmartMule procese archivos sin terminar, es obligatorio que actives la opción de de tu cliente de Torrent para agregar una extensión a las descargas incompletas. (Ej. *`Append .!ut to incomplete files`* en uTorrent o *`Añadir !qB a descargas incompletas`* en qBittorrent).

    ![alt text](images/torrent_conf.png)

2.  **Mismo Disco**: Los _Hardlinks_ exigen que la carpeta `Incoming` y la `Library` estén en la misma partición del sistema o disco duro.

3.  **Configuración de Modo**: Puedes alterar el comportamiento modificando la variable `ORGANIZER_MODE` en tu `.env` (`hardlink` por defecto, pudiendo elegir `copy` o `move`).

---

## Testing

SmartMule cuenta con una suite de pruebas para garantizar la estabilidad:
```bash
pytest -v --tb=short
```

---

## 🚀 Motor de Hashing Paralelo (Optimización)

SmartMule incluye un **motor de hashing ED2K de alto rendimiento** diseñado para no saturar tu sistema, que reduce el tiempo de cálculo del hash de forma exponencial:

-   **Arquitectura Híbrida**: Lectura secuencial de disco (`IOPRIO_VERYLOW`) combinada con cálculo paralelo mediante hilos (`multi-threading`)

-   **Control de RAM**: Sistema de _Backpressure_ que garantiza un consumo de memoria mínimo y constante (~55MB), sin importar si procesas un archivo de 1GB o una ISO de 200GB.

-   **Cortesía con el SO**: Ajusta automáticamente la prioridad de la CPU (`IDLE`) y limita el uso al 50% de tus núcleos, asegurando que el sistema sea totalmente fluido incluso durante tareas intensivas.

---
