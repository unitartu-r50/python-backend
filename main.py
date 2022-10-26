"""
To run:
uvicorn main:app --host 0.0.0.0 --port 8080 --reload

FastAPI produces documentation automagically! (see https://fastapi.tiangolo.com/tutorial/first-steps/ and https://fastapi.tiangolo.com/tutorial/metadata/)
Docs:
    Swagger: localhost:8080/docs
    Redoc: localhost:8080/redoc

Requirements
python 3.8
pip install fastapi[all]
            aiofiles
            pyaudio
Recording:
sudo apt install portaudio19-dev

TODO: Migrate to Python3.9 (Debian has issues using older Python versions than default, the new Raspberries use 3.9)
TODO: Check delay implementation
TODO: Unlinked files persist. Cleanup on server shutdown, move unlinked files to different folder
TODO: Front expects a json-message as response to POST requests (e.g session adding). (partially?) Use status codes instead?
TODO: Concurrent sessions on n>1 robots
TODO: Unlink images/audio/motions
"""
import os
import json
import subprocess

from uuid import UUID, uuid4
from zipfile import ZipFile
from tempfile import TemporaryFile
from aiofiles import open as async_open

from fastapi import FastAPI, Form, Path, Body, UploadFile, WebSocket, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, validator

from data_handlers.audio import AudioShortcutsHandler
from data_handlers.motion import MotionsHandler
from data_handlers.action import ActionsHandler, ActionShortcutsHandler, MultiAction, UtteranceItem
from data_handlers.session import SessionsHandler, Session
from pepperConnectionManager import PepperConnectionManager
from addressForwardingManager import AddressForwarder
from data_handlers.file_operations import hash_phrase_to_filename, hash_and_save_file, synthesize, compress_session

# SERVER SETTINGS

# Neurokõne speaker
SPEAKERS = ['Luukas', 'Lee']
SPEAKER = 'Luukas'

# Save file paths
SESSIONS_FILE = "data/sessions.json"
AUDIO_SHORTCUTS_FILE = "data/audio_shortcuts.json"
ACTION_SHORTCUTS_FILE = "data/action_shortcuts.json"
MOTIONS_FILE = "data/motions.json"
ADDITINAL_MOTIONS_FOLDER = "data/additional_motions"

# Create missing files/folders
if not os.path.isdir('data'):
    os.mkdir('data')
for subdir in ['additional_motions', 'recordings', 'uploads', 'compressed_sessions']:
    if not os.path.isdir(os.path.join('data', subdir)):
        os.mkdir(os.path.join('data', subdir))
for subdir in ['audio', 'sessions']:
    if not os.path.isdir(os.path.join('data', 'recordings', subdir)):
        os.mkdir(os.path.join('data', 'recordings', subdir))
for memory_file in [SESSIONS_FILE, AUDIO_SHORTCUTS_FILE, ACTION_SHORTCUTS_FILE, MOTIONS_FILE]:
    if not os.path.isfile(memory_file):
        with open(memory_file, "w") as f:
            f.write(json.dumps({os.path.basename(memory_file).rsplit(".", 1)[0]: []}))

# FastAPI config
tags_metadata = [
    {
        "name": "Pepper",
        "description": "Endpoints for communicating with Pepper"
    },
    {
        "name": "Sessions",
        "description": "Session manipulation",
    },
    {
        "name": "General audio",
        "description": "General audio queries"
    },
    {
        "name": "Actions",
        "description": "Action shortcut manipulation"
    },
    {
        "name": "Audio",
        "description": "Audio shortcut manipulation"
    },
    {
        "name": "Motions",
        "description": "Movements manipulation"
    },
    {
        "name": "Uploads",
        "description": "Session uploads"
    },
    {
        "name": "Synthesis",
        "description": "Calls to synthesize and save speech files via Neurokõne"
    },
    {
        "name": "Recording",
        "description": "Calls to start/end audio recording."
    },
    {
        "name": "Maintenance",
        "description": "Calls related to updating the front-end and back-end servers."
    }
]
app = FastAPI(
    title="Pepper backend",
    description="SA Tartu Ülikooli Kliinikumi kõnehäiretega laste robot Pepperi süsteemi toesserveri dokumentatsioon.",
    version="0.10.1",
    contact={
        "name": "Rauno Jaaska",
        "email": "rauno.jaaska@ut.ee",
    },
    openapi_tags=tags_metadata
)
app.mount("/data", StaticFiles(directory="data"), name="data")

