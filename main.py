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

TODO: Cache motion IDs to persist between server restarts
TODO: Check delay implementation
TODO: Stop video playback when another command is sent
TODO: Unlinked files persist. Cleanup on server shutdown, move unlinked files to different folder
TODO: GET requests return data as the value to key 'data', make the key 'sessions', 'audio' etc. instead
TODO: Front expects a json-message as response to POST requests (e.g session adding). (partially?) Use status codes instead?
TODO: Concurrent sessions on n>1 robots
TODO: Unlink images/audio/motions
"""
import os
import json
import requests
import subprocess

from uuid import UUID, uuid4
from zipfile import ZipFile
from tempfile import TemporaryFile
from aiofiles import open as async_open

from fastapi import FastAPI, Form, Path, Body, UploadFile, WebSocket, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError

from recorder import Recorder
from data_handlers.audio import AudioShortcutsHandler
from data_handlers.motion import MotionsHandler
from data_handlers.action import ActionsHandler, ActionShortcutsHandler, MultiAction, UtteranceItem
from data_handlers.session import SessionsHandler, Session
from pepperConnectionManager import PepperConnectionManager
from data_handlers.file_operations import hash_phrase_to_filename, hash_and_save_file

# SERVER SETTINGS

# Neurokõne speaker
SPEAKER = 'Luukas'

# Save file paths
SESSIONS_FILE = "data/sessions.json"
AUDIO_SHORTCUTS_FILE = "data/quick_audio.json"
ACTION_SHORTCUTS_FILE = "data/quick_actions.json"
MOTIONS_FILE = "data/motions.json"

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
motions_handler = MotionsHandler(MOTIONS_FILE, actions_handler)
sessions_handler = SessionsHandler(SESSIONS_FILE, actions_handler, motions_handler)
audio_shortcuts_handler = AudioShortcutsHandler(AUDIO_SHORTCUTS_FILE, actions_handler)
action_shortcuts_handler = ActionShortcutsHandler(ACTION_SHORTCUTS_FILE, actions_handler)

recorder = Recorder()
pepper_connection_manager = PepperConnectionManager(motions_handler, actions_handler)


# Verbose 422 logging (see https://fastapi.tiangolo.com/tutorial/handling-errors/#use-the-requestvalidationerror-body)
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    print(exc.body, exc.errors())


# Pepper

# TODO: Eduroam breaks websocket connections for some reason. Find out why, make sure final network doesn't.
@app.websocket("/api/pepper/initiate")
async def pepper_connect(websocket: WebSocket):
    await pepper_connection_manager.connect(websocket)


# TODO: Currently reports whether ANY connection exists. Rewrite to checking a specific connection.
@app.get("/api/pepper/status",
         tags=['Pepper'], summary="Check Pepper connection status")
def check_pepper():
    return {"status": pepper_connection_manager.get_status()}


@app.post("/api/pepper/send_command",
          tags=['Pepper'], summary="Send Pepper a command to fulfill")
async def command_pepper(item_json: dict = Body(...)):
    # TODO: Finish (check if URLs work in a non-local network)
    return await pepper_connection_manager.send_command(UUID(item_json['item_id']))


# Sessions

@app.get("/api/sessions/",
         tags=['Sessions'], summary="Get all sessions.")
def get_sessions():
    return sessions_handler.get_sessions()


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
    return sessions_handler.get_sessions()


@app.get("/api/session_items/{session_item_id}",
         tags=['Sessions'], summary="Get a specific question (SessionItem).")
def get_session_item(session_item_id: UUID = Path(...)):
    return sessions_handler.get_session_item(session_item_id)


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
    action_shortcuts_handler.add_action(action)
    return {"message": "Action created!"}


@app.delete("/api/actions/{action_id}",
            tags=['Actions'], summary="Delete an action shortcut.")
def delete_action_shortcut(action_id: UUID = Path(...)):
    action_shortcuts_handler.remove_action(action_id)
    return {"message": "Action deleted!"}


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

@app.post("/api/synthesis",
          tags=['Synthesis'], summary="Synthesize speech using the given phrase. Returns the path to the resulting file.")
def post_synthesize(phrase: str = Body(...)):
    print("Got phrase ", phrase)
    filepath = os.path.join('data', 'uploads', hash_phrase_to_filename(phrase) + ".wav")
    if not os.path.isfile(filepath):
        print("Synthesizing ", filepath)
        r = requests.post('https://api.tartunlp.ai/text-to-speech/v2', json={'text': phrase, 'speaker': SPEAKER})
        with open(filepath, 'wb') as save_file:
            save_file.write(r.content)
    else:
        print("Skipping ", filepath, ", already exists")
    return {'message': 'Audio synthesized!', 'filepath': filepath}


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
    await sessions_handler.import_session(session)
    return {'message': 'Session imported!'}


# Recording

@app.get("/api/recording/start",
         tags=['Recording'], summary="Begin recording audio using the default input of the backend.")
def start_recording():
    # TODO: Create the filename based on session progress (combine SessionItem hash and starting time?)
    recorder.record("testrec.wav")


@app.get("/api/recording/stop",
         tags=['Recording'], summary="Stop recording",
         description="Finish the recording and save the audio in WAV format.")
def stop_recording():
    recorder.stop_recording()


# Server maintenance

@app.get("/api/check_update",
         tags=['Maintenance'], summary="Check for update availability.")
def get_update_status():
    subprocess.run(['git', 'fetch'])
    backend_update = "[behind " in str(subprocess.check_output(['git', 'status', '-sb']))
    os.chdir("../web-client")
    subprocess.run(['git', 'fetch'])
    frontend_update = "[behind " in str(subprocess.check_output(['git', 'status', '-sb']))
    os.chdir("../python-backend")
    return {"update-available": backend_update or frontend_update}


@app.get("/api/update",
         tags=['Maintenance'], summary="Update the servers")
def get_update():
    subprocess.Popen('./update.sh', shell=True, preexec_fn=os.setpgrp)
    return {'message': "Started update.sh"}


@app.get("/api/shutdown",
         tags=['Maintenance'], summary="Shut the server down.")
def get_shutdown():
    subprocess.run("sudo shutdown -P now")


@app.on_event("shutdown")
def shutdown_event():
    motions_handler.save_motions()
    sessions_handler.save_sessions()

# r.GET("/tmp/:name", serveCleanlyHandler)
#
# // pepper communication
# r.POST("/api/pepper/send_command", sendCommandHandler)
#
# // sessions management
# r.GET("/api/session_items/:id", getSessionItemJSONHandler)
# r.GET("/api/session_export/:id", exportSessionJSONHandler)
# r.POST("/api/session_import", importSessionHandler)
#
# // ?
# r.GET("/api/instruction/:id", getInstructionJSONHandler)
# r.DELETE("/api/instruction/:id", deleteInstructionJSONHandler)
#
# // general upload API
# r.DELETE("/api/upload/audio", deleteUploadJSONHandler)
# r.DELETE("/api/upload/image", deleteUploadJSONHandler)
# r.POST("/api/upload/move", moveUploadJSONHandler)
#
# // serving moveStore
# r.DELETE("/api/moves/:id", deleteMoveJSONHandler)
#
# // utilities: helpful endpoints
# for the client application or other
# r.GET("/api/move_groups/", moveGroupsJSONHandler)
