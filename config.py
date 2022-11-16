# Various settings are listed here for quick access.

# Variables prone to external change (e.g. neurokõne voice names) used throughout are be listed here.

# Some variables have historically accurate defaults, others are left blank.
# For the server to work, all variables must have values.

# Web address of the server which receives session progress and recordings, and yields chatbot predictions.
# If unspecified, recorded data will be saved to local storage under data/recordings/ and
# AI predictions will not be available.
CLOUDFRONT_SERVER = "127.0.0.1:80"
# Path to the recording identifier requesting endpoint
START_RECORD_ENDPOINT = "/start_session"
# Path to the audio input websocket endpoint
AUDIO_ENDPOINT = "/stream_recording"
# Path to the action appendment endpoint
ACTION_ENDPOINT = "/add_action"


# Local recording storage size limit in GB (see CLOUDFRONT_SERVER)
RECORDING_SIZE_LIMIT = 5

# Speech synthesis via Neurokõne

# List of strings representing neurokõne speakers
SPEAKERS = ['Luukas', 'Lee']
# String identifying the default speaker
SPEAKER = 'Luukas'


# Redirection

# When these fields are filled, this server sends its IP address to ADDRESS_RECEIVER.
# The server hosting that address should then provide that IP address to visitors.
# This enables persistent access (in the same local network as this server) without
# resorting to network scanning or reserving IP addresses in the local network.

# Server web address listening to this server's IP
ADDRESS_RECEIVER = "https://deltabot.tartunlp.ai/pepper/set"

# Name supplied to the redirection server used to differentiate between instances of this server
SERVER_IDENTIFIER = ""
