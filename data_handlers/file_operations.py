import os
import requests

from hashlib import sha256
from fastapi import UploadFile
from aiofiles import open as async_open


def hash_phrase_to_filename(string):
    return sha256(string.encode()).hexdigest()


async def hash_file_to_filename(file):
    file_content = b""
    while content := await file.read(1024):
        file_content += content
    await file.seek(0)
    return sha256(file_content).hexdigest()


async def hash_and_save_file(file_content: UploadFile, file_type: str):
    file_hash = await hash_file_to_filename(file_content)
    save_path = os.path.join("data", "uploads", f"{file_hash}.{file_content.filename.rsplit('.', 1)[-1]}")
    if not os.path.isfile(save_path):
        async with async_open(save_path, "wb") as save_file:
            while content := await file_content.read(1024):
                await save_file.write(content)
    return {"filename": file_content.filename, "filepath": save_path, "message": f"{file_type} uploaded!"}


def synthesize(phrase, speaker, force=False):
    print("Got phrase ", phrase)
    filepath = os.path.join('data', 'uploads', hash_phrase_to_filename(phrase) + ".wav")
    if force or not os.path.isfile(filepath):
        print("Synthesizing ", filepath)
        r = requests.post('https://api.tartunlp.ai/text-to-speech/v2', json={'text': phrase, 'speaker': speaker})
        with open(filepath, 'wb') as save_file:
            save_file.write(r.content)
    else:
        print("Skipping ", filepath, ", already exists")

    return filepath
