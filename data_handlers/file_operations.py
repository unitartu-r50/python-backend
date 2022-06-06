import os

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
    if os.path.isfile(save_path):
        return {"filepath": save_path, "message": f"{file_type} linked!"}
    async with async_open(save_path, "wb") as save_file:
        while content := await file_content.read(1024):
            await save_file.write(content)
    return {"filepath": save_path, "message": f"{file_type} uploaded!"}
