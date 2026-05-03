[ 🇺🇸 English ](README_EN.md) | [ 🇪🇸 Castellano ](README.md)

# SmartMule 🫏

### The Intelligent Librarian for the P2P Ecosystem

**SmartMule** is an automated organization and security service designed to transform the chaos of P2P downloads (eMule, aMule, etc.) into a perfectly structured library. It uses file system monitoring, cryptographic hashing (ED2K), and Artificial Intelligence to classify, clean, and protect your computer from disguised threats.

![SmartMule](/images/SmartMule_Logo_Oficial.png)

![Terminal](/images/terminal.png)

![pop_up](/images/pop_up.png)

---

## Why?

By default, eMule places all completed downloads into a single `Incoming` folder. Over time, this directory becomes a chaotic mix of movies, software, music, and archives with cryptic "scene" names. 

**SmartMule** solves this by automatically identifying, cleaning, and moving each file into its proper thematic category, keeping your library organized without manual effort.

---

## Key Features

*   **Active Surveillance (Watchdog)**: Instantly detects new files in your `Incoming` folder.

*   **Dual-Layer Verification**: Identifies files by name (AI) and by content (ED2K Hash / Fingerprint). 

*   **Folder Grouping Support**: SmartMule detects if a download is a folder (e.g., a movie with subtitles). It identifies the main file for hashing and metadata but moves and renames the **entire folder** as a single functional unit.

*   **Semantic Antimalware (Elite Triage)**: Deep file inspection without extraction using **VirusTotal**. SmartMule trusts no one:
    -   **Macro Analysis**: Detects Office documents with macros (`.xlsm`, `.docm`, etc.) and legacy formats (`.doc`, `.xls`), treating them as executables for preventive triage.
    -   **PDF Surveillance**: Automatic scanning of PDF files for potential malicious scripts.
    -   **Archive Inspection**: The `ArchiveInspector` analyzes `.zip`, `.rar`, and `.7z` files searching for inconsistencies (e.g., an `.exe` disguised as a movie) and displaying suspicious content in the logs.
    -   **Critical Scores**: If a file has more than 5 detections on VT (prioritizing TOP engines like Microsoft or Kaspersky), it automatically moves it to a **Review** folder.

*   **Intelligent Tie-Breaking**: Uses a heuristic scoring system based on release year and technical duration (FFmpeg) to distinguish between movies with the same name with surgical precision (e.g., Solaris 1972 vs. Solaris 2002).

*   **Automated Triage**: 
    -   `MALICIOUS`: Automatic destructive deletion.
    -   `SUSPICIOUS`: Quarantine for manual review.
    -   `SAFE`: Automated thematic organization and renaming.
    ![alt text](/images/suspicious.png)
    ![alt text](/images/antimalware.png)

*   **Intelligent Search (FTS5)**: Integrated global search engine with support for filters. Locate any file by title, type, score, or resolution instantly.
    ```bash
    python main.py --search "Matrix"               # Simple search
    python main.py --search "type:movie score>8"  # Filtered search
    ```

*   **Privacy**: Compatible with local models (LM Studio) to process names without uploading them to the cloud.

*  **Ultra-low resource usage**: SmartMule is designed to run in the background without interfering with normal PC usage. To achieve this, it sets minimal I/O (`IOPRIO_VERYLOW`) and CPU (`IDLE_PRIORITY_CLASS`) priorities, ensuring the OS only allocates resources to the process when no other applications are demanding them.

---

## 📂 Organization Strategies (`ORGANIZER_MODE`)

SmartMule allows you to choose how files are physically managed via the `ORGANIZER_MODE` variable in the `.env` file:

| Mode | Supports _Seeding_ (eMule) | Description |
| :--- | :--- | :--- |
| **`hardlink`** (_Default_) | ✅ **Yes** | Creates a physical link. The file appears in both `Incoming` and `Library` but **only consumes space once**. Perfect for continuous seeding while keeping your library organized. |
| **`move`** | ❌ **No** | Moves the file from one folder to another. It is instantaneous, but eMule will stop sharing it as it won't find it in the original path. |
| **`copy`** | ✅ **Yes** | Duplicates the file. It is the slowest mode and **consumes double the space**, but it is the only one that works across different physical hard drives. |

> [!TIP]
> Always use **`hardlink`** if `Incoming` and `Library` are on the same disk drive.

---

## System Requirements

### 1. Python Dependencies

Install the necessary libraries with:
```bash
pip install -r requirements.txt
```

### 2. System Tools (MANDATORY)

For file analysis and movie tie-breaking, SmartMule requires:

