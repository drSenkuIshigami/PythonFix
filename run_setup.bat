@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

REM ============================================================================
REM  Finds a real installed Python on this PC, then runs offline_setup.py with it.
REM  Skips the Microsoft Store "python.exe" stub under WindowsApps.
REM ============================================================================

set "SCRIPT=%~dp0offline_setup.py"
set "LOG=%~dp0setup_log.txt"
set "PYTHON_EXE="
set "FOUND_DIR="

if not exist "%SCRIPT%" (
    echo ERROR: offline_setup.py not found next to this BAT file.
    echo Expected: "%SCRIPT%"
    exit /b 1
)

echo.
echo Searching for an installed Python...
echo.

REM --- 1) Official "py" launcher (most reliable on Windows) ---
where py >nul 2>&1
if not errorlevel 1 (
    for /f "delims=" %%I in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do (
        call :IsRealPython "%%I"
        if not defined PYTHON_EXE if "!_REAL!"=="1" (
            set "PYTHON_EXE=%%I"
            echo Found via py launcher: %%I
        )
    )
)

REM --- 2) python on PATH, skipping Windows Store aliases ---
if not defined PYTHON_EXE (
    for /f "delims=" %%I in ('where python 2^>nul') do (
        echo %%I | findstr /i /c:"WindowsApps" >nul
        if errorlevel 1 (
            call :IsRealPython "%%I"
            if not defined PYTHON_EXE if "!_REAL!"=="1" (
                set "PYTHON_EXE=%%I"
                echo Found on PATH: %%I
            )
        )
    )
)

REM --- 3) python3 on PATH ---
if not defined PYTHON_EXE (
    for /f "delims=" %%I in ('where python3 2^>nul') do (
        echo %%I | findstr /i /c:"WindowsApps" >nul
        if errorlevel 1 (
            call :IsRealPython "%%I"
            if not defined PYTHON_EXE if "!_REAL!"=="1" (
                set "PYTHON_EXE=%%I"
                echo Found python3 on PATH: %%I
            )
        )
    )
)

REM --- 4) Windows registry (64-bit, 32-bit, HKLM, HKCU) ---
if not defined PYTHON_EXE (
    for %%R in (HKLM HKCU) do (
        for %%N in ("SOFTWARE\Python\PythonCore" "SOFTWARE\WOW6432Node\Python\PythonCore" "SOFTWARE\Python\ContinuumAnalytics") do (
            for /f "delims=" %%K in ('reg query "%%R\%%~N" 2^>nul') do (
                for /f "tokens=2,*" %%A in ('reg query "%%K\InstallPath" /ve 2^>nul') do (
                    if exist "%%Bpython.exe" (
                        call :IsRealPython "%%Bpython.exe"
                        if not defined PYTHON_EXE if "!_REAL!"=="1" (
                            set "PYTHON_EXE=%%Bpython.exe"
                            echo Found via registry: %%Bpython.exe
                        )
                    )
                )
                for /f "tokens=2,*" %%A in ('reg query "%%K\InstallPath" /v ExecutablePath 2^>nul') do (
                    if exist "%%B" (
                        call :IsRealPython "%%B"
                        if not defined PYTHON_EXE if "!_REAL!"=="1" (
                            set "PYTHON_EXE=%%B"
                            echo Found via registry ExecutablePath: %%B
                        )
                    )
                )
            )
        )
    )
)

REM --- 5) Common install folders ---
if not defined PYTHON_EXE (
    for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python*") do call :TryDir "%%D"
)
if not defined PYTHON_EXE (
    for /d %%D in ("%LOCALAPPDATA%\Python\pythoncore-*") do call :TryDir "%%D"
)
if not defined PYTHON_EXE (
    for /d %%D in ("%ProgramFiles%\Python*") do call :TryDir "%%D"
)
if not defined PYTHON_EXE (
    for /d %%D in ("%ProgramFiles(x86)%\Python*") do call :TryDir "%%D"
)
if not defined PYTHON_EXE (
    for /d %%D in ("C:\Python*") do call :TryDir "%%D"
)
if not defined PYTHON_EXE call :TryDir "%USERPROFILE%\anaconda3"
if not defined PYTHON_EXE call :TryDir "%USERPROFILE%\miniconda3"
if not defined PYTHON_EXE call :TryDir "%LOCALAPPDATA%\anaconda3"
if not defined PYTHON_EXE call :TryDir "%LOCALAPPDATA%\miniconda3"
if not defined PYTHON_EXE call :TryDir "%ProgramFiles%\PyManager"
if not defined PYTHON_EXE call :TryFile "C:\Program Files\PyManager\python.exe"

if not defined PYTHON_EXE (
    echo.
    echo ERROR: No working Python interpreter was found on this PC.
    echo Install Python 3.8 or later from https://www.python.org/downloads/
    echo During setup, enable "Add python.exe to PATH" and "py launcher".
    echo.
    echo Search log will be written to:
    echo   %LOG%
    echo [%date% %time%] ERROR: No working Python found.>> "%LOG%"
    exit /b 1
)

for %%P in ("%PYTHON_EXE%") do set "FOUND_DIR=%%~dpP"
echo.
echo Using Python executable: %PYTHON_EXE%
echo Install directory:       %FOUND_DIR%
echo.
echo [%date% %time%] BAT selected: %PYTHON_EXE%>> "%LOG%"

"%PYTHON_EXE%" "%SCRIPT%" %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
    echo.
    echo Setup failed with exit code %RC%. See setup_log.txt for details.
    exit /b %RC%
)
echo.
echo Setup finished successfully.
echo.
echo IMPORTANT: pip will not work in terminals that were already open.
echo Close this window and open a NEW Command Prompt or PowerShell, then run:
echo   pip --version
echo   python --version
echo.
echo In an already-open PowerShell:
echo   . .\enable_pip.ps1
echo   pip --version
echo.
exit /b 0

:TryDir
if defined PYTHON_EXE goto :eof
if exist "%~1\python.exe" call :TryFile "%~1\python.exe"
goto :eof

:TryFile
if defined PYTHON_EXE goto :eof
if not exist "%~1" goto :eof
call :IsRealPython "%~1"
if "!_REAL!"=="1" (
    set "PYTHON_EXE=%~1"
    echo Found in common path: %~1
)
goto :eof

:IsRealPython
set "_REAL=0"
if not exist "%~1" goto :eof
echo %~1 | findstr /i /c:"WindowsApps" >nul
if not errorlevel 1 goto :eof
"%~1" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>&1
if errorlevel 1 goto :eof
set "_REAL=1"
goto :eof
