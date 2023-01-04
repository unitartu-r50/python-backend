import requests

from config import CLOUDFRONT_SERVER, START_RECORD_ENDPOINT, ACTION_ENDPOINT
from recorder import Recorder


class RecordingForwardingManager:
    def __init__(self):
        self.recording_connection = None
        self.recording_paused = False
        self.recorder = Recorder(stream=True)

        self.session_name = ""

    def update_recordings_size(self):
        return 0

    def record_audio(self):
        if self.session_name:
            self.recorder.record(filename=self.session_name)

    def save_audio(self):
        self.recorder.stop_recording()

    def record_command(self, command_id):
        r = requests.get("https://" + CLOUDFRONT_SERVER + ACTION_ENDPOINT, params={"action_id": command_id,
                                                                                   "session_name": self.session_name})
        print(r.json())

    def start_recording(self, connection_id):
        xd = requests.get("https://" + CLOUDFRONT_SERVER + START_RECORD_ENDPOINT).json()
        print(xd)
        self.session_name = xd['session_name']
        self.recording_connection = connection_id
        self.recording_paused = False
        self.record_audio()
        return {"message": "Recording started..."}

    def pause_recording(self, connection):
        if connection == self.recording_connection:
            self.save_audio()
            self.recording_paused = True
        return {"message": "Recording paused."}

    def resume_recording(self, connection):
        if connection == self.recording_connection:
            self.recording_paused = False
            self.record_audio()
        return {"message": "Recording resumed..."}

    def stop_recording(self, connection):
        if connection == self.recording_connection:
            self.save_audio()
            self.recording_paused = None
            self.recording_connection = None
        return {"message": "Recording finished!"}
