import json
import wave
import asyncio
import pyaudio
import websockets

from os import path
from datetime import datetime
from threading import Thread

from config import CLOUDFRONT_SERVER, AUDIO_ENDPOINT


class RecordingWorker(Thread):
    def __init__(self, filename, caller):
        super().__init__()
        self.record = False

        self.p = pyaudio.PyAudio()
        self.chunk = 4096
        self.sample_format = pyaudio.paInt16
        self.channels = 1
        self.sample_rate = 44100
        self.filename = filename
        self.caller = caller

    # Starlette's websockets don't enable creating connections, so plain websockets is used instead (requires async).
    async def stream_audio(self, pyaudio_stream):
        async with websockets.connect("ws://" + CLOUDFRONT_SERVER + AUDIO_ENDPOINT) as websocket:
            await websocket.send(json.dumps({"ch": self.channels,
                                             "sw": self.p.get_sample_size(self.sample_format),
                                             "fr": self.sample_rate,
                                             "session": self.filename}))
            while self.caller.flag:
                await websocket.send(pyaudio_stream.read(self.chunk))

        pyaudio_stream.stop_stream()
        pyaudio_stream.close()
        self.p.terminate()

    def run(self):
        pyaudio_stream = self.p.open(format=self.sample_format,
                                     channels=self.channels,
                                     rate=self.sample_rate,
                                     frames_per_buffer=self.chunk,
                                     input=True
                                     )

        if self.caller.stream:
            # An asynchronous function inside a synchronous function? Madness!
            asyncio.run(self.stream_audio(pyaudio_stream))

        else:
            frames = []
            if self.filename is None:
                self.filename = datetime.now().strftime("%F-%H-%M-%S-%f")[:-3] + ".wav"

            while self.caller.flag:
                frames.append(pyaudio_stream.read(self.chunk))

            pyaudio_stream.stop_stream()
            pyaudio_stream.close()
            self.p.terminate()

            with wave.open(path.join("data", "recordings", "audio", self.filename), "wb") as wav_file:
                wav_file.setnchannels(self.channels)
                wav_file.setsampwidth(self.p.get_sample_size(self.sample_format))
                wav_file.setframerate(self.sample_rate)
                wav_file.writeframes(b''.join(frames))


class Recorder:
    def __init__(self, stream=False):
        self.stream = stream
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
