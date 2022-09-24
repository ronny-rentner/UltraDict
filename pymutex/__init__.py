import logging as _log
from .mutex import SharedMutex
from . import mutex

_log.getLogger('pymutex').addHandler(_log.NullHandler())

def configure_default_logging():
    _log.getLogger('pymutex').setLevel(_log.WARNING)
    mutex.configure_default_logging()