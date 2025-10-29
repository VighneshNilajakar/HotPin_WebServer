@echo off
REM generate_config.bat - Generate firmware configuration from .env

REM Check if .env file exists
if not exist ".env" (
    echo Error: .env file not found
    echo Please copy .env.example to .env and configure your settings
    exit /b 1
)

REM Run the configuration generator
python tools\config_generator.py

REM Check if generation was successful
if %ERRORLEVEL% EQU 0 (
    echo Configuration files generated successfully!
    echo Run 'idf.py build' to build the firmware with new configuration
) else (
    echo Error generating configuration files
    exit /b 1
)