# Bind address of the server
HOST = "0.0.0.0"
PORT = 3000

# Extended log output, but slower
DEBUG = True

# Required to encrypt or sign sessions, cookies, tokens, etc.
SECRET = "CHANGEME!!!!!!!!!!@##@!!$$$$$$$$$$$$$!!"

# Connection to the database
POSTGRES_URL = "postgresql+asyncpg://obs:obs@postgres/obs"

# URL to the keycloak realm, as reachable by the API service. This is not
# necessarily its publicly reachable URL, keycloak advertises that iself.
KEYCLOAK_URL = "http://keycloak:8080/auth/realms/OBS%20Dev/"

# Auth client credentials
KEYCLOAK_CLIENT_ID = "portal"
KEYCLOAK_CLIENT_SECRET = "76b84224-dc24-4824-bb98-9e1ba15bd58f"

# Whether the API should run the worker loop, or a dedicated worker is used
DEDICATED_WORKER = True

# The root of the frontend. Needed for redirecting after login, and for CORS.
# Set to None if frontend is served by the API.
FRONTEND_URL = "http://localhost:3000/"

# Where to find the compiled frontend assets (must include index.html), or None
# to disable serving the frontend.
FRONTEND_DIR = None

# Can be an object or a JSON string
FRONTEND_CONFIG = None

# Path overrides:
# API_ROOT_DIR = "??" # default: api/ inside repository
DATA_DIR = "/data"
# PROCESSING_DIR = "??" # default: DATA_DIR/processing
# PROCESSING_OUTPUT_DIR = "??"  # default: DATA_DIR/processing-output
# TRACKS_DIR = "??" # default: DATA_DIR/tracks
# OBS_FACE_CACHE_DIR = "??" # default: DATA_DIR/obs-face-cache

# vim: set ft=python :
