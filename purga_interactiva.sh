#!/bin/bash

# SmartMule Interactive Purge Launcher (Linux Version)
# Script interactivo para la purga de archivos en entornos Unix/Linux.

# Colores ANSI
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

clear

echo -e "${CYAN}===================================================${NC}"
echo -e "          ${CYAN}SmartMule: Purga Inteligente${NC}"
echo -e "${CYAN}===================================================${NC}"
echo ""
echo -e "[i] Puedes usar:"
echo -e "    - Un nombre parcial (ej: Matrix)"
echo -e "    - Un comodín (ej: N*)"
echo -e "    - Una extensión (ej: *.mkv)"
echo -e "    - Nada (Pulsa 'Enter' para listar todo)"
echo ""

# Capturar entrada del usuario
read -p "> Introduce el patrón de búsqueda: " query

echo ""
echo -e "${YELLOW}[PROCESANDO]${NC} Ejecutando purga para: \"${query}\""
echo ""

# Navegamos a la carpeta del proyecto de forma dinámica
cd "$(dirname "$0")" || exit

# Ejecutamos el comando de SmartMule usando el python del entorno virtual
./venv/bin/python3 main.py --purge "$query"

echo ""
echo -e "${CYAN}===================================================${NC}"
echo -e "   Tarea finalizada. Pulsa cualquier tecla para salir..."
echo -e "${CYAN}===================================================${NC}"

# Pausa final (espera un carácter)
read -n 1 -s
