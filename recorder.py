import wave
import pyaudio

from os import path
from datetime import datetime
from threading import Thread


class RecordingWorker(Thread):
    def __init__(self, filename, caller):
        super().__init__()
        self.record = False

        self.p = pyaudio.PyAudio()
        self.chunk = 1024
        self.sample_format = pyaudio.paInt16
        self.channels = 2
        self.sample_rate = 16000
        self.filename = filename or datetime.now().strftime("%F-%H-%M-%S-%f")[:-3] + ".wav"
        self.caller = caller

    def run(self):
        frames = []
        stream = self.p.open(format=self.sample_format,
                             channels=self.channels,
                             rate=self.sample_rate,
                             frames_per_buffer=self.chunk,
                             input=True
                             )

        while self.caller.flag:
            frames.append(stream.read(self.chunk))

        stream.stop_stream()
        stream.close()
        self.p.terminate()

        with wave.open(path.join("data", "recordings", "audio", self.filename), "wb") as wav_file:
            wav_file.setnchannels(self.channels)
            wav_file.setsampwidth(self.p.get_sample_size(self.sample_format))
            wav_file.setframerate(self.sample_rate)
            wav_file.writeframes(b''.join(frames))


class Recorder:
    def __init__(self):
        self.worker = None
        self.flag = False

    def record(self, filename=None):
        if self.worker is not None:
            print("Already recording!")
            return
        self.flag = True

        self.worker = RecordingWorker(filename, self)
        self.worker.start()
        print("Recording started.")

    def stop_recording(self):
        if self.worker is None:
            print("No recording in progress, nothing to stop.")
            return
        self.flag = False
        self.worker.join()
        filename = self.worker.filename
        self.worker = None
        print("Recording finished.")
        return filename
