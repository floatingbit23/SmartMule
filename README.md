[ 🇪🇸 Castellano ](README.md) | [ 🇺🇸 English ](README_EN.md)

# SmartMule 🫏

### El Bibliotecario Inteligente para el Ecosistema P2P

**SmartMule** es un servicio automatizado de organización, seguridad y búsqueda inteligente diseñado para transformar el caos de las descargas P2P (eMule, aMule, clientes Torrent, etc.) en una biblioteca perfectamente estructurada. Utiliza vigilancia del sistema de archivos, hashing criptográfico (ED2K), Inteligencia Artificial (_Small Language Models_) y un motor de búsqueda híbrido (FTS5 + Semántico) para clasificar, limpiar, localizar y proteger tu equipo de amenazas camufladas.

![SmartMule](/images/SmartMule_Logo_Oficial.png)

![Terminal](/images/terminal.png)

![alt text](images/pop_up.png)

---

## ¿Es realmente necesario?

Por defecto, eMule deposita todas las descargas finalizadas en una única carpeta `Incoming`. Con el tiempo, este directorio se convierte en un caos de películas, software, música y archivos con nombres crípticos. 

**SmartMule** soluciona este problema identificando, limpiando y moviendo cada archivo a su categoría temática correspondiente de forma automática, manteniendo tu biblioteca organizada sin esfuerzo manual.

---

## 📂 Estructura de la Biblioteca

SmartMule organiza tus archivos en las siguientes categorías automáticas dentro de tu carpeta `Library`:

| Categoría | Carpeta | Descripción |
| :--- | :--- | :--- |
| 🎬 **Cine y TV** | `Movies_and_Series` | Películas y episodios de series (MKV, MP4, AVI, etc.). |
| 🎵 **Música** | `Music` | Álbumes y pistas de audio (MP3, FLAC, OGG, etc.). |
| 📚 **Libros** | `Books` | eBooks, cómics y documentos técnicos (PDF, EPUB, CBR, etc.). |
| 💾 **Software** | `Software` | Programas e instaladores (EXE, MSI, APK, etc.). |
| 📄 **Información** | `Information` | Metadatos P2P (`.torrent`, `.emulecollection`), archivos `.nfo` y `.md5`. |
| 📦 **Comprimidos** | `Compressed` | Archivos ZIP, RAR o 7Z que no contienen medios claros. |
| 🖼️ **Imágenes** | `Images` | Fotos y material gráfico (JPG, PNG, WEBP, etc.). |
| 📝 **Documentos** | `Documents` | Archivos de texto y ofimática (DOCX, XLSX, TXT, etc.). |
| 📁 **Otros** | `Other` | Archivos que no han podido ser categorizados automáticamente. |
| 🛡️ **Cuarentena** | `00_Quarantine` | Archivos altamente sospechosos o detectados como maliciosos por el sistema antimalware. |
| 🔍 **Revisión** | `01_Review` | Archivos que requieren intervención manual para su clasificación. |

## Características Principales

*   **Vigilancia Activa (Watchdog)**: Detecta archivos nuevos en tu carpeta `Incoming` al instante.

*   **Doble Capa de Verificación**: Identifica archivos por su nombre (IA) y por su contenido (Hash ED2K / Fingerprint). 

*   **Soporte para Agrupación y Metadatos**: SmartMule detecta si una descarga es una carpeta (ej: película con subtítulos). Identifica el archivo principal para el hashing pero mueve la **carpeta completa**. 

    Además, organiza automáticamente archivos operativos como **Colecciones de eMule (`.emulecollection`)** y archivos **`.torrent`** en la categoría de `Información`.

*   **Antimalware Semántico (Triaje de Élite)**: Inspección profunda de archivos sin extracción usando **VirusTotal**. SmartMule no se fía de nadie:
    -   **Análisis de Macros**: Detecta documentos de Office con macros (`.xlsm`, `.docm`, etc.) y formatos antiguos (`.doc`, `.xls`) tratándolos como ejecutables.
    -   **Vigilancia de PDF**: Escaneo automático de archivos PDF ante scripts maliciosos.
    -   **Inspección de Contenedores**: El `ArchiveInspector` analiza archivos `.zip`, `.rar` y `.7z` buscando inconsistencias (ej: un `.exe` disfrazado de película) y mostrando el contenido sospechoso en los logs.
    -   **Puntuaciones Críticas**: Si un archivo tiene más de 5 detecciones en VT (priorizando motores TOP como Microsoft o Kaspersky), lo mueve a **Review** para evitar riesgos.

