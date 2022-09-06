#
# UltraDict
#
# A sychronized, streaming Python dictionary that uses shared memory as a backend
#
# Copyright [2022] [Ronny Rentner] [ultradict.code@ronny-rentner.de]
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

__all__ = ['UltraDict']

import multiprocessing, multiprocessing.shared_memory, multiprocessing.synchronize
import collections, os, pickle, sys, time, weakref
import importlib.util, importlib.machinery

try:
    # Needed for the shared locked
    import atomics
except ModuleNotFoundError:
    pass

try:
    import ultraimport
    Exceptions = ultraimport('__dir__/Exceptions.py')
    try:
        log = ultraimport('__dir__/utils/log.py', 'log', package=1)
        log.log_targets = [ sys.stderr ]
    except ultraimport.ResolveImportError:
        import logging as log
except ModuleNotFoundError:
    from . import Exceptions
    try:
        from .utils import log
        log.log_targets = [ sys.stderr ]
    except ModuleNotFoundError:
        import logging as log

def remove_shm_from_resource_tracker():
    """
    Monkey-patch multiprocessing.resource_tracker so SharedMemory won't be tracked
    More details at: https://bugs.python.org/issue38119
    """
    # pylint: disable=protected-access, import-outside-toplevel
    # Ignore linting errors in this bug workaround hack
    from multiprocessing import resource_tracker
    def fix_register(name, rtype):
        if rtype == "shared_memory":
            return None
        return resource_tracker._resource_tracker.register(name, rtype)
    resource_tracker.register = fix_register
    def fix_unregister(name, rtype):
        if rtype == "shared_memory":
            return None
        return resource_tracker._resource_tracker.unregister(name, rtype)
    resource_tracker.unregister = fix_unregister
    if "shared_memory" in resource_tracker._CLEANUP_FUNCS:
        del resource_tracker._CLEANUP_FUNCS["shared_memory"]

#More details at: https://bugs.python.org/issue38119
remove_shm_from_resource_tracker()