# Allowed origins (see https://fastapi.tiangolo.com/tutorial/cors/)
origins = [
    "*"
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*']
)

# TODO: FIX ALSA ERROR OUTPUTS
# Workaround: ALSA errors are only displayed on the first instantiation, so we get it out of the way on boot
# Various methods of silencing stdout/stderr did not have ANY effect (before deadline), more work needed
# p = pyaudio.PyAudio()
# del p

# Helper objects
actions_handler = ActionsHandler()
motions_handler = MotionsHandler(MOTIONS_FILE, ADDITINAL_MOTIONS_FOLDER, actions_handler)
sessions_handler = SessionsHandler(SESSIONS_FILE, actions_handler, motions_handler)
audio_shortcuts_handler = AudioShortcutsHandler(AUDIO_SHORTCUTS_FILE, actions_handler)
action_shortcuts_handler = ActionShortcutsHandler(ACTION_SHORTCUTS_FILE, actions_handler, motions_handler)

pepper_connection_manager = PepperConnectionManager(motions_handler, actions_handler)
address_forwarder = AddressForwarder(10)


# Verbose 422 logging (see https://fastapi.tiangolo.com/tutorial/handling-errors/#use-the-requestvalidationerror-body)
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    print(exc.body, exc.errors())


# Pepper

@app.websocket("/api/pepper/initiate")
async def pepper_connect(websocket: WebSocket):
    await pepper_connection_manager.connect(websocket)


@app.get("/api/pepper/connect",
         tags=['Pepper'], summary="Connect the client to a robot.")
async def connect_pepper(conn: str):
    return await pepper_connection_manager.link(conn)


@app.get("/api/pepper/disconnect",
         tags=['Pepper'], summary="Disconnect the client from a robot.")
async def disconnect_pepper(conn: str):
    return await pepper_connection_manager.unlink(conn)


@app.get("/api/pepper/status",
         tags=['Pepper'], summary="Check Pepper connection status.")
def check_pepper(conn: str):
    return {"status": pepper_connection_manager.get_status(conn)}


@app.post("/api/pepper/send_command",
          tags=['Pepper'], summary="Send Pepper a command to fulfill.")
async def command_pepper(conn: str, item_json: dict = Body(...)):
    return await pepper_connection_manager.send_command(UUID(item_json['item_id']), conn)


@app.get("/api/pepper/stop_video",
         tags=['Pepper'], summary="Stop video playback.")
async def stop_video(conn: str):
    return await pepper_connection_manager.clear_fragment(conn)


# Sessions

@app.get("/api/sessions/",
         tags=['Sessions'], summary="Get all sessions.")
def get_sessions():
    return sessions_handler.get_sorted_sessions()


@app.post("/api/sessions/",
          tags=['Sessions'], summary="Add a session.")
def post_session(session: Session):
    sessions_handler.add_session(session)
    return {"message": "Session saved!"}


@app.get("/api/sessions/{session_id}",
         tags=['Sessions'], summary="Get a specific session.")
def get_session(session_id: UUID = Path(...)):
    return sessions_handler.get_session(session_id)


@app.put("/api/sessions/{session_id}",
         tags=['Sessions'], summary="Update an existing session.")
def update_session(session: Session, session_id: UUID = Path(...)):
    return sessions_handler.update_session(session_id, session)


# TODO: make all deletions non-destructive (?)
@app.delete("/api/sessions/{session_id}",
            tags=['Sessions'], summary="Delete an existing session.")
def remove_session(session_id: UUID = Path(...)):
    sessions_handler.remove_session(session_id)
    return {'message': 'Session removed!'}


@app.get("/api/session_items/{session_item_id}",
         tags=['Sessions'], summary="Get a specific question (SessionItem).")
def get_session_item(session_item_id: UUID = Path(...)):
    return sessions_handler.get_session_item(session_item_id)


@app.get("/api/export_session/{session_id}",
         tags=['Sessions'], summary="Export a session.")
def get_exported_session(session_id: UUID = Path(...)):
    return compress_session(sessions_handler.get_session(session_id))