*   **Desempate Inteligente (Tie-Breaking)**: Utiliza un sistema de scoring heurístico basado en el año de estreno y la duración técnica (FFmpeg) para distinguir entre películas homónimas (ej: Solaris 1972 vs Solaris 2002).

*   **Búsqueda Inteligente (FTS5)**: Motor de búsqueda global integrado con soporte para filtros avanzados. Localiza cualquier archivo por título, tipo, puntuación, resolución, género o fecha al instante. 

    ```bash
    smartmule --search "Matrix"               # Búsqueda por nombre o título
    smartmule --search "type:movie score>8"  # Búsqueda con filtros de tipo y nota
    smartmule --search "res:1080p genre:scifi" # Filtros por resolución y género
    smartmule --search "verdict:safe"          # Solo archivos verificados como seguros
    smartmule --search "added:today"           # Archivos añadidos en las últimas 24h
    ```

*   **Reproducción Integrada (VLC)**: Permite lanzar contenidos multimedia directamente desde tu consola mediante el flag `--play`. El sistema filtra automáticamente las coincidencias de tipo vídeo (películas, series...) y abre el mejor resultado asíncronamente en *VLC Media Player* sin bloquear tu terminal (con soporte de _fallback_ al reproductor por defecto en caso de no encontrarse VLC).

    ```bash
    smartmule --play "Matrix"                  # Reproduce en VLC el primer vídeo que coincida
    ```

*   **Triaje Automático**: 
    -   `SAFE`: Organización temática automatizada.
    -   `SUSPICIOUS`: Cuarentena para revisión manual.
    -   `MALICIOUS`: Borrado automático destructivo.

    ![alt text](/images/suspicious.png)
    ![alt text](/images/antimalware.png)

*   **Privacidad**: Compatible con modelos locales (LM Studio) para procesar nombres sin subirlos a la nube.

*  **Gasto de recursos muy bajo**: SmartMule está diseñado para ejecutarse en segundo plano sin interferir con el uso normal del PC. Establece una prioridad de I/O (`IOPRIO_VERYLOW`) y CPU (`IDLE_PRIORITY_CLASS`) mínimas. Además, utiliza el modo **SQLite WAL** para permitir búsquedas instantáneas incluso mientras el motor está organizando archivos pesados.

---

### 📂 Estrategias de Organización (`ORGANIZER_MODE`)

SmartMule permite elegir cómo se gestionan los archivos físicamente mediante la variable `ORGANIZER_MODE` en el archivo `.env`:

| Modo | Soporta _Seeding_ (eMule) | Descripción |
| :--- | :--- | :--- |
| **`hardlink`** (Por defecto) | ✅ **Sí** | Crea un vínculo físico. El archivo aparece en `Incoming` y `Library` pero **solo ocupa espacio una vez**. |
| **`move`** | ❌ **No** | Mueve el archivo. eMule dejará de compartirlo al no encontrarlo en la ruta original. |
| **`copy`** | ✅ **Sí** | Duplica el archivo. Consume el doble de espacio pero funciona entre discos físicos distintos. |

>[!TIP]
> Usa **`hardlink`** siempre que `Incoming` y `Library` estén en el mismo disco duro.

---

## 🛠️ Requisitos del Sistema

### Dependencias de Python

Instala las librerías necesarias con:
```bash
pip install -r requirements.txt
```

### Herramientas de Sistema (OBLIGATORIO)

Para el análisis de archivos y desempate de películas, SmartMule requiere:

