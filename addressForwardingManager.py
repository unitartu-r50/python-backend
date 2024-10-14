import os
import json
import time
import logging
import requests

from threading import Thread

from config import ADDRESS_RECEIVER, SERVER_IDENTIFIER


class AddressForwardingWorker(Thread):
    def __init__(self, caller, timer):
        super().__init__()
        self.caller = caller
        self.timer = timer

    def run(self):
        counter = 0
        while self.caller.flag:
            if counter >= self.timer:
                server_ip = os.popen('ip addr show wlan0 | grep "\<inet\>" | awk \'{ print $2 }\' | awk -F "/" \'{ print $1 }\'').read().strip()
                try:
                    requests.post(ADDRESS_RECEIVER, json=json.dumps({'ip': server_ip, 'id': SERVER_IDENTIFIER}))
                except ConnectionError as err:
                    logging.error(err)
                counter = 0
            else:
                counter += 1
            time.sleep(1)


class AddressForwarder:
    def __init__(self, timer):
        self.worker = None
        self.flag = False
        if SERVER_IDENTIFIER:
            self._start(timer)

    def _start(self, timer):
        self.flag = True
        self.worker = AddressForwardingWorker(self, timer)
        self.worker.start()

    def stop(self):
        self.flag = False
        if SERVER_IDENTIFIER:
            self.worker.join()
