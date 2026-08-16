#!/bin/bash
# Simple script to run buffarr locally with a .env file.
# Pass --config path/to/config.toml instead to use a config file (see
# config.example.toml); .env is then optional.

if [ -f .env ]; then
    export $(cat .env | sed 's/#.*//g' | grep -v '^$' | xargs)
elif [ "$#" -eq 0 ]; then
    echo "Error: .env file not found (or pass --config path/to/config.toml)"
    exit 1
fi

export PYTHONPATH=src
python3 src/main.py "$@"
