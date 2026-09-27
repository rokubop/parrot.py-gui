from lib.default_config import *
import os

# The user override lives in the data root so each profile carries its own
# settings; exec because the root is only known at runtime.
_USER_CONFIG_FILE = os.path.join(DATA_DIR, "code", "config.py")
if not os.path.exists(_USER_CONFIG_FILE):
    os.makedirs(os.path.dirname(_USER_CONFIG_FILE), exist_ok=True)
    configfile = open(_USER_CONFIG_FILE, "w")
    configfile.write('DEFAULT_CLF_FILE = ""\n')
    configfile.write('STARTING_MODE = ""\n')
    configfile.write('MICROPHONE_SEPARATOR = None\n')
    configfile.close()
with open(_USER_CONFIG_FILE, encoding="utf-8") as _f:
    exec(compile(_f.read(), _USER_CONFIG_FILE, "exec"))
