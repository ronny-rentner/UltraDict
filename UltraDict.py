#
# UltraDict
#
# A sychronized Python dictionary that uses shared memory as a backend
#
# Copyright [2022] [Ronny Rentner] [mail@ronny-rentner.de]
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

import multiprocessing, multiprocessing.shared_memory, collections, atexit, enum, time, marshal

import atomics

try:
    from utils import log
except:
    import logging as log


def remove_shm_from_resource_tracker():
    """
    Monkey-patch multiprocessing.resource_tracker so SharedMemory won't be tracked
    More details at: https://bugs.python.org/issue38119
    """
    from multiprocessing import resource_tracker
    def fix_register(name, rtype):
        if rtype == "shared_memory":
            return
        return resource_tracker._resource_tracker.register(name, rtype)
    resource_tracker.register = fix_register
    def fix_unregister(name, rtype):
        if rtype == "shared_memory":
            return
        return resource_tracker._resource_tracker.unregister(name, rtype)
    resource_tracker.unregister = fix_unregister
    if "shared_memory" in resource_tracker._CLEANUP_FUNCS:
        del resource_tracker._CLEANUP_FUNCS["shared_memory"]

remove_shm_from_resource_tracker()




class UltraDict(collections.UserDict):

    class SharedLock():
        """
        Lock stored in shared_memory to provide an additional layer of protection,
        e.g. when using spawned processes.

        Locking process:

        1.  Check if `lock` and `lock_pid` are both not set.
        2.  Set `lock` to True.
        3a. If `lock_pid` is still not set, set `lock_pid` to our own pid.
        3b. If `lock_pid` is set, there is a race condition. Exception!
                TODO: Wait for lock to become available.
        4.  Do the critical work.
        5.  Check if `lock_pid` is still set to our own pid.
        6a. If yes, all is good, set `lock_pid` to 0.
        6b. If no, some other process stole our lock. Exception!
                TODO: Try to repeat if lock was stolen.
        7.  Set `lock` to False, all done.
        """

        __slots__ = 'parent', 'has_lock', 'lock_name', 'pid', 'pid_name', 'lock'

        def __init__(self, parent, lock_name, pid_name):
            self.parent = parent
            self.has_lock = 0
            self.lock_name = lock_name
            self.pid_name = pid_name
            self.pid = multiprocessing.current_process().pid
            self.lock = getattr(self.parent, self.lock_name)

        def aquire(self):
            #log.debug("Acquire lock")
            lock = getattr(self.parent, self.lock_name)
            pid = getattr(self.parent, self.pid_name)
            counter = 0

            # If we already own the lock, just increment our counter
            if self.has_lock:
                #log.debug("Already got lock", self.has_lock)
                self.has_lock += 1
                ipid = int.from_bytes(pid, 'little')
                if ipid != self.pid:
                    raise Exception("Error, '{}' stole our lock '{}'".format(ipid, self.pid))

                return True

            # We try to get the lock and busy wait until it's ready
            while True:
                # We need both, the shared lock to be False and the lock_pid to be 0
                if self.test_and_inc():
                    self.has_lock += 1

                    ipid = int.from_bytes(pid, 'little')
                    #log.debug("Got lock", self.has_lock, self.pid, ipid)

                    # If nobody owns the lock, the pid should be zero
                    assert ipid == 0
                    pid[:] = self.pid.to_bytes(4, 'little')
                    return True
                else:
                    # Oh no, already locked by someone else
                    # TODO: Busy wait?
                    counter += 1
                    if counter > 100_000:
                        raise Exception("Failed to aquire lock")

        def test_and_inc(self):
            with atomics.atomicview(buffer=self.lock, width=2, atype=atomics.INT) as lock_atomic:
                lock_state = lock_atomic.load()
                if lock_state == 0:
                    old = lock_atomic.exchange(1)
                    #log.debug('inc old: ', old)
                    if old != 0:
                        # Oops, someone else was faster than us
                        return False
                    return True
            return False

        def test_and_dec(self):
            with atomics.atomicview(buffer=self.lock, width=2, atype=atomics.INT) as lock_atomic:
                lock_state = lock_atomic.load()
                if lock_state == 1:
                    old = lock_atomic.exchange(0)
                    #log.debug('dec old: ', old)
                    if old != 1:
                        raise Exception("failed test and dec")
                    return True
            return False


        def release(self):
            #log.debug("Release lock", self.has_lock)
            if self.has_lock > 0:
                lock = getattr(self.parent, self.lock_name)
                pid = getattr(self.parent, self.pid_name)
                if int.from_bytes(pid, 'little') != self.pid:
                    raise Exception("Our lock for pid {} was stolen by pid {}".format(self.pid, int.from_bytes(pid, 'little')))
                self.has_lock -= 1
                # Last local lock released, release shared lock
                if not self.has_lock:
                    pid[:] = b'\x00\x00\x00\x00'
                    self.test_and_dec()
                #log.debug("After release: ", self.has_lock, int.from_bytes(pid, 'little'))
                return True
            else:
                return False

        def reset(self):
            # Risky
            lock = getattr(self.parent, self.lock_name)
            pid = getattr(self.parent, self.pid_name)
            lock[:] = b'\x00\x00'
            pid[:] = b'\x00\x00\x00\x00'
            self.has_lock = 0

        def status(self):
            lock = getattr(self.parent, self.lock_name)
            pid = getattr(self.parent, self.pid_name)
            return { 
                'lock': int.from_bytes(lock, 'little'),
                'has_lock': self.has_lock,
                'lock_remote': lock[0], 
                'pid': self.pid,
                'pid_remote': int.from_bytes(pid, 'little'),
            }

        def cleanup(self):
            del self.lock

        def print_status(self):
            import pprint
            pprint.pprint(self.status())

        def __repr__(self):
            return(f"{self.__class__.__name__} @{hex(id(self))} lock_name={self.lock_name!r}, has_lock={self.has_lock}, pid={self.pid})")

        def __enter__(self):
            self.aquire()

        def __exit__(self, type, value, traceback):
            self.release()

    __slots__ = 'name', 'control', 'buffer', 'lock', 'shared_lock', \
        'update_stream_position', 'full_dump_counter'

    def __init__(self, *args, name=None, buffer_size=10000, serializer=marshal, shared_lock=False, **kwargs):

        assert buffer_size < 2**32

        # Local position, ie. the last position we have processed from the stream
        self.update_stream_position  = 0

        # Local version counter for the full dumps, ie. if we find a higher version
        # remote, we need to load a full dump
        self.full_dump_counter       = 0

        # Small 300 bytes of shared memory where we store state information of our
        # update stream
        self.control = self.get_memory(create=True, name=name, size=300)

        self.name = self.control.name
        self.serializer = serializer

        # Actual stream buffer that contains marshalled data of changes to the dict
        self.buffer = self.get_memory(create=True, name=self.name + '_memory', size=buffer_size)

        # Pointer to the right memory position
        self.update_stream_position_remote = self.control.buf[ 0:  4]
        self.lock_pid_remote               = self.control.buf[ 4:  8]
        self.lock_remote                   = self.control.buf[ 8: 10]
        self.full_dump_counter_remote      = self.control.buf[10: 14]
        self.full_dump_memory_name_remote  = self.control.buf[20:275]

        # Local lock for all processes and threads created by the same interpreter
        if shared_lock:
            self.lock = self.SharedLock(self, 'lock_remote', 'lock_pid_remote')
        else:
            self.lock = multiprocessing.RLock()


        super().__init__(*args, **kwargs)

        # Load all data from shared memory
        self.apply_update()

        atexit.register(self.cleanup)

