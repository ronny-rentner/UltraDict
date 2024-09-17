# MIT License

# Copyright (c) 2020 HMaker

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.


import os
import errno
import time
import stat
import mmap
import weakref
import logging
import ctypes, ctypes.util
from . import utils

pthread_lib = ctypes.util.find_library('pthread')
if pthread_lib:
    _pt = ctypes.CDLL(pthread_lib)

# pthread structs' size from pthreadtypes-arch.h
_PTHREAD_MUTEX_ATTRS_SIZE = 4
import platform as _platform
_arch = _platform.architecture()[0]
if _arch == '64bit':
    if ctypes.sizeof(ctypes.POINTER(ctypes.c_int)) == 8:
        _PTHREAD_MUTEX_SIZE = 40
    else:
        _PTHREAD_MUTEX_SIZE = 32
elif _arch == '32bit':
    _PTHREAD_MUTEX_SIZE = 24
else:
    raise ImportError(f'Unknown platform architecture: {_arch}')


_MUTEX_LOAD_TIMEOUT = 2 # in secs
_MUTEX_LOCK_HEARTBEAT = 1 # in secs

def configure_default_logging():
    logger = logging.getLogger('pymutex.SharedMutex')
    handler = logging.StreamHandler()
    datetime_fmt = utils.get_local_datetime_fmt()
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(name)s in %(short_mutex_pathname)s] %(levelname)s: %(message)s",
            datefmt=f'{datetime_fmt[0]} {datetime_fmt[1]}'
        )
    )
    logger.addHandler(handler)


# posix timespec in types/struct_timespectypes.h
class _timespec(ctypes.Structure):
    _fields_ = [
        ('tv_sec', ctypes.c_long),
        ('tv_nsec', ctypes.c_long)
    ]

class InvalidSharedState(Exception):
    """Raised when the shared state protected by the mutex is invalid.
    It will be raised in all attempts to lock the mutex after
    SharedMutex.recover_shared_state() returns False."""

class UninitializedMutexError(Exception):
    """The mutex is in an uninitialized state."""
    pass


class _MutexState:
    """This class holds the mutex state because it will be accessed when SharedMutex
    is being garbage collected (through weakref.finalize), that would not be possible
    if a reference to SharedMutex was used. So the reference graph will look like:
        <application's code> -> SharedMutex -> _MutexState
        weakref.finalize() -> _MutexState
    When SharedMutex is collected by the GC, _MutexState is destroyed.
    """

    def __init__(self, pathname: str, mutex_ptr, mutex_attrs_ptr, mutex_fd: int,
                 mutex_mmap: mmap.mmap, recover_shared_state_cb):
        self.mutex_ptr = mutex_ptr
        self.mutex_attrs_ptr = mutex_attrs_ptr
        self.locked = False
        self.fd = mutex_fd
        self.mmap = mutex_mmap
        self.recover_shared_state_cb = recover_shared_state_cb
        self.logger = logging.LoggerAdapter(
            logging.getLogger('pymutex.SharedMutex'),
            {'short_mutex_pathname': utils.shrink_path(pathname, 2), 'mutex_pathname': pathname}
        )


def _mutex_finalizer(state: _MutexState):
    """This will not destroy the mutex. If this mutex is freed when locked, all threads
    waiting for this mutex will be in a deadlock."""
    state.logger.debug("Cleaning up...")
    if state.mutex_ptr is None:
        state.logger.critical("The mutex had a null mutex_ptr when being cleaned.")
    if state.locked:
        state.logger.critical("Possible deadlock! This mutex was left locked.")
    state.mutex_ptr = None
    state.mutext_attrs_ptr = None
    os.close(state.fd)
    state.mmap.flush()
    state.mmap.close() # let gc collect it later
    state.logger.debug("Mutex cleaned.")


