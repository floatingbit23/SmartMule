# SmartMule 🧠

### El Bibliotecario Inteligente para el Ecosistema P2P

**SmartMule** es un servicio automatizado de organización y seguridad diseñado para transformar el caos de las descargas P2P (eMule, aMule, etc.) en una biblioteca perfectamente estructurada. Utiliza vigilancia del sistema de archivos, hashing criptográfico (ED2K) e Inteligencia Artificial para clasificar, limpiar y proteger tu equipo de amenazas camufladas.

---

## 🚀 Características Principales

*   **Vigilancia Activa (Watchdog)**: Detecta archivos nuevos en tu carpeta `Incoming` al instante.

*   **Doble Capa de Verificación**: Identifica archivos por su nombre (IA) y por su contenido (Hash ED2K / Fingerprint). 

*   **Antimalware Semántico**: Inspección profunda de archivos comprimidos (`.zip`, `.rar`, `.7z`) sin extracción, usando VirusTotal, para detectar ejecutables ocultos o inconsistencias.

*   **Desempate Inteligente (Tie-Breaking)**: Usa la duración real de los videos para distinguir entre películas homónimas (ej: Solaris 1972 vs 2002).
*   **Triaje Automático**: 
    -   `MALICIOUS`: Borrado automático destructivo.
    -   `SUSPICIOUS`: Cuarentena para revisión manual.
    -   `SAFE`: Organización temática automatizada.
*   **Privacidad**: Compatible con modelos locales (LM Studio) para procesar nombres sin subirlos a la nube.

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

## 🏗️ Cómo funciona (El Pipeline de Datos)

1.  **Monitorización**: El `Watcher` detecta el archivo e inicia una espera de desbloqueo (_I/O unlock_).

2.  **Caché Inteligente**: Se calcula una "Fingerprint" rápida. Si el archivo ya existe y el `mtime` (_modification time_) no ha cambiado, se reutilizan los metadatos para ahorrar APIs.

3.  **Análisis Semántico**: Si es un contenedor, el `ArchiveInspector` busca amenazas antes de que el usuario lo abra.

4.  **Capa IA (LLM)**: Limpia el nombre "sucio" de la _Scene_ y detecta el tipo de medio (Cine, Música, Libros, Software, etc.).

5.  **Enriquecimiento (API)**: Consulta **TMDB** u **OpenLibrary** usando el año y la duración para un emparejamiento perfecto.

6.  **Organización**: El `LibraryOrganizer` mueve el archivo a su destino final (ej: `/Library/Movies_and_Series/Matrix (1999).mkv`).

---

## 🧪 Testing

SmartMule cuenta con una suite de pruebas para garantizar la estabilidad:
```bash
pytest -v --tb=short
```

---
