@echo off
rem Arrastra imagenes (o una carpeta) encima de este archivo para convertirlas en clips 3D.
rem Tambien se puede usar desde la terminal:  EFECTO3D.bat foto.jpg --formato horizontal
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Primera vez: preparando Python y dependencias...
  python -m venv .venv || (echo No encuentro Python. Instalalo desde python.org y marca "Add to PATH". & pause & exit /b 1)
  ".venv\Scripts\python.exe" -m pip install -q --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt || (echo Fallo la instalacion. & pause & exit /b 1)
)
if "%~1"=="" (
  echo Arrastra imagenes o una carpeta encima de EFECTO3D.bat
  ".venv\Scripts\python.exe" efecto3d.py --help
  pause
  exit /b 0
)
".venv\Scripts\python.exe" efecto3d.py %*
if errorlevel 1 (echo. & echo Algo fallo: revisa el mensaje de arriba.) else (echo. & echo Terminado. Los videos estan en la carpeta salida_3d junto a tus imagenes.)
pause
