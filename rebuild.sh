#!/bin/bash

cd ../web-client/ || exit 1
sudo -H -u pi bash -c 'npm run build'
