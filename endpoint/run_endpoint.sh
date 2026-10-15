#!/bin/bash

# Set up the routing needed for the simulation.
/setup.sh

if [ "$ROLE" == "client" ]; then
    # Wait for the simulator to start up.
    /wait-for-it.sh sim:57832 -s -t 30

    h2load --output-file=/logs/h2load.json ${CLIENT_PARAMS}

elif [ "$ROLE" == "server" ]; then
    /usr/local/nginx/sbin/nginx -e stderr ${SERVER_PARAMS}
fi