@app.delete("/api/instruction/{action_id}",
            tags=['Sessions'], summary="Remove an action from a question (SessionItem).")
def delete_session_action(action_id: UUID = Path(...)):
    return sessions_handler.remove_action(action_id)


# Action shortcuts

@app.get("/api/actions/",
         tags=['Actions'], summary="Get all action shortcuts.")
def get_action_shortcuts():
    return action_shortcuts_handler.get_actions()


@app.post("/api/actions/",
          tags=['Actions'], summary="Add an action shortcut.")
def post_action_shortcut(action: MultiAction):
    return action_shortcuts_handler.add_action(action)


@app.post("/api/actions/{action_id}",
          tags=['Actions'], summary="Update an action shortcut")
def update_action_shortcut(action: MultiAction):
    return action_shortcuts_handler.update_action(action)


@app.delete("/api/actions/{action_id}",
            tags=['Actions'], summary="Delete an action shortcut.")
def delete_action_shortcut(action_id: UUID = Path(...)):
    return action_shortcuts_handler.remove_action(action_id)


# Quick audio

@app.get("/api/audio/",
         tags=['Audio'], summary="Get metadata of all quick audio files.")
def get_audio_shortcuts():
    return audio_shortcuts_handler.get_audio_metadata()


@app.post("/api/audio/",
          tags=['Audio'], summary="Add a new audio shortcut")
async def post_audio_shortcut(file_content: UploadFile, phrase: str = Form(...), group: str = Form("Default")):
    phrase_hash = hash_phrase_to_filename(phrase)
    save_path = os.path.join("data", "uploads", f"{phrase_hash}.wav")
    if not os.path.isfile(save_path):
        async with async_open(save_path, "wb") as save_file:
            while content := await file_content.read(1024):
                await save_file.write(content)
    audio_shortcuts_handler.add_audio(UtteranceItem.parse_obj({"ID": uuid4(),
                                                               "Group": group,
                                                               "Delay": 0,
                                                               "Phrase": phrase,
                                                               "FilePath": save_path
                                                               }))
    return {"message": "Audio shortcut created."}


@app.get("/api/audio/{audio_id}",
         tags=['Audio'], summary="Get metadata of a specific audio shortcut")
def get_audio_shortcut(audio_id: UUID = Path(...)):
    return audio_shortcuts_handler.get_single_audio_metadata(audio_id)


@app.delete("/api/audio/{audio_id}",
            tags=['Audio'], summary="Remove an audio shortcut")
def remove_audio_shortcut(audio_id: UUID = Path(...)):
    audio_shortcuts_handler.remove_audio(audio_id)
    return {"message": "Audio shortcut removed"}


# Motions

@app.get("/api/motions/",
         tags=['Motions'], summary="Get metadata of all movements.")
def get_moves():
    return motions_handler.get_motions()


@app.get("/api/motions/{move_id}",
         tags=['Motions'], summary="Get metadata of a specific movement")
def get_move(move_id: UUID = Path(...)):
    return motions_handler.get_motion_by_id(move_id)


# Speech synthesis


@app.get("/api/voices",
         tags=['Synthesis'], summary="List available voices")
def get_voices():
    return {'voices': SPEAKERS}


class SynthesisRequest(BaseModel):
    phrase: str
    voice: str
    speed: float

    @validator('speed')
    def speed_validator(cls, spd):
        print(spd)
        if spd < 0.5 or spd > 2:
            raise ValueError("Speed must be a value between 0.5 and 2!")
        return spd


@app.post("/api/synthesis",
          tags=['Synthesis'], summary="Synthesize speech using the given phrase. Returns the path to the resulting file.")
def post_synthesize(sr: SynthesisRequest):
    print(sr)
    return {'message': 'Audio synthesized!', 'filepath': synthesize(sr.phrase, sr.voice, sr.speed, force=True)}


@app.post("/api/synthesis/batch",
          tags=['Synthesis'], summary="Synthesize all speech for the given session.")
def post_synthesize_batch(voice: str, session: Session):
    for session_item in session.Items:
        for action in session_item.Actions:
            if action.UtteranceItem and action.UtteranceItem.Phrase:
                if action.UtteranceItem.Pronunciation and action.UtteranceItem.Pronunciation != action.UtteranceItem.Phrase:
                    phrase = action.UtteranceItem.Pronunciation
                else:
                    phrase = action.UtteranceItem.Phrase
                    action.UtteranceItem.Pronunciation = ""
                action.UtteranceItem.FilePath = synthesize(phrase, voice, action.UtteranceItem.Speed, force=True)
    return sessions_handler.update_session(session.ID, session)