*   **FFmpeg (ffprobe)**: Needed to extract video resolution and technical metadata.
    -   **Windows**: Download from [ffmpeg.org](https://ffmpeg.org/download.html), extract the `.zip`, and add the `bin` folder to your system `PATH`.
    -   **Linux**: `sudo apt install ffmpeg`

*   **7-Zip / Patool**: Needed to inspect compressed files.
    -   **Windows**: Install [7-Zip](https://www.7-zip.org/) and ensure it is in the `PATH`.
    -   **Linux**: `sudo apt install p7zip-full`

---

## How it Works (Data Pipeline)

1.  **Monitoring**: The `Watcher` detects the file and starts an I/O unlock wait.

2.  **Smart Cache**: A fast "Fingerprint" is calculated. If the file already exists and the `mtime` (modification time) has not changed, metadata is reused to save API calls.

3.  **Semantic Analysis**: If it's a container, the `ArchiveInspector` looks for threats before the user opens it.

4.  **AI Layer (LLM)**: Cleans the "dirty" scene filename and detects the media type (Movies, Music, Books, Software, etc.).

5.  **Enrichment (API)**: Queries **TMDB** or **OpenLibrary** using the year and technical metadata for a precise match.

6.  **Organization**: The `LibraryOrganizer` moves and renames the file to its final destination (e.g., `/Library/Movies_and_Series/The Matrix (1999).mkv`).

---

## Daemon (Background Execution)

SmartMule is designed to run once and remain monitoring permanently in a completely invisible manner.

*   **Start (Invisible Mode)**: 

    - **Windows**: Double-click the `smartmule_launcher.vbs` file. I recommend placing a shortcut in your *Startup* folder (`shell:startup`).
    
    - **Linux**: Run `./smartmule_launcher.sh`. This script uses `nohup` to keep the process alive after closing the terminal.

*   **Stop**: Run `python3 main.py stop`. SmartMule will detect the hidden process and close it cleanly.

    ![stop_pid](/images/stop_pid.png)

*   **Auditing**: All silent activity will be recorded in the `smartmule.log` file. You can quickly see the last lines with:
    ```bash
    python main.py --log      # Shows the last 30 lines (default)
    python main.py --log 100  # Shows the last 100 lines
    ```
    Or follow it in real-time on Windows:
    ```powershell
    Get-Content smartmule.log -Wait -Encoding UTF8
    ```
    ![alt text](/images/logs.png)

*   **Inventory and Statistics**: To quickly see which files are registered in the library, the breakdown by category, and the total storage used, use the `--stats` flag. To check system health and dependencies, use `--status`. To check your active paths and APIs, use `--config`:
    ```bash
    python main.py --stats     # View statistics
    python main.py --status    # Check system health
    python main.py --config    # View active configuration
    ```
    ![alt text](/images/inventory.png)

*   **Intelligent Search**: To quickly locate any file by its official title or original name, use the `--search` flag. The FTS5 engine allows for fast and accent-insensitive searches:
    ```bash
    python main.py --search "Matrix"
    ```

### Linux Alias

To avoid typing the virtual environment path every time you want to use the CLI, you can create an alias in your terminal:

1.  Open your configuration: `nano ~/.bashrc`
2.  Paste this line at the end (adjust the path if necessary):
    ```bash
    alias smartmule='/home/user/SmartMule/venv/bin/python3 /home/user/SmartMule/main.py'
    ```
3.  Reload the configuration: `source ~/.bashrc`

**Windows:**
1.  Create a file named `smartmule.bat` in a folder that is in your `PATH` (e.g., `C:\Windows`).
2.  Paste this content inside (adjust the paths to your installation):
    ```batch
    @echo off
    C:\SmartMule\venv\Scripts\python.exe C:\SmartMule\main.py %*
    ```

3.  Done! Now you can use the simplified commands from any terminal.

### Available Commands (via Alias)

Once the alias is configured, you will be able to use from any terminal:
*   `smartmule start` (Starts the SmartMule engine)
*   `smartmule stop` (Stops the service)
*   `smartmule restart` (Restarts the service)
*   `smartmule --stats` (View library inventory and storage statistics)
*   `smartmule --status` (View system health and dependencies)
*   `smartmule --config` (View active paths and API configuration)
*   `smartmule --purge "Name"` (Delete files)
*   `smartmule --reprocess "Name"` (Force file re-analysis)
*   `smartmule --debug` (Start with detailed AI logs)
*   `smartmule --pid`  (Shows the active process PID)
*   `smartmule --search "Name"` (Search files)

---

## Maintenance and Purge (_Smart Deletion_)

_When using `hardlink` mode (default), deleting a file from your library does not physically delete it from the disk if it still exists in the `Incoming` folder (and vice versa). This is necessary for continuous seeding as a good eMule peer but can be tedious to clean up_. 

To facilitate complete cleanup, SmartMule includes a purge command:

*   **Selective Purge**: Search for files by name, _Wildcards_, or _Regex_.
    ```bash
    python main.py --purge "name*"     # Finds files starting with "name"
    python main.py --purge ".*\.mkv$"  # Finds all .mkv files
    ```

*   **Interactive Explorer**: If you run the command without search terms, SmartMule will display the full list of your library for you to choose what to delete.
    ```bash
    python main.py --purge
    ```

Use example:
![alt text](images/purge.png)

*   **Destructive Mode (Total Wipeout)**: ⚠️⚠️ Deletes absolutely every file registered in the database in one go.
    ```bash
    python main.py --purge --all --no-preserve
    ```
    *Note: This command requires a text confirmation ("BORRAR TODO") for safety.*

### 🔄 Re-processing (Force Identification)
Sometimes, a file might be incorrectly classified (e.g., as a generic "Video") because the title was too noisy or the API failed. If you update SmartMule or improve your cleaning rules, you can force it to be analyzed again from scratch:

*   **Command**: `smartmule --reprocess "Name"`
*   Deletes the database record, clears the AI cache, and removes the file from the `Library`. The original file in `Incoming` remains intact. SmartMule will detect it as a new file and apply the full identification pipeline again.
    _(💡 Note: It is recommended to run `smartmule restart` after this command to force an immediate re-scan)._

### 🚀 One-Click Purge (Cross-platform)
For extra convenience, SmartMule automatically deploys shortcut tools inside your library folder (`LIBRARY_PATH`):

*   **Windows**: Use **`Purga_Interactiva.bat`**.
*   **Linux**: Use **`purga_interactiva.sh`**.

Just run the appropriate file to search and delete files without having to open the terminal or remember CLI commands:
![alt text](images/purge_script.png)

---

## eMule Configuration (IMPORTANT)

To maintain visibility on the network and continue earning credits after organizing your files, follow these steps:

1.  **Share Library**: Go to eMule > **Options** > **Directories** and mark the `Library` folder as a shared directory (ensure you include its subfolders).

![shared_folders](/images/shared_folders.png)

2.  **Privacy**: Do not share the SmartMule root folder, only the `Library` folder. SmartMule stores its database in a hidden folder (`.data`) so that eMule does not index it.

3.  **Maintain Credits**: Your credits are associated with your *User Identification* (Hash), not file names. By sharing the `Library` with cleaned and renamed files, eMule will recognize that you have the same content (same ED2K Hash) and you will continue to accumulate upload priority.

4.  **Update**: After starting SmartMule for the first time, go to eMule's **Shared Files** tab and click the **Reload** button so that the new names appear on the network instantly.

---

## Torrent Configuration (BitTorrent, uTorrent, qBittorrent)

SmartMule is fully compatible with Torrent download managers. Because Torrent networks stop *seeding* (sharing) if you change the file's location, SmartMule defaults to creating **Hardlinks** for files coming from these networks, ensuring that you can continue sharing (_Seeding_) the files without interruptions.

1.  **Extensions Settings (Crucial)**: To prevent SmartMule from processing unfinished files, it is mandatory that you enable the option in your Torrent client to add an extension to incomplete downloads. (e.g. *`Append .!ut to incomplete files`* in uTorrent or *`Append .!qB to incomplete files`* in qBittorrent).

    ![alt text](images/torrent_conf.png)

2.  **Same Drive**: _Hardlinks_ require that both the `Incoming` folder and the `Library` folder reside on the same system partition or hard drive.

3.  **Mode configuration**: You can alter the behavior by modifying the `ORGANIZER_MODE` variable in your `.env` (`hardlink` by default, but you can choose `copy` or `move`).

---

## Testing

Full test suite to ensure stability:
```bash
pytest -v --tb=short
```

---

## 🚀 Parallel Hashing Engine (Optimization)

SmartMule includes a high-performance ED2K hashing engine designed not to saturate your system, which reduces processing time exponentially:

-   **Hybrid Architecture**: Sequential disk reading (`IOPRIO_VERYLOW`) combined with parallel chunk hashing via multi-threading.

-   **RAM Control**: _Backpressure_ mechanism that ensures a constant and minimal memory footprint (~55MB), whether processing a 1GB file or a 200GB ISO.

-   **Courtesy with the OS**: Automatically sets CPU priority to `IDLE` and uses only 50% of available cores, making the background process virtually invisible.
