#!/bin/bash

# SmartMule Background Launcher (Linux Version)
# Lanza el motor de SmartMule en segundo plano.

# Navegamos al directorio del script
cd "$(dirname "$0")" || exit

# Verificamos si ya está corriendo
if [ -f "smartmule.pid" ]; then

    PID=$(cat smartmule.pid) # Leemos el PID del archivo

    if ps -p $PID > /dev/null; then
        echo "⚠️ SmartMule ya está corriendo (PID: $PID)."
        exit 1
    fi
    
fi

# Lanzamos en segundo plano utilizando el python del entorno virtual
# - nohup: Evita que el proceso muera al cerrar la sesión
# - & : Lo manda al background
# - > /dev/null 2>&1 : Silencia la salida (ya que SmartMule tiene sus propios logs)
nohup ./venv/bin/python3 main.py start > /dev/null 2>&1 &

echo "[i] SmartMule lanzado en segundo plano."
echo "[i] Puedes ver el estado en 'smartmule.log' o usar 'python3 main.py stop' para detenerlo."
