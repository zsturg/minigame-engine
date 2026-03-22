import sys
import os

def resource_path(relative_path):
    """
    Resolve a path to a bundled resource (data files shipped with the app).

    PyInstaller folder build:
        sys._MEIPASS points to a temp dir containing bundled data.
    Running from source:
        Resolves relative to the script directory.
    """
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)


def writable_path(relative_path):
    """
    Resolve a path for *writable* files (config, user data).

    When frozen, _MEIPASS is read-only, so writable files live next to the .exe.
    When running from source, same as resource_path (script directory).
    """
    if hasattr(sys, '_MEIPASS'):
        # sys.executable is the .exe; its parent is the app folder
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, relative_path)
