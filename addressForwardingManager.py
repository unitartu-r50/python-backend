import os
import json
import time

import requests

from threading import Thread


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
                requests.post("https://deltabot.tartunlp.ai/pepper/set", json=json.dumps({'ip': server_ip}))
                counter = 0
            else:
                counter += 1
            time.sleep(1)


class AddressForwarder:
    def __init__(self, timer):
        self.worker = None
        self.flag = False
        # self._start(timer)

    def _start(self, timer):
        self.flag = True
        self.worker = AddressForwardingWorker(self, timer)
        self.worker.start()

    def stop(self):
        self.flag = False
        # self.worker.join()
