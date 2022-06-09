#!/bin/bash

cd ../web-client/ || exit 1
git pull --ff-only origin master
sudo -H -u pi bash -c 'npm run build'
cd ../python-backend || exit 1
git pull --ff-only origin master
source fastapi_env/bin/activate
pip install -r requirements.txt
deactivate
sudo service pepper-backend restart;
