@echo off
:: SmartMule Interactive Purge Launcher
:: Diseñado para facilitar la limpieza sin usar la terminal manualmente.

title SmartMule - Purga de Archivos
color 0B
cls

echo ===================================================
echo           SmartMule: Purga Inteligente
echo ===================================================
echo.
echo [i] Puedes usar:
echo     - Un nombre parcial (ej: Matrix)
echo     - Un comodin (ej: N*)
echo     - Una extension (ej: *.mkv)
echo     - Nada ('Enter' para listar toda la biblioteca)
echo.
set /p query="> Introduce el patron de busqueda: "

echo.
echo [PROCESANDO] Ejecutando purga para: "%query%"
echo.

:: Navegamos a la carpeta del proyecto (Inyectado automaticamente por SmartMule)
cd /d "TEMPLATE_PROJECT_PATH"

:: Ejecutamos el comando de SmartMule
python main.py --purge "%query%"

echo.
echo ===================================================
echo   Tarea finalizada. Presiona cualquier tecla para salir...
echo ===================================================
pause > nul