# Uploads

@app.post("/api/upload/audio",
          tags=['Uploads'], summary="Upload session audio")
async def post_audio(file_content: UploadFile):
    return await hash_and_save_file(file_content, "Audio file")


@app.post("/api/upload/image",
          tags=["Uploads"], summary="Upload session image")
async def post_image(file_content: UploadFile):
    return await hash_and_save_file(file_content, "Image")


@app.post("/api/upload/session",
          tags=['Uploads'], summary="Upload a session")
async def post_session(file_content: UploadFile):
    temp_file = TemporaryFile()
    temp_file.write(file_content.file.read())
    session_zip = ZipFile(temp_file)
    if 'session.json' not in session_zip.namelist():
        return {'error': 'Session file missing from archive!'}

    for filename in list(filter(lambda x: x.startswith('uploads/'), session_zip.namelist())):
        # Extract the file manually to avoid wonky directory creation via ZipFile.extract()
        with open(os.path.join('data', 'uploads', os.path.basename(filename)), 'wb') as f1:
            f1.write(session_zip.read(filename))
    with session_zip.open('session.json') as sess:
        session = json.loads(sess.read())

    if file_content.filename.replace(".zip", "") != session['Name']:
        return {'error': {'Import failed: archive and session name do not match!'}}

    # If an existing session shares the name with the posted session, the client-side check has passed and
    # the existing session must be updated instead.
    for old_session in sessions_handler.sessions:
        if session['Name'] == old_session.Name:
            await sessions_handler.dict_to_session_rename(session)
            sessions_handler.update_session(old_session.ID, Session.parse_obj(session))
            return {'message': "Session update dummy msg", 'session_index': sessions_handler.get_session_index(session['ID'])}
    await sessions_handler.import_session(session)
    return {'message': 'Session imported!', 'session_index': sessions_handler.get_session_index(session['ID'])}


# Recording

# # Testing
# @app.get("/api/recording/test")
# def start_recording():
#     return pepper_connection_manager.recorder.record()
#
#
# @app.get("/api/recording/test_end")
# def start_recording():
#     return pepper_connection_manager.recorder.stop_recording()


@app.get("/api/recording/start",
         tags=['Recording'], summary="Begin recording audio and session progress.",
         description="Audio is taken from the server's default audio input and is saved in WAV format. Recordings can be found in data/recordings.")
def start_recording(conn: str):
    return pepper_connection_manager.start_recording(conn)


@app.get("/api/recording/stop",
         tags=['Recording'], summary="Stop recording.")
def stop_recording(conn: str):
    return pepper_connection_manager.stop_recording(conn)


# Server maintenance

@app.get("/api/rebuild",
         tags=['Maintenance'], summary="Rebuild the site via NPM.")
def get_rebuild():
    subprocess.Popen('./rebuild.sh', shell=True, preexec_fn=os.setpgrp)
    return {'message': "Started rebuild.sh"}


@app.get("/api/check_update",
         tags=['Maintenance'], summary="Check for update availability.")
def get_update_status():
    subprocess.run(['git', 'fetch'])
    backend_update = "[behind " in str(subprocess.check_output(['git', 'status', '-sb']))
    os.chdir("../web-client")
    subprocess.run(['git', 'fetch'])
    frontend_update = "[behind " in str(subprocess.check_output(['git', 'status', '-sb']))
    os.chdir("../python-backend")
    return {"update_available": backend_update or frontend_update}


@app.get("/api/update",
         tags=['Maintenance'], summary="Update the servers")
def get_update():
    subprocess.Popen('./update.sh', shell=True, preexec_fn=os.setpgrp)
    return {'message': "Started update.sh"}


@app.get("/api/shutdown",
         tags=['Maintenance'], summary="Shut the server down.")
def get_shutdown():
    os.system("shutdown -P now")


@app.on_event("shutdown")
def shutdown_event():
    motions_handler.save_motions()
    sessions_handler.save_sessions()
    address_forwarder.stop()