class SharedMutex:
    """A POSIX robust mutex that is shareable across processes.
    The sharing is done by memory mapping a file that contains the mutex's state.
    """

    def __init__(self, mutex_file: str, recover_shared_state_cb):
        """Create a new mutex and store its state in "mutex_file" file. If "mutex_file" already exists,
        the stored mutex will be loaded. The only validation that is done when opening an existing
        file that is *supposed* to be a mutex is by checking its size. Trying to lock or unlock an
        invalid mutex is undefined behavior.

        Parameters
        ----------
        1. mutex_file: The pathname of the shared mutex

        2. recover_shared_state_cb (callable):
        The callback that is called when the last thread that locked this mutex terminated
        without unlocking it. Use this callback to ensure the application's shared state
        protected by this mutex is consistent. This callback takes no argument and must
        return True if the shared state is consistent, False otherwise. The current thread
        owns the lock (don't try to unlock). If the shared state is marked as inconsistent, the
        mutex will be unusable and any attempt to lock it results in InvalidSharedState error
        (see man pages of pthread_mutex_lock for more details). This callback MUST NOT keep any
        direct or indirect reference to this mutex, otherwise it is not granted that this mutex
        will be cleaned up correctly.
        """
        try:
            # create and open the mutex's file in read-write mode, fail if it exists
            # the created file will be in read-only mode, only the current process can
            # write to it.
            mutex_fd = os.open(
                mutex_file,
                os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_TRUNC,
                stat.S_IRUSR
            )
        except FileExistsError:
            # Try to mmap it
            self._mutex_load(mutex_file, recover_shared_state_cb)
            self._finalizer = weakref.finalize(self, _mutex_finalizer, self._state)
            return
        try:
            mutex_attrs = ctypes.create_string_buffer(_PTHREAD_MUTEX_ATTRS_SIZE)
            mutex_attrs_ptr = ctypes.byref(mutex_attrs)
            e = _pt.pthread_mutexattr_init(mutex_attrs_ptr)
            if e != 0:
                raise OSError(e, os.strerror(e))
            # set type to PTHREAD_MUTEX_ERRORCHECK
            e = _pt.pthread_mutexattr_settype(mutex_attrs_ptr, ctypes.c_int(2))
            if e != 0:
                raise OSError(e, os.strerror(e))
            # set robustness to PTHREAD_MUTEX_ROBUST
            try:
                e = _pt.pthread_mutexattr_setrobust(mutex_attrs_ptr, ctypes.c_int(1))
            except AttributeError:
                pass
            if e != 0:
                raise OSError(e, os.strerror(e))
            # set sharing mode to PTHREAD_PROCESS_SHARED
            e = _pt.pthread_mutexattr_setpshared(mutex_attrs_ptr, ctypes.c_int(1))
            if e != 0:
                raise OSError(e, os.strerror(e))
            mutex = ctypes.create_string_buffer(_PTHREAD_MUTEX_SIZE)
            e = _pt.pthread_mutex_init(ctypes.byref(mutex), mutex_attrs_ptr)
            if e != 0:
                _pt.pthread_mutexattr_destroy(mutex_attrs_ptr)
                raise OSError(e, os.strerror(e))
            try:
                assert os.write(mutex_fd, mutex) == _PTHREAD_MUTEX_SIZE, 'Failed to store the mutex'
                # Share the mutex by creating a memory mapped file
                mutex_mmap = mmap.mmap(mutex_fd, 0, mmap.MAP_SHARED, mmap.PROT_WRITE | mmap.PROT_READ)
                mutex = ctypes.c_char.from_buffer(mutex_mmap)
                # Process's user will have write and read permissions on the mutex file from now
                # FIXME: Should it restrict all processes to be running as same user?
                os.fchmod(mutex_fd, stat.S_IRUSR | stat.S_IWUSR)
            except:
                _pt.pthread_mutex_destroy(ctypes.byref(mutex))
                _pt.pthread_mutexattr_destroy(mutex_attrs_ptr)
                raise
        except:
            os.remove(mutex_file)
            os.close(mutex_fd)
            raise
        self._state = _MutexState(mutex_file, ctypes.byref(mutex), mutex_attrs_ptr, mutex_fd, mutex_mmap, recover_shared_state_cb)
        self._finalizer = weakref.finalize(self, _mutex_finalizer, self._state)

    @property
    def owns_lock(self):
        """Returns True if this mutex instance owns the lock, False otherwise."""
        return self._state.locked

    def lock(self, block: bool = True, timeout: float = 0):
        """Lock the mutex. If "block" is True, the current thread
        blocks until the mutex becomes available, if "timeout" > 0 the
        thread blocks until timeout (in seconds) expires. Returns
        True if the mutex was locked, False otherwise."""
        #if self._state.mutex_ptr is None: raise RuntimeError('Invalid state')
        if block:
            # The robustness setting only works for lock attempts that
            # comes *after* the thread holding the lock terminates
            # without releasing it. The blocking call will be made of
            # several calls to pthread_mutex_timedlock.
            if timeout and timeout > 0:
                locked = self._mutex_timedlock(timeout, False)
            else:
                locked = self._mutex_timedlock(_MUTEX_LOCK_HEARTBEAT)
        else:
            e = _pt.pthread_mutex_trylock(self._state.mutex_ptr)
            if e == 0:
                locked = True
            else:
                locked = self._mutex_lock_handle_error(e)

        if locked:
            self._state.locked = True
            return True
        else:
            return False

    def unlock(self):
        """Unlock the mutex. Raises PermissionError if the current thread does not owns the lock."""
        #if self._state.mutex_ptr is None: raise RuntimeError('Invalid mutex state')
        e = _pt.pthread_mutex_unlock(self._state.mutex_ptr)
        if e == 0:
            self._state.locked = False
        elif e == errno.EINVAL:
            raise UninitializedMutexError()
        else:
            raise OSError(e, os.strerror(e))

    def _mutex_timedlock(self, timeout: float, until_lock = True):
        while True:
            current_timeout = time.clock_gettime(time.CLOCK_REALTIME) + timeout
            e = _pt.pthread_mutex_timedlock(
                self._state.mutex_ptr,
                ctypes.byref(_timespec(
                    int(current_timeout),
                    int((current_timeout * 1000 % 1000) * 1_000_000)
                ))
            )
            if e == 0:
                return True
            elif e == errno.ETIMEDOUT:
                if not until_lock: return False
            else:
                return self._mutex_lock_handle_error(e)

    def _mutex_lock_handle_error(self, e: int):
        """Returns True if the lock was acquired, False otherwise.
        Raises OSError if "e" can't be handled."""
        if e == errno.EBUSY:
            return False
        elif e == errno.EINVAL:
            raise UninitializedMutexError()
        elif e == errno.EOWNERDEAD:
            # The last thread holding the lock terminated without releasing it,
            # make sure the shared state is consistent.
            # The current thread owns the lock
            try:
                self._state.logger.warning("The last thread holding the lock left it locked, recovering...")
                if self._state.recover_shared_state_cb():
                    try:
                        e = _pt.pthread_mutex_consistent(self._state.mutex_ptr)
                    except AttributeError:
                        pass
                    if e != 0:
                        raise OSError(e, os.strerror(e))
                    return True
                self._state.logger.warning("The shared state could not be recovered, this mutex is unusable from now.")
                raise InvalidSharedState('The shared state could not be recovered by recover_shared_state callback.')
            except:
                self.unlock()
                raise
        elif e == errno.ENOTRECOVERABLE:
            self._state.logger.warning("This mutex is unusable, it must be removed.")
            raise InvalidSharedState('The shared state could not be recovered by recover_shared_state callback.')
        else:
            raise OSError(e, os.strerror(e))

    def _mutex_load(self, mutex_file: str, recover_shared_state_cb):
        attempts = 0
        while True:
            try:
                mutex_fd = os.open(mutex_file, os.O_RDWR)
                if os.lseek(mutex_fd, 0, os.SEEK_END) != _PTHREAD_MUTEX_SIZE:
                    os.close(mutex_fd)
                    raise ValueError(f"The mutex stored in file <{mutex_file}> is invalid.")
                os.lseek(mutex_fd, 0, os.SEEK_SET)
                break
            except PermissionError:
                if attempts * 0.2 >= _MUTEX_LOAD_TIMEOUT:
                    raise TimeoutError(f"The loading of the mutex in '{mutex_file}' timed out. Check whether other process terminated when initializing the mutex and remove the file.")
                attempts += 1
                time.sleep(0.2)
        mutex_mmap = mmap.mmap(mutex_fd, 0, mmap.MAP_SHARED, mmap.PROT_WRITE | mmap.PROT_READ)
        self._state = _MutexState(
            mutex_file,
            ctypes.byref(ctypes.c_char.from_buffer(mutex_mmap)),
            None,
            mutex_fd,
            mutex_mmap,
            recover_shared_state_cb
        )
