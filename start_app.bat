@echo off
setlocal

set "ROOT=%~dp0"
cd /d "%ROOT%"

set "VENV_DIR=.venv"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
    echo Creating Python environment...
    python -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo Failed to create virtual environment.
        echo Make sure Python is installed and added to PATH.
        pause
        exit /b 1
    )
    echo Installing required packages...
    "%PYTHON_EXE%" -m pip install --upgrade pip
    "%PYTHON_EXE%" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo Installation failed. Please check your internet connection and try again.
        pause
        exit /b 1
    )
)

echo Starting the app...
start "Road Safety App" "%PYTHON_EXE%" -m streamlit run app.py --server.headless false

if errorlevel 1 (
    echo Failed to start the app.
    pause
    exit /b 1
)

echo.
echo The app is starting in your browser.
echo Keep this window open while you use the app.
echo Press Ctrl+C to stop it.
pause
