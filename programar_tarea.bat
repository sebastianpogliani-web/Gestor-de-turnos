@echo off
setlocal

set TASK_NAME=MonitorVisitas
set SCRIPT=%~dp0actualizar.py
set START_TIME=08:00

echo ============================================================
echo  Programador de tarea: %TASK_NAME%
echo  Script : %SCRIPT%
echo  Horario: cada 4 horas desde las %START_TIME%
echo ============================================================
echo.

:: Buscar python en PATH
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python no encontrado en PATH.
    echo Instala Python y asegurate de que este en el PATH del sistema.
    pause
    exit /b 1
)

for /f "delims=" %%i in ('where python') do set PYTHON=%%i
echo Python encontrado: %PYTHON%
echo.

:: Eliminar tarea previa si existe (silencioso)
schtasks /delete /tn "%TASK_NAME%" /f >nul 2>&1

:: Crear tarea: cada 4 horas, usuario actual, solo si hay sesion iniciada
schtasks /create ^
  /tn "%TASK_NAME%" ^
  /tr "\"%PYTHON%\" \"%SCRIPT%\"" ^
  /sc hourly ^
  /mo 4 ^
  /st %START_TIME% ^
  /it ^
  /f

if %errorlevel% equ 0 (
    echo.
    echo [OK] Tarea "%TASK_NAME%" creada correctamente.
    echo      Se ejecutara cada 4 horas a partir de las %START_TIME%.
    echo      Para verla: Programador de tareas ^> Biblioteca
    echo      Para eliminarla: schtasks /delete /tn "%TASK_NAME%" /f
) else (
    echo.
    echo [ERROR] No se pudo crear la tarea.
    echo Si ves un error de permisos, ejecuta este .bat como Administrador
    echo haciendo clic derecho ^> "Ejecutar como administrador".
)

echo.
pause
endlocal