*   **FFmpeg (ffprobe)**: Necesario para extraer la resolución y metadatos técnicos de los videos.
    -   **Windows**: Descarga de [ffmpeg.org](https://ffmpeg.org/download.html), extrae el `.zip` y añade la carpeta `bin` al `PATH` de tu sistema.
    -   **Linux**: `sudo apt install ffmpeg`

*   **7-Zip / Patool**: Necesario para inspeccionar archivos comprimidos.
    -   **Windows**: Instala [7-Zip](https://www.7-zip.org/) y asegúrate de que esté en el `PATH`.
    -   **Linux**: `sudo apt install p7zip-full`

---

## 🚀 Configuración del Alias (Recomendado)

Para usar SmartMule de forma sencilla desde cualquier terminal (sin tener que escribir `python main.py` o activar el entorno virtual manualmente), configura el comando `smartmule`:

### En Windows (PowerShell / CMD)
1. Crea un archivo llamado `smartmule.bat` en una carpeta que esté en tu `PATH` (ej: `C:\Windows`).
2. Pega este contenido ajustando las rutas a tu instalación:
   ```batch
   @echo off
   C:\SmartMule\venv\Scripts\python.exe C:\SmartMule\main.py %*
   ```

### En Linux / macOS
1. Abre tu configuración: `nano ~/.bashrc` (o `~/.zshrc`).
2. Pega esta línea al final ajustando la ruta:
   ```bash
   alias smartmule='/home/user/SmartMule/venv/bin/python3 /home/user/SmartMule/main.py'
   ```
3. Recarga: `source ~/.bashrc`

---

## Comandos disponibles (CLI)

Una vez configurado el alias, puedes usar estos comandos desde cualquier carpeta:

| Comando | Descripción |
| :--- | :--- |
| `smartmule start` | Arranca el motor de vigilancia (Daemon). |
| `smartmule stop` | Detiene el servicio de forma segura. |
| `smartmule restart` | Reinicia el motor (Stop + Start). |
| `smartmule --search "..."` | Búsqueda inteligente (Híbrida) con filtros. |
| `smartmule --play "..."` | Busca un archivo de vídeo y lo reproduce en _VLC Media Player_. |
| `smartmule --open "..."` | Abre cualquier archivo (música, libros, comprimidos...) con su aplicación preferida de forma segura. |
| `smartmule --build-index` | Reconstruir el índice semántico (IA). |
| `smartmule --stats` | Inventario y estadísticas de almacenamiento. |
| `smartmule --status` | Chequeo de salud y dependencias. |
| `smartmule --config` | Ver rutas y APIs activas. |
| `smartmule --log [N]` | Ver últimas N líneas del log. |
| `smartmule --purge "..."` | Herramienta de borrado selectivo. |
| `smartmule --reprocess "..."`| Forzar nuevo análisis de un archivo. |
| `smartmule --pid` | Ver el ID del proceso activo. |
| `smartmule --debug` | Habilitar logs detallados de IA. |

---


## Cómo funciona (El Pipeline de Datos)

1.  **Monitorización**: El `Watcher` detecta el archivo.
2.  **Caché Inteligente**: Se calcula una "Fingerprint" rápida para evitar duplicar análisis.
3.  **Análisis Semántico**: El `ArchiveInspector` busca amenazas en contenedores.
4.  **Capa IA (LLM)**: Limpia el nombre y detecta el tipo de medio.
5.  **Enriquecimiento (API)**: Consulta **TMDB** u **OpenLibrary**.
6.  **Organización**: El `LibraryOrganizer` mueve el archivo a su destino final.

---

## Daemon (Ejecución en Segundo Plano)

SmartMule está diseñado para ejecutarse una sola vez y quedarse vigilando permanentemente de forma completamente invisible.

*   **Arrancar (Modo Invisible)**: 

    - **Windows**: Haz doble clic en el archivo `smartmule_launcher.vbs`. Recomiendo colocar un acceso directo en tu carpeta de *Autoinicio* (`shell:startup`).
    
    - **Linux**: Ejecuta `./smartmule_launcher.sh`. Este script usa `nohup` para que el proceso siga vivo aunque cierres la terminal.

*   **Detener**: Ejecuta `smartmule stop`. SmartMule detectará el proceso oculto y lo cerrará limpiamente.

    ![stop_pid](/images/stop_pid.png)

*   **Auditoría**: Toda la actividad silenciosa quedará registrada en el archivo `smartmule.log`. Puedes ver las últimas líneas rápidamente con:
    ```bash
    smartmule --log      # Muestra las últimas 30 líneas (por defecto)
    smartmule --log 100  # Muestra las últimas 100 líneas
    ```
    O seguirlo en tiempo real en Windows:
    ```powershell
    Get-Content smartmule.log -Wait -Encoding UTF8
    ```
    Y en Linux / macOS:
    ```bash
    tail -f smartmule.log
    ```

    ![alt text](/images/logs.png)

*   **Inventario y Estadísticas**: 

    Para ver rápidamente qué archivos están registrados en la biblioteca, el desglose detallado por categorías (con su correspondiente espacio en GB/MB) y el tamaño total ocupado, usa el flag `--stats`. 

    ![alt text](/images/inventory.png)


    Para verificar el estado de salud y dependencias del sistema, usa `--status`. 

    > Imagen pendiente...


    Para verificar qué rutas y APIs tienes activas, usa `--config`:

    ![alt text](/images/config.png)

---

## Mantenimiento y Purga (_Smart Deletion_)

_Cuando usas el modo `hardlink` (predeterminado), borrar un archivo de tu biblioteca no lo borra físicamente del disco si aún existe en la carpeta `Incoming` (y viceversa). Esto es necesario para seguir compartiendo (_Seeding_) como cliente eMule (y ganar créditos en la red), pero puede ser tedioso de limpiar_. 

Para facilitar la limpieza total, SmartMule incluye un comando de purga/eliminación de archivos:

*   **Purga Selectiva**: Busca archivos por nombre, comodines (_Wildcards_) o expresiones regulares (_Regex_). 
    ```bash
    smartmule --purge "nombre*"  # Encuentra archivos que empiecen por "nombre"
    smartmule --purge "\.mkv$" # Encuentra todos los archivos con extensión .mkv
    ```

*   **Explorador Interactivo**: Si ejecutas el comando sin términos de búsqueda, SmartMule te mostrará la lista completa de tu biblioteca para que elijas qué eliminar.
    ```bash
    smartmule --purge
    ```

Ejemplo de uso:
![alt text](images/purge.png)

*   **Modo Destructivo (Limpieza Total)**: ⚠️⚠️ Borra absolutamente todos los archivos registrados en la base de datos de un solo golpe.
    ```bash
    smartmule --purge --all --no-preserve
    ```
    *Nota: Este comando requiere una confirmación de texto (escribir "BORRAR TODO") por seguridad.*

### 🔄 Re-procesamiento (Forzar identificación)
A veces, un archivo puede clasificarse erróneamente (ej: como "Video" genérico) porque el título estaba demasiado "sucio" o la llamada a la API falló. Si actualizas SmartMule o mejoras tus reglas de limpieza, puedes forzar que se vuelva a analizar desde cero:

*   **Comando**: `smartmule --reprocess "Nombre"`
*   Elimina el registro de la BBDD, borra la caché de la IA y elimina el archivo de la `Library`. El archivo original en `Incoming` permanece intacto. SmartMule lo detectará como un archivo nuevo y aplicará el pipeline de identificación completo de nuevo. 
    _(💡 Nota: Es recomendable ejecutar `smartmule restart` tras este comando para forzar el re-escaneo inmediato)._

### 🚀 Purga en un solo clic (Multiplataforma)
Para mayor comodidad, SmartMule despliega automáticamente herramientas de acceso directo dentro de tu carpeta de biblioteca (`LIBRARY_PATH`):

*   **Windows**: Usa **`Purga_Interactiva.bat`**.
*   **Linux**: Usa **`purga_interactiva.sh`**.

Solo tienes que ejecutar el archivo correspondiente para buscar y eliminar archivos sin tener que recordar comandos complejos:
![alt text](images/purge_script.png)

---

## Configuración en eMule (IMPORTANTE)

Para no perder visibilidad en la red ni dejar de ganar créditos tras la organización de tus archivos, sigue estos pasos:

1.  **Compartir Biblioteca**: Ve a eMule > **Opciones** > **Directorios** y marca la carpeta `Library` como directorio compartido (asegúrate de incluir sus subcarpetas).

![shared_folders](/images/shared_folders.png)

2.  **Privacidad**: No compartas la carpeta raíz de SmartMule, solo la carpeta `Library`. SmartMule guarda su base de datos en una carpeta oculta (`.data`) para que eMule no la indexe.

3.  **Mantener Créditos**: Tus créditos están asociados a tu *User Identification* (Hash), no a los nombres de los archivos. Al compartir la `Library` con los archivos ya limpios y renombrados, eMule reconocerá que tienes el mismo contenido (mismo Hash ED2K) y seguirás sumando prioridad de subida.

---

## 🧲 Configuración para Torrents (BitTorrent, uTorrent, qBittorrent)

SmartMule es totalmente compatible con gestores de descargas Torrent. Debido a que las redes Torrent detienen el *Seeding* (compartición de archivos) si cambias el archivo de sitio, SmartMule usa por defecto la creación de **Hardlinks** para los archivos de estas redes, asegurando que puedas seguir compartiendo (_Seeding_) los archivos sin interrupciones.

1.  **Ajustes de Extensiones [OBLIGATORIO]**: Para prevenir que SmartMule procese archivos sin terminar, es **imprescindible** que actives la opción de tu cliente de Torrent para agregar una extensión a las descargas incompletas. (Ej. *`Append .!ut to incomplete files`* en uTorrent o *`Añadir !qB a descargas incompletas`* en qBittorrent). Esto evita que el sistema intente indexar archivos parciales.

    ![alt text](images/torrent_conf.png)

2.  **Mismo Disco [RECOMENDADO]**: Para una eficiencia máxima de espacio, se recomienda que la carpeta `Incoming` y la `Library` estén en la misma partición. Esto permite usar _Hardlinks_ (no ocupa espacio adicional). 
    *   *Nota*: Si las carpetas están en discos distintos, SmartMule lo detectará y realizará una **copia automática** (_fallback_), pero esto duplicará el espacio usado.

3.  **Configuración de Modo [OPCIONAL]**: Por defecto SmartMule trabaja en modo `hardlink`. Puedes forzar que siempre use copias o movimientos modificando la variable `ORGANIZER_MODE` en tu archivo `.env`.

---

## 🧠 Búsqueda Semántica (Opcional)

SmartMule incorpora un motor de búsqueda híbrido que combina la precisión de palabras clave (Búsqueda léxica con FTS5) con una potente **Búsqueda Semántica Vectorial** gestionada por modelos de IA locales. 

Para instalar el motor semántico (aprox. ~300MB), ejecuta:
```bash
pip install -r requirements-semantic.txt
```

### Características

- **Multilingüe**: El modelo es capaz de entender el contexto sin importar el idioma (ej: puedes buscar "barcos que se hunden" en español y la IA encontrará "Titanic" aunque la película y sus metadatos estén en inglés).

- **Algoritmo de Fusión Híbrida (_Weighted RRF_)**: SmartMule fusiona de forma inteligente los resultados léxicos 📝 (palabras clave exactas mediante **BM25** con $k_1=1.2$ y $b=0.75$) y semánticos 🧠 (mediante _Bi-Encoder_) mediante un algoritmo avanzado (_Weighted Reciprocal Rank Fusion_).

- **Re-Ranking de Alta Precisión (_Cross-Encoder_)**: Los mejores 10 resultados pasan por una segunda capa de IA (_Cross-Encoder_) que analiza la relación real entre tu búsqueda y el contenido, marcando los aciertos más probables con la etiqueta **🧠✨ AI+**.

- **Refuerzo Bilingüe Automático**: Si un archivo carece de sinopsis en español o inglés tras consultar las APIs oficiales, la IA genera o traduce automáticamente la versión faltante. Esto garantiza que términos como "_Big Brother_" encuentren resultados aunque el archivo solo tenga metadatos en español ("_Gran Hermano_") y viceversa.

Ejemplo de uso:
```bash
smartmule --search "space" 
# Encontrará películas como Interstellar, Gravity, The Martian, etc., aunque la palabra "space" no aparezca en sus títulos.
```
![alt text](/images/rrf_scores.png)

### Configuración
Tras la primera instalación o si añades muchos archivos, puedes construir el índice vectorial de tu biblioteca masivamente con:
```bash
smartmule --build-index
```

**Nota**: Se han empleado los siguientes modelos de IA optimizados para ONNX (_Open Neural Network Exchange_):
- `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`: Generación de embeddings multilingües (_Bi-Encoder_) para la búsqueda semántica rápida.
- `Xenova/ms-marco-MiniLM-L-6-v2`: Refinamiento de resultados (_Cross-Encoder_) para el re-ranking de alta precisión (Etiqueta **AI+**).

---

## Testing

SmartMule cuenta con una suite de pruebas para garantizar la estabilidad. Puedes lanzarla con el comando:
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