class UltraDict(collections.UserDict, dict):

    Exceptions = Exceptions
    log = log

    class RLock(multiprocessing.synchronize.RLock):
        """ Not yet used """
        pass

    class SharedLock():
        """
        Lock stored in shared_memory to provide an additional layer of protection,
        e.g. when using spawned processes.

        Internally uses atomics package of patomics for atomic locking.

        This is needed if you write to the shared memory with independent processes.
        """

        __slots__ = 'parent', 'has_lock',  'ctx', 'lock_atomic', 'lock_remote', \
            'pid', 'pid_bytes', 'pid_remote', 'pid_remote_ctx', 'pid_remote_atomic', \
            'next_acquire_parameters'

        def __init__(self, parent, lock_name, pid_name):
            self.has_lock = 0
            self.next_acquire_parameters = ()

            # `lock_name` contains the name of the attribute that the parent uses
            # to store the memory view on the remote lock, so `self.lock_remote` is
            # referring to a memory view
            self.lock_remote = getattr(parent, lock_name)
            self.pid_remote = getattr(parent, pid_name)

            self.init_pid()

            try:
                self.ctx = atomics.atomicview(buffer=self.lock_remote[0:1], atype=atomics.BYTES)
                self.pid_remote_ctx = atomics.atomicview(buffer=self.pid_remote[0:4], atype=atomics.BYTES)
            except NameError as e:
                self.cleanup()
                raise e
            self.lock_atomic = self.ctx.__enter__()
            self.pid_remote_atomic = self.pid_remote_ctx.__enter__()

            def after_fork():
                if self.has_lock:
                    raise Exception("Release the SharedLock before you fork the process")

                # After forking, we got a new pid
                self.init_pid()

            if sys.platform != 'win32':
                os.register_at_fork(after_in_child=after_fork)

        def init_pid(self):
            self.pid = multiprocessing.current_process().pid
            self.pid_bytes = self.pid.to_bytes(4, 'little')

        def acquire_with_timeout(self, block=True, sleep_time=0.000001, timeout=1.0, steal_after_timeout=False):
            # The block parameter will be ignored
            time_start = None
            blocking_pid = None
            while True:
                try:
                    return self.acquire(block=False, sleep_time=sleep_time)
                except Exceptions.CannotAcquireLock as e:
                    if not time_start:
                        time_start = e.timestamp
                        blocking_pid = e.blocking_pid

                    # We should not be the blocking pid
                    assert blocking_pid != self.pid

                    time_passed = time.monotonic() - time_start

                    if time_passed >= timeout:
                        if steal_after_timeout:
                            # If the blocking pid has changed meanwhile, someone else took or stole the lock
                            if blocking_pid == e.blocking_pid:
                                self.steal_from_dead(from_pid=blocking_pid, release=True)
                            time_start = None
                            blocking_pid = None
                            continue
                        raise Exceptions.CannotAcquireLockTimeout(blocking_pid = e.blocking_pid, timestamp=time_start) from None


        #@profile
        def acquire(self, block=True, sleep_time=0.000001, timeout=None, steal_after_timeout=False):
            # If we already own the lock, just increment our counter
            if self.has_lock:
                self.has_lock += 1
                return True

            if timeout:
                return self.acquire_with_timeout(sleep_time=sleep_time, timeout=timeout, steal_after_timeout=steal_after_timeout)

            while True:
                # We need both, the shared lock to be False and the lock_pid to be 0
                if self.test_and_inc():

                    assert self.has_lock == 0
                    self.has_lock = 1

                    # If nobody had owned the lock, so the remote pid should be zero
                    assert self.pid_remote[0:4] == b'\x00\x00\x00\x00'

                    self.pid_remote[:] = self.pid_bytes
                    return True

                # If set to 0, we practically have a busy wait
                if sleep_time:
                    # On Python < 3.10, this smallest possible time is actually rather big,
                    #  maybe around 10 ms, depending on your CPU.
                    time.sleep(sleep_time)

                if not block:
                    raise Exceptions.CannotAcquireLock(blocking_pid=self.get_remote_pid())

        #@profile
        def test_and_inc(self):
            old = self.lock_atomic.exchange(b'\x01')
            if old != b'\x00':
                # Oops, someone else was faster than us
                return False
            return True

        #@profile
        def test_and_dec(self):
            old = self.lock_atomic.exchange(b'\x00')
            if old != b'\x01':
                raise Exception("Failed to release lock")
            return True

        #@profile
        def release(self, *args):
            #log.debug("Release lock, lock={}", self.has_lock)
            if self.has_lock > 0:
                owner = int.from_bytes(self.pid_remote, 'little')
                if owner != self.pid:
                    raise Exception(f"Our lock for pid {self.pid} was stolen by pid {owner}")
                self.has_lock -= 1
                # Last local lock released, release shared lock
                if not self.has_lock:
                    self.pid_remote[:] = b'\x00\x00\x00\x00'
                    self.test_and_dec()
                #log.debug("Relased lock, lock={} pid_remote={}", self.has_lock, int.from_bytes(self.pid_remote, 'little'))
                return True

            return False

        def reset(self):
            # Risky
            self.lock_remote[:] = b'\x00'
            self.pid_remote[:] = b'\x00\x00\x00\x00'
            self.has_lock = 0

        def reset_acquire_parameters(self):
            self.next_acquire_parameters = ()

        def steal(self, from_pid=0, release=False):
            if self.has_lock:
                raise Exception("Cannot steal the lock because we have already acquired it. Use release() to release the lock.")

            #log.debug(f'Stealing from_pid={from_pid}, remote_pid={self.get_remote_pid()}')

            # It's not locked, so nothing to steal from
            if not self.get_remote_lock():
                return False

            # Someone else has stolen the lock
            if from_pid != self.get_remote_pid():
                return False

            # Stealing the lock means actually just putting our pid into the shared memory overwriting the other pid.
            # This can go wrong if the lock owner is actually still alive and working.
            result = self.pid_remote_atomic.cmpxchg_strong(expected=from_pid.to_bytes(4, 'little'), desired=self.pid_bytes)
            if result.success:
                self.has_lock = 1
                if release:
                    self.release()
            return result.success

        def steal_from_dead(self, from_pid=0, release=False):
            """ Check if from_pid is actually a dead process and if yes, steal the lock from it.
                Optionally, the lock can be directly released after stealing it.
            """

            try:
                import psutil
            except ModuleNotFoundError:
                raise Exceptions.MissingDependency("Install `psutil` Python package to use shared_lock=True") from None
            # No process must exist anymore with the from_pid or it must at least be dead (ie. zombie status)
            try:
                p = psutil.Process(from_pid)
                if p and p.is_running() and p.status() not in [psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD]:
                    raise Exception(f"Trying to steal lock from process that is still alive, something seems really wrong from_pid={from_pid} pid={self.pid} p={p}")
            except psutil.NoSuchProcess:
                # If the process is already gone, we cannot find information about it.
                # It will be safe to steal the lock.
                pass
            except Exception as e:
                raise e

            return self.steal(from_pid=from_pid, release=release)

        def status(self):
            return {
                'has_lock': self.has_lock,
                'lock_remote': int.from_bytes(self.lock_remote, 'little'),
                'pid': self.pid,
                'pid_remote': int.from_bytes(self.pid_remote, 'little'),
            }

        def print_status(self, status=None):
            import pprint
            if not status:
                status = self.status()
            pprint.pprint(status)

        def cleanup(self):
            if hasattr(self, 'ctx'):
                self.ctx.__exit__(None, None, None)
                del self.ctx
            if hasattr(self, 'lock_atomic'):
                del self.lock_atomic
            if hasattr(self, 'pid_remote_ctx'):
                self.pid_remote_ctx.__exit__(None, None, None)
                del self.pid_remote_ctx
            if hasattr(self, 'pid_remote_aotmic'):
                del self.pid_remote_atomic
            del self.lock_remote
            del self.pid_remote
            del self.pid_bytes
            del self.pid

        def get_remote_pid(self):
            return int.from_bytes(self.pid_remote, 'little')

        def get_remote_lock(self):
            return int.from_bytes(self.lock_remote, 'little')

        def __repr__(self):
            return f"{self.__class__.__name__} @{hex(id(self))} lock_remote={int.from_bytes(self.lock_remote, 'little')}, has_lock={self.has_lock}, pid={self.pid}), pid_remote={int.from_bytes(self.pid_remote, 'little')}"

        def __enter__(self):
            self.acquire(*self.next_acquire_parameters)
            self.reset_acquire_parameters()
            return self

        def __exit__(self, type, value, traceback):
            self.release()
            # Make sure exceptions are not ignored
            return False

        def __call__(self, block=True, timeout=None, sleep_time=0.000001, steal_after_timeout=False):
            self.next_acquire_parameters = ( block, timeout, sleep_time, steal_after_timeout )

            return self

    __slots__ = 'name', 'control', 'buffer', 'buffer_size', 'lock', 'shared_lock', \
        'update_stream_position', 'update_stream_position_remote', \
        'full_dump_counter', 'full_dump_memory', 'full_dump_size', \
        'serializer', \
        'lock_pid_remote', \
        'lock_remote', \
        'full_dump_counter_remote', \
        'full_dump_static_size_remote', \
        'shared_lock_remote', \
        'recurse', 'recurse_remote', 'recurse_register', \
        'full_dump_memory_name_remote', \
        'data', 'closed', 'auto_unlink', \
        'finalizer'

    def __init__(self, *args, name=None, create=None, buffer_size=10_000, serializer=pickle, shared_lock=None, full_dump_size=None,
            auto_unlink=None, recurse=None, recurse_register=None, **kwargs):
        # pylint: disable=too-many-branches, too-many-statements

        # On win32, only multiples of 4k are allowed
        if sys.platform == 'win32':
            buffer_size = -(buffer_size // -4096) * 4096
            if full_dump_size:
                full_dump_size = -(full_dump_size // -4096) * 4096

        assert buffer_size < 2**32

        if recurse:
            assert serializer == pickle

        self.data = {}

        # Local position, ie. the last position we have processed from the stream
        self.update_stream_position  = 0

        # Local version counter for the full dumps, ie. if we find a higher version
        # remote, we need to load a full dump
        self.full_dump_counter       = 0

        self.closed = False
        self.auto_unlink = auto_unlink

        # Small 1000 bytes of shared memory where we store the runtime state
        # of our update stream
        self.control = self.get_memory(create=create, name=name, size=1000)
        self.name = self.control.name

        def finalize(weak_self, name):
            #log.debug('Finalize', name)
            resolved_self = weak_self()
            if resolved_self is not None:
                #log.debug('Weakref is intact, closing')
                resolved_self.close(from_finalizer=True)
            #log.debug('Finalized')

        self.finalizer = weakref.finalize(self, finalize, weakref.ref(self), self.name)

        self.init_remotes()

        self.serializer = serializer

        # Actual stream buffer that contains marshalled data of changes to the dict
        self.buffer = self.get_memory(create=create, name=self.name + '_memory', size=buffer_size)
        # TODO: Raise exception if buffer size mismatch
        self.buffer_size = self.buffer.size

        self.full_dump_memory = None

        # Dynamic full dump memory handling
        # Warning: Issues on Windows when the process ends that has created the full dump memory
        self.full_dump_size = None

        if hasattr(self.control, 'created_by_ultra'):

            if auto_unlink is None:
                self.auto_unlink = True

            if recurse:
                self.recurse_remote[0:1] = b'1'

            if shared_lock:
                self.shared_lock_remote[0:1] = b'1'

            # We created the control memory, thus let's check if we need to create the
            # full dump memory as well
            if full_dump_size:
                self.full_dump_size = full_dump_size
                self.full_dump_static_size_remote[:] = full_dump_size.to_bytes(4, 'little')

                self.full_dump_memory = self.get_memory(create=True, name=self.name + '_full', size=full_dump_size)
                self.full_dump_memory_name_remote[:] = self.full_dump_memory.name.encode('utf-8').ljust(255)

        # We just attached to the existing control
        else:
            # TODO: Detect configuration mismatch and raise an exception

            # Check if we have a fixed size full dump memory
            size = int.from_bytes(self.full_dump_static_size_remote, 'little')

            # Check if shared_lock parameter was not set to inconsistent value
            shared_lock_remote = self.shared_lock_remote[0:1] == b'1'
            if shared_lock is None:
                shared_lock = shared_lock_remote
            elif shared_lock != shared_lock_remote:
                raise Exceptions.ParameterMismatch(f"shared_lock={shared_lock} was set but the creator has used shared_lock={shared_lock_remote}")

            # Check if recurse parameter was not set to inconsistent value
            recurse_remote = self.recurse_remote[0:1] == b'1'
            if recurse is None:
                recurse = recurse_remote
            elif recurse != recurse_remote:
                raise Exceptions.ParameterMismatch(f"recure={recurse} was set but the creator has used recurse={recurse_remote}")

            # Got existing size of full dump memory, that must mean it's static size
            # and we should attach to it
            if size > 0:
                self.full_dump_size = size
                self.full_dump_memory = self.get_memory(create=False, name=self.name + '_full')

        # Local lock for all processes and threads created by the same interpreter
        if shared_lock:
            try:
                self.lock = self.SharedLock(self, 'lock_remote', 'lock_pid_remote')
            except NameError:
                #self.cleanup()
                raise Exceptions.MissingDependency("Install `atomics` Python package to use shared_lock=True") from None
        else:
            self.lock = multiprocessing.RLock()

        self.shared_lock = shared_lock

        # Parameters that could be read from remote if we are connecting to an existing UltraDict
        self.recurse = recurse

        # In recurse mode, we must ensure a recurse register
        if self.recurse:
            # Must be either the name of an UltraDict as a string or an UltraDict instance
            if recurse_register is not None:
                if type(recurse_register) == str:
                    self.recurse_register = UltraDict(name=recurse_register)
                elif type(recurse_register) == UltraDict:
                    self.recurse_register = recurse_register
                else:
                    raise Exception("Bad type for recurse_register")

            # If no register was defined, we should create one
            else:
                self.recurse_register = UltraDict(name=f'{self.name}_register',
                    recurse=False, auto_unlink=False, shared_lock=self.shared_lock)
                # The register should not run its own finalizer if we need it later for unlinking our nested children
                if self.auto_unlink:
                    self.recurse_register.finalizer.detach()
                    #log.debug("Created recurse register with name={}", self.recurse_register.name)

        else:
            self.recurse_register = None

        super().__init__(*args, **kwargs)

        # Load all data from shared memory
        self.apply_update()

        if sys.platform == 'win32':
            if not shared_lock:
                log.warning('You are running on win32, potentially without locks. Consider setting shared_lock=True')


        #if auto_unlink:
        #    atexit.register(self.unlink)
        #else:
        #    atexit.register(self.cleanup)

        #log.debug("Initialized", self.name)

    def __del__(self):
        #log.debug("__del__", self.name)
        self.close()
        if hasattr(self, 'recurse') and self.recurse:
            #log.debug("Close recurse register")
            self.recurse_register.close()
            del self.recurse_register


    def init_remotes(self):
        # Memoryviews to the right buffer position in self.control
        self.update_stream_position_remote = self.control.buf[ 0:  4]
        self.lock_pid_remote               = self.control.buf[ 4:  8]
        self.lock_remote                   = self.control.buf[ 8: 10]
        self.full_dump_counter_remote      = self.control.buf[10: 14]
        self.full_dump_static_size_remote  = self.control.buf[14: 18]
        self.shared_lock_remote            = self.control.buf[18: 19]
        self.recurse_remote                = self.control.buf[19: 20]
        self.full_dump_memory_name_remote  = self.control.buf[20:275]

    def del_remotes(self):
        """
        Delete all instance attributes whose name ends with '_remote' from
        the instance for cleanup. This shall ensure there are no
        reference left to shared memory views so proper cleanup can happen.
        """
        remotes = [ r for r in dir(self) if r.endswith('_remote') ]
        for r in remotes:
            if hasattr(self, r):
                delattr(self, r)

    def __reduce__(self):
        from functools import partial
        return (partial(self.__class__, name=self.name, auto_unlink=self.auto_unlink, recurse_register=self.recurse_register), ())

    @staticmethod
    def get_memory(*, create=True, name=None, size=0):
        """
        Attach an existing SharedMemory object with `name`.

        If `create` is True, create the object if it does not exist.
        """
        assert size > 0 or not create
        if name:
            # First try to attach to existing memory
            try:
                memory = multiprocessing.shared_memory.SharedMemory(name=name)
                #log.debug('Attached shared memory: ', memory.name)

                if create:
                    raise Exceptions.AlreadyExists(f"Cannot create memory '{name}' because it already exists")

                return memory
            except FileNotFoundError:
                pass

        # No existing memory found
        if create or create is None:
            memory = multiprocessing.shared_memory.SharedMemory(create=True, size=size, name=name)
            #multiprocessing.resource_tracker.unregister(memory._name, 'shared_memory')
            # Remember that we have created this memory
            memory.created_by_ultra = True
            #log.debug('Created shared memory: ', memory.name)

            return memory

        raise Exceptions.CannotAttachSharedMemory(f"Could not get memory '{name}'")

    #@profile
    def dump(self):
        """ Dump the full dict into shared memory """

        with self.lock:
            old = bytes(self.full_dump_memory_name_remote).decode('utf-8').strip().strip('\x00')

            self.apply_update()

            marshalled = self.serializer.dumps(self.data)
            length = len(marshalled)

            # If we don't have a fixed size, let's create full dump memory dynamically
            # TODO: This causes issues on Windows because the memory is not persistant
            #       Maybe switch to mmaped file?
            if self.full_dump_size and self.full_dump_memory:
                full_dump_memory = self.full_dump_memory
            else:
                # Dynamic full dump memory
                full_dump_memory = self.get_memory(create=True, size=length + 6)

            #log.debug("Full dump memory: ", full_dump_memory)

            if length + 6 > full_dump_memory.size:
                raise Exceptions.FullDumpMemoryFull(f'Full dump memory too small for full dump: needed={length + 6} got={full_dump_memory.size}')

            # Write header, 6 bytes
            # First byte is FF byte
            full_dump_memory.buf[0:1] = b'\xFF'
            # Then comes 4 bytes of length of the body
            full_dump_memory.buf[1:5] = length.to_bytes(4, 'little')
            # Then another FF bytes, end of header
            full_dump_memory.buf[5:6] = b'\xFF'

            # Write body
            full_dump_memory.buf[6:6+length] = marshalled

            # On Windows, if we close it, it cannot be read anymore by anyone else.
            if not self.full_dump_size and sys.platform != 'win32':
                full_dump_memory.close()

            # TODO: There's a slight chance of something going wrong when we first update
            #       the remote memory name and then the counter.

            # Only after we have filled the new full dump memory with the marshalled data,
            # we update the remote name so other users can find it
            if not (self.full_dump_size and self.full_dump_memory):
                self.full_dump_memory_name_remote[:] = full_dump_memory.name.encode('utf-8').ljust(255)

            self.full_dump_counter += 1
            current = int.from_bytes(self.full_dump_counter_remote, 'little')
            # Now also increment the remote counter
            self.full_dump_counter_remote[:] = int(current + 1).to_bytes(4, 'little')

            # Reset the stream position to zero as we have
            # just provided a fresh new full dump
            self.update_stream_position = 0
            self.update_stream_position_remote[:] = b'\x00\x00\x00\x00'

            #log.info("Dumped dict with {} elements to {} bytes, remote_counter={}", len(self), len(marshalled), current+1)

            # If the old full dump memory was dynamically created, delete it
            if old and old != full_dump_memory.name and not self.full_dump_size:
                self.unlink_by_name(old)

            # On Windows, we need to keep a reference to the full dump memory,
            # otherwise it's destoryed
            self.full_dump_memory = full_dump_memory

            return full_dump_memory

    def get_full_dump_memory(self, max_retry=3, retry=0):
        """
        Attach to the full dump memory.

        Retry if necessary for a low number of times. It could happen that the full
        dump memory was removed because a new full dump was created before we had the
        chance to read the old full dump.

        """
        try:
            name = bytes(self.full_dump_memory_name_remote).decode('utf-8').strip().strip('\x00')
            #log.debug("Full dump name={}", name)
            assert len(name) >= 1
            return self.get_memory(create=False, name=name)
        except Exceptions.CannotAttachSharedMemory as e:
            if retry < max_retry:
                return self.get_full_dump_memory(max_retry=max_retry, retry=retry+1)
            elif retry == max_retry:
                # On the last retry, let's use a lock to ensure we can safely import the dump
                with self.lock:
                    return self.get_full_dump_memory(max_retry=max_retry, retry=retry+1)
            else:
                raise e

    #@profile
    def load(self, force=False):
        """
        Opportunistacally load full dumps without any locking.

        There is a rare case where a full dump is replaced with a newer full dump while
        we didn't have the chance to load the old one. In this case, we just retry.
        """
        full_dump_counter = int.from_bytes(self.full_dump_counter_remote, 'little')
        #log.debug("Loading full dump local_counter={} remote_counter={}", self.full_dump_counter, full_dump_counter)
        try:
            if force or (self.full_dump_counter < full_dump_counter):
                if self.full_dump_size and self.full_dump_memory:
                    full_dump_memory = self.full_dump_memory
                else:
                    # Retry if necessary
                    full_dump_memory = self.get_full_dump_memory()

                buf = full_dump_memory.buf
                pos = 0

                # Read header
                # The first byte should be a FF byte to introduce the header
                assert bytes(buf[pos:pos+1]) == b'\xFF'
                pos += 1
                # Then comes 4 bytes of length
                length = int.from_bytes(bytes(buf[pos:pos+4]), 'little')
                assert length > 0, (self.status(), full_dump_memory, bytes(buf[:]).decode('utf-8').strip().strip('\x00'), len(buf))
                pos += 4
                #log.debug("Found update, pos={} length={}", pos, length)
                assert bytes(buf[pos:pos+1]) == b'\xFF'
                pos += 1
                # Unserialize the update data, we expect a tuple of key and value
                self.data = self.serializer.loads(bytes(buf[pos:pos+length]))
                self.full_dump_counter = full_dump_counter
                self.update_stream_position = 0

                if sys.platform != 'win32' and not self.full_dump_memory:
                    full_dump_memory.close()
            else:
                raise Exception("Cannot load full dump, no new data available")
        except AssertionError as e:
            full_dump_delta = int.from_bytes(self.full_dump_counter_remote, 'little') - self.full_dump_counter
            if full_dump_delta > 1:
                # If more than one new full dump was created during the time we were trying to load one full dump
                # it can happen that our full dump has just disappeared
                return self.load(force=True)
            # TODO: Before we reach max recursion depth, try to load the full dump using a lock
            self.print_status()
            raise e

    #@profile
    def append_update(self, key, item, delete=False):
        """ Append dict changes to shared memory stream """

        # If mode is 0, it means delete the key from the dict
        # If mode is 1, it means update the key
        #mode = not delete
        marshalled = self.serializer.dumps((not delete, key, item))
        length = len(marshalled)

        with self.lock:
            start_position = int.from_bytes(self.update_stream_position_remote, 'little')
            # 6 bytes for the header
            end_position = start_position + length + 6
            #log.debug("Update start from={} len={}", start_position, length)
            if end_position > self.buffer_size:
                #log.debug("Buffer is full")

                # todo: is is necessary? apply_update() is also done inside dump()
                self.apply_update()
                if not delete:
                    self.data.__setitem__(key, item)
                self.dump()
                return

            marshalled = b'\xFF' + length.to_bytes(4, 'little') + b'\xFF' + marshalled

            # Write body with the real data
            self.buffer.buf[start_position:end_position] = marshalled

            # Inform others about it
            self.update_stream_position = end_position
            self.update_stream_position_remote[:] = end_position.to_bytes(4, 'little')
            #log.debug("Update end to={} buffer_size={} ", end_position, self.buffer_size)

    #@profile
    def apply_update(self):
        """ Opportunistically apply dict changes from shared memory stream without any locking.  """

        if self.full_dump_counter < int.from_bytes(self.full_dump_counter_remote, 'little'):
            self.load(force=True)

        if self.update_stream_position < int.from_bytes(self.update_stream_position_remote, 'little'):

            # Remember start position in the update stream
            pos = self.update_stream_position
            #log.debug("Apply update: stream position own={} remote={} full_dump_counter={}", pos, int.from_bytes(self.update_stream_position_remote, 'little'), self.full_dump_counter)

            try:
                # Iterate over all updates until the start of the last update
                while pos < int.from_bytes(self.update_stream_position_remote, 'little'):
                    # Read header
                    # The first byte should be a FF byte to introduce the headerfull_dump_counter_remote
                    assert bytes(self.buffer.buf[pos:pos+1]) == b'\xFF'
                    pos += 1
                    # Then comes 4 bytes of length
                    length = int.from_bytes(bytes(self.buffer.buf[pos:pos+4]), 'little')
                    pos += 4
                    #log.debug("Found update, update_stream_position={} length={}", self.update_stream_position, length + 6)
                    assert bytes(self.buffer.buf[pos:pos+1]) == b'\xFF'
                    pos += 1
                    # Unserialize the update data, we expect a tuple of key and value
                    mode, key, value = self.serializer.loads(bytes(self.buffer.buf[pos:pos+length]))
                    # Update or local dict cache (in our parent)
                    if mode:
                        self.data.__setitem__(key, value)
                    else:
                        self.data.__delitem__(key)
                    pos += length
                    # Remember that we have applied the update
                    self.update_stream_position = pos
            except (AssertionError, pickle.UnpicklingError) as e:

                # It can happen that a slow process is not fast enough reading the stream and some
                # other process already got around overwriting the current position. It is possible to
                # recover from this situation if and only if a new, fresh full dump exists that can be loaded.
                if self.full_dump_counter < int.from_bytes(self.full_dump_counter_remote, 'little'):
                    log.warning(f"Full dumps too fast full_dump_counter={self.full_dump_counter} full_dump_counter_remote={int.from_bytes(self.full_dump_counter_remote, 'little')}. Consider increasing buffer_size.")
                    return self.apply_update()

                # As a last resort, let's get a lock. This way we are safe but slow.
                with self.lock:
                    if self.full_dump_counter < int.from_bytes(self.full_dump_counter_remote, 'little'):
                        log.warning(f"Full dumps too fast full_dump_counter={self.full_dump_counter} full_dump_counter_remote={int.from_bytes(self.full_dump_counter_remote, 'little')}. Consider increasing buffer_size.")
                        return self.apply_update()

                raise e

    def update(self, other=None, *args, **kwargs):
        # pylint: disable=arguments-differ, keyword-arg-before-vararg

        # The original signature would be `def update(self, other=None, /, **kwargs)` but
        # this is not possible with Cython. *args will just be ignored.

        if other is not None:
            for k, v in other.items() if isinstance(other, collections.abc.Mapping) else other:
                self[k] = v
        for k, v in kwargs.items():
            self[k] = v

    def __delitem__(self, key):
        #log.debug("__delitem__ {}", key)
        with self.lock:
            self.apply_update()

            # Update our local copy
            self.data.__delitem__(key)

            self.append_update(key, b'', delete=True)
            # TODO: Do something if append_update() fails

    def __setitem__(self, key, item):
        #log.debug("__setitem__ {}, {}", key, item)
        with self.lock:
            self.apply_update()

            if self.recurse:

                assert type(self.recurse_register) == UltraDict, "recurse_register must be an UltraDict instance"

                if type(item) == dict:
                    # TODO: Use parent's buffer with a namespace prefix?
                    item = UltraDict(item,
                                     recurse          = True,
                                     recurse_register = self.recurse_register,
                                     auto_unlink      = False,
                                     shared_lock      = self.shared_lock,
                                     buffer_size      = self.buffer_size,
                                     full_dump_size   = self.full_dump_size)

                    if item.name not in self.recurse_register.data:
                        self.recurse_register[item.name] = True

            # Update our local copy
            # It's important for the integrity to do this first
            self.data.__setitem__(key, item)

            # Append the update to the update stream
            self.append_update(key, item)
            # TODO: Do something if append_u int.from_bytes(self.update_stream_position_remote, 'little')pdate() fails

    def __getitem__(self, key):
        #log.debug("__getitem__ {}", key)
        self.apply_update()
        return self.data[key]

    # deprecated in Python 3
    def has_key(self, key):
        self.apply_update()
        return key in self.data

    def __eq__(self, other):
        return self.apply_update() == other.apply_update()

    def __contains__(self, key):
        self.apply_update()
        return key in self.data

    def __len__(self):
        self.apply_update()
        return len(self.data)

    def __iter__(self):
        self.apply_update()
        return iter(self.data)

    def __repr__(self):
        try:
            self.apply_update()
        except Exceptions.AlreadyClosed:
            # If something goes wrong during the update, let's ignore it and still return a representation
            # TODO: Maybe somehow add a stale update warning?
            pass
        return self.data.__repr__()

    def status(self):
        """ Internal debug helper to get the control state variables """
        ret = { attr: getattr(self, attr) for attr in self.__slots__ if hasattr(self, attr) and attr != 'data' }

        ret['update_stream_position_remote'] = int.from_bytes(self.update_stream_position_remote, 'little')
        ret['lock_pid_remote']               = int.from_bytes(self.lock_pid_remote, 'little')
        ret['lock_remote']                   = int.from_bytes(self.lock_remote, 'little')
        ret['shared_lock_remote']            = self.shared_lock_remote[0:1] == b'1'
        ret['recurse_remote']                = self.recurse_remote[0:1] == b'1'
        ret['lock']                          = self.lock
        ret['full_dump_counter_remote']      = int.from_bytes(self.full_dump_counter_remote, 'little')
        ret['full_dump_memory_name_remote']  = bytes(self.full_dump_memory_name_remote).decode('utf-8').strip('\x00').strip()

        return ret

    def print_status(self, status=None, stderr=False):
        """ Internal debug helper to pretty print the control state variables """
        import pprint
        if not status:
            status = self.status()
        pprint.pprint(status, stream=sys.stderr if stderr else sys.stdout)

    def cleanup(self):
        #log.debug('Cleanup')

        #for item in self.data.items():
        #    print(type(item))

        if hasattr(self, 'lock') and hasattr(self.lock, 'cleanup'):
            self.lock.cleanup()

        # If we use RLock(), this closes the file handle
        if hasattr(self, 'lock'):
            del self.lock
        if hasattr(self, 'full_dump_memory'):
            del self.full_dump_memory

        data = self.data
        del self.data

        self.del_remotes()

        #self.control.close()
        #self.buffer.close()

        #if self.full_dump_memory:
        #    self.full_dump_memory.close()

        # No further cleanup on Windows, it will break everything
        #if sys.platform == 'win32':
        #    return

        #Only do cleanup once
        #atexit.unregister(self.cleanup)

        self.apply_update = self.raise_already_closed
        self.append_update = self.raise_already_closed

        return data

    def raise_already_closed(self, *args, **kwargs):
        raise Exceptions.AlreadyClosed('UltraDict already closed, you can only access the `UltraDict.data` buffer!')

    def keys(self):
        self.apply_update()
        return self.data.keys()

    def values(self):
        self.apply_update()
        return self.data.values()

    def unlink(self):
        self.close(unlink=True)

    def close(self, unlink=False, from_finalizer=False):
        #log.debug('Close name={} unlink={} auto_unlink={} creator={}', self.name, unlink, self.auto_unlink, hasattr(self.control, 'created_by_ultra'))

        if self.closed:
            #log.debug('Already closed, doing nothing')
            return
        self.closed = True

        if hasattr(self, 'finalizer'):
            self.finalizer.detach()

        if hasattr(self, 'full_dump_memory_name_remote'):
            full_dump_name = bytes(self.full_dump_memory_name_remote).decode('utf-8').strip().strip('\x00')

        data = self.cleanup()

        # If we are the master creator of the shared memory, we'll delete (unlink) it
        # including the full dump memory; for the full dump memory, we delete it even
        # if we are not the creator
        if unlink or (self.auto_unlink and hasattr(self.control, 'created_by_ultra')):
            #log.debug('Unlink', self.name)
            self.control.unlink()
            self.buffer.unlink()
            if full_dump_name:
                self.unlink_by_name(full_dump_name, ignore_errors=True)

            if getattr(self, 'recurse', False):
                self.unlink_recursed()

        if hasattr(self, 'control'):
            self.control.close()
        if hasattr(self, 'buffer'):
            self.buffer.close()

        return data

    def unlink_recursed(self):
        #log.debug("Unlink recursed id={}", hex(id(self)))
        if not self.recurse or (type(self.recurse_register) != UltraDict):
            raise Exception("Cannot unlink recursed for non-recurse UltraDict")

        ignore_errors = sys.platform == 'win32'
        for name in self.recurse_register.keys():
            #log.debug("Unlink recursed child name={}", name)
            self.unlink_by_name(name=name, ignore_errors=ignore_errors)
            self.unlink_by_name(name=f"{name}_memory", ignore_errors=ignore_errors)

        self.recurse_register.close(unlink=True)


    @staticmethod
    def unlink_by_name(name, ignore_errors=False):
        """
        Can be used to delete left over shared memory blocks after crashes.
        """
        try:
            #log.debug("Unlinking memory '{}'", name)
            memory = UltraDict.get_memory(create=False, name=name)
            memory.unlink()
            memory.close()
            return True
        except Exceptions.CannotAttachSharedMemory as e:
            if not ignore_errors:
                raise e
        return False



# Saved as a reference

#def bytes_to_int(bytes):
#    result = 0
#    for b in bytes:
#        result = result * 256 + int(b)
#    return result
#
#def int_to_bytes(value, length):
#    result = []
#    for i in range(0, length):
#        result.append(value >> (i * 8) & 0xff)
#    result.reverse()
#    return result

#class Mapping(dict):
#
#    def __init__(self, *args, **kwargs):
#        print("__init__", args, kwargs)
#        super().__init__(*args, **kwargs)
#
#    def __setitem__(self, key, item):
#        print("__setitem__", key, item)
#        self.__dict__[key] = item
#
#    def __getitem__(self, key):
#        print("__getitem__", key)
#        return self.__dict__[key]
#
#    def __repr__(self):
#        print("__repr__")
#        return repr(self.__dict__)
#
#    def __len__(self):
#        print("__len__")
#        return len(self.__dict__)
#
#    def __delitem__(self, key):
#        print("__delitem__")
#        del self.__dict__[key]
#
#    def clear(self):
#        print("clear")
#        return self.__dict__.clear()
#
#    def copy(self):
#        print("copy")
#        return self.__dict__.copy()
#
#    def has_key(self, k):
#        print("has_key")
#        return k in self.__dict__
#
#    def update(self, *args, **kwargs):
#        print("update")
#        return self.__dict__.update(*args, **kwargs)
#
#    def keys(self):
#        print("keys")
#        return self.__dict__.keys()
#
#    def values(self):
#        print("values")
#        return self.__dict__.values()
#
#    def items(self):
#        print("items")
#        return self.__dict__.items()
#
#    def pop(self, *args):
#        print("pop")
#        return self.__dict__.pop(*args)
#
#    def __cmp__(self, dict_):
#        print("__cmp__")
#        return self.__cmp__(self.__dict__, dict_)
#
#    def __contains__(self, item):
#        print("__contains__", item)
#        return item in self.__dict__
#
#    def __iter__(self):
#        print("__iter__")
#        return iter(self.__dict__)
#
#    def __unicode__(self):
#        print("__unicode__")
#        return unicode(repr(self.__dict__))
#
