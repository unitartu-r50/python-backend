import os.path
import subprocess

from datetime import datetime

from config import RECORDING_SIZE_LIMIT
from recorder import Recorder


class RecordingManager:
    def __init__(self):
        # In GB
        self.storage_fill = 0
        self.rec_cap = RECORDING_SIZE_LIMIT

        self.recording_connection = None
        self.recording_paused = False
        self.recording_file = None
        self.recorder = Recorder()

        self.update_recordings_size()

        for subdir in ['audio', 'sessions']:
            if not os.path.isdir(os.path.join('data', 'recordings', subdir)):
                os.mkdir(os.path.join('data', 'recordings', subdir))

    def update_recordings_size(self):
        self.storage_fill = round(int(subprocess.check_output(['du',
                                                               '-s',
                                                               '--si',
                                                               '--block-size=MB',
                                                               os.path.join('data', 'recordings')]).decode('utf-8').split("MB")[0])/1000/self.rec_cap, 2)
        return self.storage_fill

    def record_audio(self):
        self.recorder.record()

    def save_audio(self):
        with open(self.recording_file, "a") as f:
            f.write(f"AUDIO,{self.recorder.stop_recording()}\n")

    def record_command(self, command_id):
        with open(self.recording_file, "a") as f:
            f.write(f"CMD,{command_id}\n")

    def start_recording(self, connection_id):
        # Since the audio is recorded by a physical Raspberry,
        # each server (Raspberry) can perform up to one recording at a time.
        if self.recording_connection is not None:
            return {"error": f"Another client ({connection_id}) is already recording!"}
        self.update_recordings_size()
        if self.storage_fill > 0.95:
            return {"error": "Recording storage is near capacity. Export and clear the data to continue recording."}
        self.recording_connection = connection_id
        self.recording_paused = False
        self.recording_file = os.path.join('data', 'recordings', 'sessions', datetime.now().strftime("%F-%H-%M-%S-%f")[:-3] + '.csv')
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
            self.recording_file = None
            self.recording_paused = False
            self.recording_connection = None
        return {"message": "Recording finished!"}