#    def __getstate__(self):
#        """Return state values to be pickled."""
#        return (self.name, self.data, self.update_stream_position, self.full_dump_counter)
#
#    def __setstate__(self, state):
#        """Restore state from the unpickled state values."""
#        self.name, self.data, self.update_stream_position, self.full_dump_counter = state

    def get_memory(self, *, create=True, name=None, size=0):
        """
        Attach an existing SharedMemory object with `name`.

        If `create` is True, create the object if it does not exist.
        """
        assert size > 0 or not create
        if name:
            # First try to attach to existing memory
            try:
                memory = multiprocessing.shared_memory.SharedMemory(name=name)
                memory.created_by_ultra = False
                log.debug('Attached shared memory: ', memory.name)
                return memory
            except FileNotFoundError as e: pass

        # No existing memory found
        if create:
            memory = multiprocessing.shared_memory.SharedMemory(create=True, size=size, name=name)
            # Remember that we have created this memory
            memory.created_by_ultra = True
            #log.debug('Created shared memory: ', memory.name)
            return memory

        raise Exception("Could not get memory")

    def dump(self):
        """ Dump the full dict into shared memory """
        old = bytes(self.full_dump_memory_name_remote).decode('utf-8').strip()
        with self.lock:
            self.apply_update()
            marshalled = self.serializer.dumps(self.data)
            #log.info("Dumped dict with {} elements to {} bytes", len(self), len(marshalled))
            full_dump_memory = self.get_memory(create=True, size=len(marshalled))
            #log.debug("Full dump memory: ", full_dump_memory)
            full_dump_memory.buf[:] = marshalled
            self.full_dump_memory_name_remote[:] = full_dump_memory.name.encode('utf-8').ljust(255)
            if old:
                self.unlink_by_name(old)
            full_dump_memory.close()
            self.full_dump_counter += 1
            current = int.from_bytes(self.full_dump_counter_remote, 'little')
            self.full_dump_counter_remote[:] = int(current + 1).to_bytes(4, 'little')
            # Reset the update_counter to zero as we have
            # just provided a fresh new full dump
            self.update_stream_position = 0
            self.update_stream_position_remote[:] = b'\x00\x00\x00\x00'

    def load(self, force=False):
        full_dump_counter = int.from_bytes(self.full_dump_counter_remote, 'little')
        #log.debug("Loading full dump local_counter={} remote_counter={}", self.full_dump_counter, full_dump_counter)
        if force or (self.full_dump_counter < full_dump_counter):
            name = bytes(self.full_dump_memory_name_remote).decode('utf-8').strip().strip('\x00')
            full_dump_memory = self.get_memory(create=False, name=name)
            full_dump = self.serializer.loads(full_dump_memory.buf)
            #log.debug("Got full dump: ", full_dump)
            self.data.clear()
            self.data.update(full_dump)
            self.full_dump_counter = full_dump_counter
            self.update_stream_position = 0
        else:
            log.warn("Cannot load full dump, no new data available")

    def append_update(self, key, item, delete=False):
        """ Append dict changes to shared memory stream """

        # If mode is 0, it means delete the key from the dict
        # If mode is 1, it means update the key
        mode = not delete
        marshalled = self.serializer.dumps((mode, key, item))
        length = len(marshalled)

        # TODO: Add also a shared lock in case some foreign process is also writing updates
        with self.lock:
            start_position = int.from_bytes(self.update_stream_position_remote, 'little')
            # 6 bytes for the header
            end_position = start_position + length + 6
            #log.debug("Pos: ", start_position, end_position)
            if end_position > self.buffer.size:
                #log.debug("Buffer is full")
                self.dump()
                return
        
            # Write header, 6 bytes
            # First byte is null byte
            self.buffer.buf[start_position:start_position+1]   = b'\x00'
            # Then comes 4 bytes of length of the body
            self.buffer.buf[start_position+1:start_position+5] = length.to_bytes(4, 'little')
            # Then another null bytes, end of header
            self.buffer.buf[start_position+5:start_position+6] = b'\x00'

            # Write body with the real data
            self.buffer.buf[start_position+6:end_position]    = marshalled

            # Inform others about it
            self.update_stream_position = end_position
            self.update_stream_position_remote[:] = end_position.to_bytes(4, 'little')
            #log.debug("Update counter increment from {} by {} to {}", start_position, len(marshalled), end_position)

    def apply_update(self):
        """ Apply dict changes from shared memory stream """

        if self.full_dump_counter < int.from_bytes(self.full_dump_counter_remote, 'little'):
            self.load(force=True)

        if self.update_stream_position < int.from_bytes(self.update_stream_position_remote, 'little'):
            # Our own position in the update stream
            pos = self.update_stream_position
            #log.debug("Apply update: stream position own={} remote={}", pos, int.from_bytes(self.update_stream_position_remote, 'little'))
            # Iterate over all updates until the start of the last update

            while pos < int.from_bytes(self.update_stream_position_remote, 'little'):
                # Read header
                # The first byte should be a null byte to introduce the header
                assert bytes(self.buffer.buf[pos:pos+1]) == b'\x00'
                pos += 1
                # Then comes 4 bytes of length
                length = int.from_bytes(bytes(self.buffer.buf[pos:pos+4]), 'little')
                pos += 4
                #log.debug("Found update, pos={} length={}", pos, length)
                assert bytes(self.buffer.buf[pos:pos+1]) == b'\x00'
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

    def update(self, other=None, *args, **kwargs):
        #log.debug("update")
        if other is not None:
            for k, v in other.items() if isinstance(other, collections.Mapping) else other:
                self[k] = v
        for k, v in kwargs.items():
            self[k] = v

    def __delitem__(self, key):
        #log.debug("__delitem__ {}", key)

        # Update our local copy
        self.data.__delitem__(key)

        self.append_update(key, b'', delete=True)
        # TODO: Do something if append_update() fails


    def __setitem__(self, key, item):
        #log.debug("__setitem__ {}, {}", key, item)

        # Update our local copy
        # It's important for the integrity to do this first
        self.data.__setitem__(key, item)

        # Append the update to the update stream
        self.append_update(key, item)
        # TODO: Do something if append_u int.from_bytes(self.update_stream_position_remote, 'little')pdate() fails

    def __getitem__(self, key):
        #log.debug("__getitem__ {}", key)
        self.apply_update()
        #log.debug("__getitem__ =>", self.data[key])
        return self.data[key]

    def __repr__(self):
        self.apply_update()
        return self.data.__repr__()

    def status(self):
        """ Internal debug helper to get the control state variables """
        ret = { attr: getattr(self, attr) for attr in self.__slots__ if hasattr(self, attr) }
        ret['update_stream_position_remote'] = int.from_bytes(self.update_stream_position_remote, 'little')
        ret['lock_pid_remote']               = int.from_bytes(self.lock_pid_remote, 'little')
        ret['lock_remote']                   = int.from_bytes(self.lock_remote, 'little')
        ret['lock']                          = self.lock
        ret['full_dump_counter_remote']      = int.from_bytes(self.full_dump_counter_remote, 'little')
        ret['full_dump_memory_name_remote']  = bytes(self.full_dump_memory_name_remote).decode('utf-8').strip('\x00').strip()
        return ret

    def print_status(self):
        """ Internal debug helper to pretty print the control state variables """
        import pprint
        pprint.pprint(self.status())

    def cleanup(self):
        #log.debug('Cleanup')

        if hasattr(self.lock, 'cleanup'):
            self.lock.cleanup()

        del self.update_stream_position_remote
        del self.lock_pid_remote
        del self.lock_remote
        del self.full_dump_counter_remote
        del self.full_dump_memory_name_remote

        self.control.close()
        self.buffer.close()

    def unlink(self, force=False):
        self.cleanup();
        if force or self.control.created_by_ultra:
            self.control.unlink()
            self.buffer.unlink()

    def unlink_by_name(self, name):
        try:
            memory = self.get_memory(create=False, name=name)
            #log.debug("Unlinking memory '{}'", name)
            memory.close()
            memory.unlink()
        except (KeyError, Exception) as e:
            pass



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
#    def __setitem__(self, key, item):
#        self.__dict__[key] = item
#
#    def __getitem__(self, key):
#        return self.__dict__[key]
#
#    def __repr__(self):
#        return repr(self.__dict__)
#
#    def __len__(self):
#        return len(self.__dict__)
#
#    def __delitem__(self, key):
#        del self.__dict__[key]
#
#    def clear(self):
#        return self.__dict__.clear()
#
#    def copy(self):
#        return self.__dict__.copy()
#
#    def has_key(self, k):
#        return k in self.__dict__
#
#    def update(self, *args, **kwargs):
#        return self.__dict__.update(*args, **kwargs)
#
#    def keys(self):
#        return self.__dict__.keys()
#
#    def values(self):
#        return self.__dict__.values()
#
#    def items(self):
#        return self.__dict__.items()
#
#    def pop(self, *args):
#        return self.__dict__.pop(*args)
#
#    def __cmp__(self, dict_):
#        return self.__cmp__(self.__dict__, dict_)
#
#    def __contains__(self, item):
#        return item in self.__dict__
#
#    def __iter__(self):
#        return iter(self.__dict__)
#
#    def __unicode__(self):
#        return unicode(repr(self.__dict__))
#
