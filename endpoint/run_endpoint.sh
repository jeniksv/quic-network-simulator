#!/bin/bash

# Set up the routing needed for the simulation.
/setup.sh
mkdir -p /logs

if [ "$ROLE" == "client" ]; then
    # Wait for the simulator to start up.
    /wait-for-it.sh sim:57832 -s -t 30

    h2load --output-file=/logs/h2load.json ${CLIENT_PARAMS}

elif [ "$ROLE" == "server" ]; then
    NGINX_BIN=/opt/nginx-bin/nginx
    "$NGINX_BIN" -e stderr ${SERVER_PARAMS}
fi
