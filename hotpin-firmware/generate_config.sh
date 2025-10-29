#!/bin/bash
# generate_config.sh - Generate firmware configuration from .env

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo "Error: .env file not found"
    echo "Please copy .env.example to .env and configure your settings"
    exit 1
fi

# Run the configuration generator
python tools/config_generator.py

# Check if generation was successful
if [ $? -eq 0 ]; then
    echo "Configuration files generated successfully!"
    echo "Run 'idf.py build' to build the firmware with new configuration"
else
    echo "Error generating configuration files"
    exit 1
fi