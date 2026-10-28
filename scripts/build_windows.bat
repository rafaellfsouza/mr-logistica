@echo off
REM ---------------------------------------------------------------------------
REM Gera o executavel de arquivo unico do MR Logistica no Windows.
REM Resultado: dist\MRLogistica.exe  (copie para qualquer PC e de dois cliques)
REM ---------------------------------------------------------------------------
cd /d %~dp0..
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python -m PyInstaller mrlogistica.spec --noconfirm --clean
echo.
echo Pronto! Executavel em: %cd%\dist\MRLogistica.exe
pause
