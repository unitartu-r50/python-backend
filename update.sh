#!/bin/bash

cd ../web-client/ || exit 1
git pull origin master
npm run build
cd ../python-backend || exit 1
git pull origin master
source fastapi_env/bin/activate
pip install -r requirements.txt
deactivate
sudo service pepper-backend restart;
