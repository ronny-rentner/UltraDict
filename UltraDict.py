#
# UltraDict
#
# A sychronized, streaming Python dictionary that uses shared memory as a backend
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

import multiprocessing, multiprocessing.shared_memory
import collections, atexit, enum, time, marshal, sys, pickle

try:
    # Needed for the shared locked
    import atomics
except:
    pass

try:
    from utils import log
except:
    import logging as log

#def profile(arg):
#    return arg

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

#More details at: https://bugs.python.org/issue38119
remove_shm_from_resource_tracker()




class UltraDict(collections.UserDict, dict):

    class SharedLock():
        """
        Lock stored in shared_memory to provide an additional layer of protection,
        e.g. when using spawned processes.

        Internally uses atomics package of patomics for atomic locking.

        This is needed if you write to the shared memory with independent processes.
        """

        __slots__ = 'parent', 'has_lock', 'lock_name', 'pid', 'pid_name', 'pid_remote', 'ctx', 'lock_atomic'

        def __init__(self, parent, lock_name, pid_name):
            self.parent = parent
            self.has_lock = 0
            self.lock_name = lock_name
            self.pid_name = pid_name
            self.pid = multiprocessing.current_process().pid
            # Memoryview
            self.pid_remote = getattr(self.parent, self.pid_name)
            self.ctx = atomics.atomicview(buffer=getattr(self.parent, self.lock_name)[0:1], atype=atomics.BYTES)
            self.lock_atomic = self.ctx.__enter__()

        #@profile
        def acquire(self):
            #log.debug("Acquire lock")
            #lock = getattr(self.parent, self.lock_name)
            counter = 0

            # If we already own the lock, just increment our counter
            if self.has_lock:
                #log.debug("Already got lock", self.has_lock)
                self.has_lock += 1
                ipid = int.from_bytes(self.pid_remote, 'little')
                if ipid != self.pid:
                    raise Exception("Error, '{}' stole our lock '{}'".format(ipid, self.pid))

                return True

            # We try to get the lock and busy wait until it's ready
            while True:
                # We need both, the shared lock to be False and the lock_pid to be 0
                if self.test_and_inc():
                    self.has_lock += 1

                    ipid = int.from_bytes(self.pid_remote, 'little')
                    #log.debug("Got lock", self.has_lock, self.pid, ipid)

                    # If nobody owns the lock, the pid should be zero
                    assert ipid == 0
                    self.pid_remote[:] = self.pid.to_bytes(4, 'little')
                    return True
                else:
                    # Oh no, already locked by someone else
                    # TODO: Busy wait? Timeout?
                    counter += 1
                    if counter > 100_000:
                        raise Exception("Failed to acquire lock: ", counter)

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
            self.ctx.__exit__(None, None, None)
            del self.pid_remote
            del self.lock_atomic
            del self.ctx

        def print_status(self):
            import pprint
            pprint.pprint(self.status())

        def __repr__(self):
            return(f"{self.__class__.__name__} @{hex(id(self))} lock_name={self.lock_name!r}, has_lock={self.has_lock}, pid={self.pid})")

        __enter__ = acquire
        __exit__ = release

    __slots__ = 'name', 'control', 'buffer', 'buffer_size', 'lock', 'shared_lock', \
        'update_stream_position', 'update_stream_position_remote', \
        'full_dump_counter', 'full_dump_memory', 'full_dump_size', \
        'serializer', \
        'lock_pid_remote', \
        'lock_remote', \
        'full_dump_counter_remote', \
        'full_dump_static_size_remote', \
        'shared_lock_remote', \
        'recurse_remote', \
        'full_dump_memory_name_remote', \
        'data', 'recurse'

    def __init__(self, *args, name=None, buffer_size=10000, serializer=pickle, shared_lock=False, full_dump_size=None,
            auto_unlink=True, recurse=False, **kwargs):

        if sys.platform == 'win32':
            buffer_size = -(buffer_size // -4096) * 4096
            if full_dump_size:
                full_dump_size = -(full_dump_size // -4096) * 4096

        assert buffer_size < 2**32

        # Local position, ie. the last position we have processed from the stream
        self.update_stream_position  = 0

        # Local version counter for the full dumps, ie. if we find a higher version
        # remote, we need to load a full dump
        self.full_dump_counter       = 0

        # Small 300 bytes of shared memory where we store the runtime state
        # of our update stream
        self.control = self.get_memory(create=True, name=name, size=1000)

        # Memoryviews to the right buffer position in self.control
        self.update_stream_position_remote = self.control.buf[ 0:  4]
        self.lock_pid_remote               = self.control.buf[ 4:  8]
        self.lock_remote                   = self.control.buf[ 8: 10]
        self.full_dump_counter_remote      = self.control.buf[10: 14]
        self.full_dump_static_size_remote  = self.control.buf[14: 18]
        self.shared_lock_remote            = self.control.buf[18: 19]
        self.recurse_remote                = self.control.buf[19: 20]
        self.full_dump_memory_name_remote  = self.control.buf[20:275]

        self.name = self.control.name

        self.serializer = serializer

        # Actual stream buffer that contains marshalled data of changes to the dict
        self.buffer = self.get_memory(create=True, name=self.name + '_memory', size=buffer_size)
        self.buffer_size = self.buffer.size

        self.full_dump_memory = None

        # Dynamic full dump memory handling
        # Warning: Issues on Windows when the process ends that has created the full dump memory
        self.full_dump_size = None

        if hasattr(self.control, 'created_by_ultra'):
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
            # Check if we have a fixed size full dump memory
            size = int.from_bytes(self.full_dump_static_size_remote, 'little')

            shared_lock = self.shared_lock_remote[0:1] == b'1'
            recurse = self.recurse_remote[0:1] == b'1'

            # Got existing size of full dump memory, that must mean it's static size
            # and we should attach to it
            if size > 0:
                self.full_dump_size = size
                self.full_dump_memory = self.get_memory(create=False, name=self.name + '_full')
            

        # Local lock for all processes and threads created by the same interpreter
        if shared_lock:
            self.lock = self.SharedLock(self, 'lock_remote', 'lock_pid_remote')
        else:
            self.lock = multiprocessing.RLock()

        self.recurse = recurse

        super().__init__(*args, **kwargs)

        # Load all data from shared memory
        self.apply_update()

        if auto_unlink:
            atexit.register(self.unlink)
        else:
            atexit.register(self.cleanup)

    def __reduce__(self):
        from functools import partial
        return (partial(self.__class__, name=self.name), ())

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
                #log.debug('Attached shared memory: ', memory.name)
                
                # TODO: Load config from leader

                return memory
            except FileNotFoundError as e: pass

        # No existing memory found
        if create:
            memory = multiprocessing.shared_memory.SharedMemory(create=True, size=size, name=name)
            #multiprocessing.resource_tracker.unregister(memory._name, 'shared_memory')
            # Remember that we have created this memory
            memory.created_by_ultra = True
            #log.debug('Created shared memory: ', memory.name)
            return memory  

        raise Exception("Could not get memory: ", name)

    #@profile
    def dump(self):
        """ Dump the full dict into shared memory """

        old = bytes(self.full_dump_memory_name_remote).decode('utf-8').strip()
        with self.lock:
            self.apply_update()
            marshalled = self.serializer.dumps(self.data)
            length = len(marshalled)
            #log.info("Dumped dict with {} elements to {} bytes", len(self), len(marshalled))

            # If we don't have a fixed size, let's create full dump memory dynamically
            # TODO: This causes issues on Windows because the memory is not persistant
            if self.full_dump_size and self.full_dump_memory:
                full_dump_memory = self.full_dump_memory
            else:
                # Dynamic full dump memory
                full_dump_memory = self.get_memory(create=True, size=length + 6)
                self.full_dump_memory_name_remote[:] = full_dump_memory.name.encode('utf-8').ljust(255)

            # On Windows, we need to keep a reference to the full dump memory,
            # otherwise it's destoryed
            self.full_dump_memory = full_dump_memory

            #log.debug("Full dump memory: ", full_dump_memory)

            if length + 6 > full_dump_memory.size:
                raise Exception('Full dump memory too small for full dump: needed={} got={}'.format(length + 6, full_dump_memory.size))

            # Write header, 6 bytes
            # First byte is null byte
            full_dump_memory.buf[0:1] = b'\x00'
            # Then comes 4 bytes of length of the body
            full_dump_memory.buf[1:5] = length.to_bytes(4, 'little')
            # Then another null bytes, end of header
            full_dump_memory.buf[5:6] = b'\x00'

            # Write body
            full_dump_memory.buf[6:6+length] = marshalled

            # If the old memory was dynamically created, delete it
            if old and old != full_dump_memory.name and not self.full_dump_size:
                self.unlink_by_name(old)
            
            # On Windows, if we close it, it cannot be read anymore by anyone else.
            if not self.full_dump_size and sys.platform != 'win32':
                full_dump_memory.close()

            self.full_dump_counter += 1
            current = int.from_bytes(self.full_dump_counter_remote, 'little')
            self.full_dump_counter_remote[:] = int(current + 1).to_bytes(4, 'little')
            # Reset the update_counter to zero as we have
            # just provided a fresh new full dump
            self.update_stream_position = 0
            self.update_stream_position_remote[:] = b'\x00\x00\x00\x00'

            return full_dump_memory

    #@profile
    def load(self, force=False):
        full_dump_counter = int.from_bytes(self.full_dump_counter_remote, 'little')
        #log.debug("Loading full dump local_counter={} remote_counter={}", self.full_dump_counter, full_dump_counter)
        if force or (self.full_dump_counter < full_dump_counter):
            name = bytes(self.full_dump_memory_name_remote).decode('utf-8').strip().strip('\x00')
            if self.full_dump_size and self.full_dump_memory:
                full_dump_memory = self.full_dump_memory
            else:
                full_dump_memory = self.get_memory(create=False, name=name)
            buf = full_dump_memory.buf
            assert buf
            pos = 0
            # Read header
            # The first byte should be a null byte to introduce the header
            assert bytes(buf[pos:pos+1]) == b'\x00'
            pos += 1
            # Then comes 4 bytes of length
            length = int.from_bytes(bytes(buf[pos:pos+4]), 'little')
            pos += 4
            #log.debug("Found update, pos={} length={}", pos, length)
            assert bytes(buf[pos:pos+1]) == b'\x00'
            pos += 1
            # Unserialize the update data, we expect a tuple of key and value
            full_dump = self.serializer.loads(bytes(buf[pos:pos+length]))
            #log.debug("Got full dump: ", full_dump)

            self.data.clear()
            self.data.update(full_dump)
            self.full_dump_counter = full_dump_counter
            self.update_stream_position = 0
            if sys.platform != 'win32' and not self.full_dump_memory:
                full_dump_memory.close()
        else:
            log.warn("Cannot load full dump, no new data available")

    #@profile
    def append_update(self, key, item, delete=False):
        """ Append dict changes to shared memory stream """

        # If mode is 0, it means delete the key from the dict
        # If mode is 1, it means update the key
        mode = not delete
        marshalled = self.serializer.dumps((mode, key, item))
        length = len(marshalled)

        with self.lock:
            start_position = int.from_bytes(self.update_stream_position_remote, 'little')
            # 6 bytes for the header
            end_position = start_position + length + 6
            #log.debug("Pos: ", start_position, end_position, self.buffer_size)
            if end_position > self.buffer_size:
                #log.debug("Buffer is full")
                # This is necessary in case a load() and dump() is necessary
                self.apply_update()
                self.data.__setitem__(key, item)
                self.dump()
                return
        
            marshalled = b'\x00' + length.to_bytes(4, 'little') + b'\x00' + marshalled

            # Write body with the real data
            self.buffer.buf[start_position:end_position] = marshalled

            # Inform others about it
            self.update_stream_position = end_position
            self.update_stream_position_remote[:] = end_position.to_bytes(4, 'little')
            #log.debug("Update counter increment from {} by {} to {}", start_position, len(marshalled), end_position)
        return True

    #@profile
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
            for k, v in other.items() if isinstance(other, collections.abc.Mapping) else other:
                self[k] = v
        for k, v in kwargs.items():
            self[k] = v

    def __delitem__(self, key):
        #log.debug("__delitem__ {}", key)
        self.apply_update()

        # Update our local copy
        self.data.__delitem__(key)

        self.append_update(key, b'', delete=True)
        # TODO: Do something if append_update() fails

    def __setitem__(self, key, item):
        #log.debug("__setitem__ {}, {}", key, item)
        self.apply_update()

        if self.recurse:
            if type(item) == dict:
                item = UltraDict(item, recurse=True)

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

    def has_key(self, key):
        self.apply_update()
        return key in self.data

    def __contains__(self, key):
        self.apply_update()
        return key in self.data

    def __len__(self):
        self.apply_update()
        return len(self.data)

    def __repr__(self):
        self.apply_update()
        return self.data.__repr__()

    def status(self):
        """ Internal debug helper to get the control state variables """
        ret = { attr: getattr(self, attr) for attr in self.__slots__ if hasattr(self, attr) and attr != 'data' }

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
        del self.full_dump_static_size_remote
        del self.shared_lock_remote
        del self.recurse_remote
        del self.full_dump_counter_remote
        del self.full_dump_memory_name_remote

        self.control.close()
        self.buffer.close()

        if self.full_dump_memory:
            self.full_dump_memory.close()

        # No further cleanup on Windows, it will break everything
        #if sys.platform == 'win32':
        #    return

        #Only do cleanup once
        atexit.unregister(self.cleanup)

    def keys(self):
        self.apply_update()
        return self.data.keys()

    def unlink(self, force=False):
        full_dump_name = bytes(self.full_dump_memory_name_remote).decode('utf-8').strip().strip('\x00')

        self.cleanup();

        if force or hasattr(self.control, 'created_by_ultra'):
            self.control.unlink()
            self.buffer.unlink()
            self.unlink_by_name(full_dump_name)


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
