# UltraDict

Sychronized, streaming Python dictionary that uses shared memory as a backend

**Warning: This is an early hack. There are only few unit tests and so on. Maybe not stable!**

Features:
* Fast (compared to other sharing solutions)
* No running manager processes
* Works in spawn and fork context
* Safe locking between independent processes
* Tested with Python >= v3.8 on Linux, Windows and Mac
* Convenient, no setter or getters necessary
* Optional recursion for nested dicts

[![PyPI Package](https://img.shields.io/pypi/v/ultradict.svg)](https://pypi.org/project/ultradict)
[![Run Python Tests](https://github.com/ronny-rentner/UltraDict/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/ronny-rentner/UltraDict/actions/workflows/ci.yml)
[![Python >=3.8](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/github/license/ronny-rentner/UltraDict.svg)](https://github.com/ronny-rentner/UltraDict/blob/master/LICENSE.md)

## General Concept

`UltraDict` uses [multiprocessing.shared_memory](https://docs.python.org/3/library/multiprocessing.shared_memory.html#module-multiprocessing.shared_memory) to synchronize a dict between multiple processes.

It does so by using a *stream of updates* in a shared memory buffer. This is efficient because only changes have to be serialized and transferred.

If the buffer is full, `UltraDict` will automatically do a full dump to a new shared
memory space, reset the streaming buffer and continue to stream further updates. All users
of the `UltraDict` will automatically load full dumps and continue using
streaming updates afterwards.

## Issues

On Windows, if no process has any handles on the shared memory, the OS will gc all of the shared memory making it inaccessible for
future processes. To work around this issue you can currently set `full_dump_size` which will cause the creator
of the dict to set a static full dump memory of the requested size. This full dump memory will live as long as the creator lives.
This approach has the downside that you need to plan ahead for your data size and if it does not fit into the full dump memory, it will break.

## Alternatives

There are many alternatives:

 * [multiprocessing.Manager](https://docs.python.org/3/library/multiprocessing.html#managers)
 * [shared-memory-dict](https://github.com/luizalabs/shared-memory-dict)
 * [mpdict](https://github.com/gatopeich/mpdict)
 * Redis
 * Memcached

## How to use?

### Simple

In one Python REPL:
```python
Python 3.9.2 on linux
>>>
>>> from UltraDict import UltraDict
>>> ultra = UltraDict({ 1:1 }, some_key='some_value')
>>> ultra
{1: 1, 'some_key': 'some_value'}
>>>
>>> # We need the shared memory name in the other process.
>>> ultra.name
'psm_ad73da69'
```

In another Python REPL:
```python
Python 3.9.2 on linux
>>>
>>> from UltraDict import UltraDict
>>> # Connect to the shared memory with the name above
>>> other = UltraDict(name='psm_ad73da69')
>>> other
{1: 1, 'some_key': 'some_value'}
>>> other[2] = 2
```

Back in the first Python REPL:
```python
>>> ultra[2]
2
```

### Nested

In one Python REPL:
```python
Python 3.9.2 on linux
>>>
>>> from UltraDict import UltraDict
>>> ultra = UltraDict(recurse=True)
>>> ultra['nested'] = { 'counter': 0 }
>>> type(ultra['nested'])
<class 'UltraDict.UltraDict'>
>>> ultra.name
'psm_0a2713e4'
```

In another Python REPL:
```python
Python 3.9.2 on linux
>>>
>>> from UltraDict import UltraDict
>>> other = UltraDict(name='psm_0a2713e4')
>>> other['nested']['counter'] += 1
```

Back in the first Python REPL:
```python
>>> ultra['nested']['counter']
1
```

## Performance comparison

Lets compare a classical Python dict, UltraDict, multiprocessing.Manager and Redis.

Note that this comparison is not a real life workload. It was executed on Debian Linux 11
with Redis installed from the Debian package and with the default configuration of Redis.

```python
Python 3.9.2 on linux
>>>
>>> from UltraDict import UltraDict
>>> ultra = UltraDict()
>>> for i in range(10_000): ultra[i] = i
...
>>> len(ultra)
10000
>>> ultra[500]
500
>>> # Now let's do some performance testing
>>> import multiprocessing, redis, timeit
>>> orig = dict(ultra)
>>> len(orig)
10000
>>> orig[500]
500
>>> managed = multiprocessing.Manager().dict(orig)
>>> len(managed)
10000
>>> r = redis.Redis()
>>> r.flushall()
>>> r.mset(orig)
```

### Read performance

>>>
```python
>>> timeit.timeit('orig[1]', globals=globals()) # original
0.03832335816696286
>>> timeit.timeit('ultra[1]', globals=globals()) # UltraDict
0.5248982920311391
>>> timeit.timeit('managed[1]', globals=globals()) # Manager
40.85506196087226
>>> timeit.timeit('r.get(1)', globals=globals()) # Redis
49.3497632863
>>> timeit.timeit('ultra.data[1]', globals=globals()) # UltraDict data cache
0.04309639008715749
```

We are factor 15 slower than a real, local dict, but way faster than using a Manager. If you need full read performance, you can access the underlying cache `ultra.data` directly and get almost original dict performance, of course at the cost of not having real-time updates anymore.

### Write performance

```python
>>> min(timeit.repeat('orig[1] = 1', globals=globals())) # original
0.028232071083039045
>>> min(timeit.repeat('ultra[1] = 1', globals=globals())) # UltraDict
2.911152713932097
>>> min(timeit.repeat('managed[1] = 1', globals=globals())) # Manager
31.641707635018975
>>> min(timeit.repeat('r.set(1, 1)', globals=globals())) # Redis
124.3432381930761
```

We are factor 100 slower than a real, local Python dict, but still factor 10 faster than using a Manager and much fast than Redis.

### Testing performance

There is an automated performance test in `tests/performance/performance.py`. If you run it, you get something like this:

```bash
python ./tests/performance/performance.py

Testing Performance with 1000000 operations each

Redis (writes) = 24,351 ops per second
Redis (reads) = 30,466 ops per second
Python MPM dict (writes) = 19,371 ops per second
Python MPM dict (reads) = 22,290 ops per second
Python dict (writes) = 16,413,569 ops per second
Python dict (reads) = 16,479,191 ops per second
UltraDict (writes) = 479,860 ops per second
UltraDict (reads) = 2,337,944 ops per second
UltraDict (shared_lock=True) (writes) = 41,176 ops per second
UltraDict (shared_lock=True) (reads) = 1,518,652 ops per second

Ranking:
  writes:
    Python dict = 16,413,569 (factor 1.0)
    UltraDict = 479,860 (factor 34.2)
    UltraDict (shared_lock=True) = 41,176 (factor 398.62)
    Redis = 24,351 (factor 674.04)
    Python MPM dict = 19,371 (factor 847.33)
  reads:
    Python dict = 16,479,191 (factor 1.0)
    UltraDict = 2,337,944 (factor 7.05)
    UltraDict (shared_lock=True) = 1,518,652 (factor 10.85)
    Redis = 30,466 (factor 540.9)
    Python MPM dict = 22,290 (factor 739.31)
```

I am interested in extending the performance testing to other solutions (like sqlite, memcached, etc.) and to more complex use cases with multiple processes working in parallel.

## Parameters

`Ultradict(*arg, name=None, create=None, buffer_size=10000, serializer=pickle, shared_lock=False, full_dump_size=None, auto_unlink=None, recurse=False, recurse_register=None, **kwargs)`

`name`: Name of the shared memory. A random name will be chosen if not set. By default, if a name is given
a new shared memory space is created if it does not exist yet. Otherwise the existing shared
memory space is attached.

`create`: Can be either `True` or `False` or `None`. If set to `True`, a new UltraDict will be created
and an exception is thrown if one exists already with the given name. If kept at the default value `None`,
either a new UltraDict will be created if the name is not taken or an existing UltraDict will be attached.

Setting `create=True` does ensure not accidentally attaching to an existing UltraDict that might be left over.

`buffer_size`: Size of the shared memory buffer used for streaming changes of the dict.
The buffer size limits the biggest change that can be streamed, so when you use large values or
deeply nested dicts you might need a bigger buffer. Otherwise, if the buffer is too small,
it will fall back to a full dump. Creating full dumps can be slow, depending on the size of your dict.

Whenever the buffer is full, a full dump will be created. A new shared memory is allocated just
big enough for the full dump. Afterwards the streaming buffer is reset.  All other users of the
dict will automatically load the full dump and continue streaming updates.

(Also see the section [Memory management](#memory-management) below!)

`serializer`: Use a different serialized from the default pickle, e. g. marshal, dill, jsons.
The module or object provided must support the methods *loads()* and *dumps()*

`shared_lock`: When writing to the same dict at the same time from multiple, independent processes,
they need a shared lock to synchronize and not overwrite each other's changes. Shared locks are slow.
They rely on the [atomics](https://github.com/doodspav/atomics) package for atomic locks. By default,
UltraDict will use a multiprocessing.RLock() instead which works well in fork context and is much faster.

(Also see the section [Locking](#locking) below!)

`full_dump_size`: If set, uses a static full dump memory instead of dynamically creating it. This
might be necessary on Windows depending on your write behaviour. On Windows, the full dump memory goes
away if the process goes away that had created the full dump. Thus you must plan ahead which processes might
be writing to the dict and therefore creating full dumps.

`auto_unlink`: If True, the creator of the shared memory will automatically unlink the handle at exit so
it is not visible or accessible to new processes. All existing, still connected processes can continue to use the
dict.

`recurse`: If True, any nested dict objects will be automatically wrapped in an `UltraDict` allowing transparent nested updates.

`recurse_register`: Has to be either the `name` of an UltraDict or an UltraDict instance itself. Will be used internally to keep track of dynamically created, recursive UltraDicts for proper cleanup when using `recurse=True`. Usually does not have to be set by the user.

## Memory management

`UltraDict` uses shared memory buffers and those buffers usually 'live' in RAM, but `UltraDict` does not use any management processes to keep track of the buffers. Furthermore, it cannot know when to free those shared memory buffers because you might want the buffers to outlive the process that has created them.

By convention you should set the parameter `auto_unlink` to True for exactly one of the processes that is using the `UltraDict`. The first process
that is creating a certain `UltraDict` will automatically get the flag `auto_unlink=True` unless you explicitly set it to `False`.
When this process with the `auto_unlink=True` flag ends, it will try to unlink (free) all shared memory buffers.

A special case is the recursive mode using `recurse=True` parameter. This mode will use an additional internal register to keep
track of recursively nested `UltraDict` instances. All child `UltraDicts` will write to this internal register the names of the shared memory buffers
they are creating. This allows the buffers to outlive the processes and still being correctly cleaned up at the end of the program.

**Buffer sizes and read performance:**

There are 3 cases that can occur when you read from an `UltraDict:

1. No new updates: This is the fastes cases. `UltraDict` was optimized for this case to find out as quickly as possible if there are no updates on the stream and then just return the desired data. If you want even better read perforamance you can directly access the underlying `data` attribute of your `UltraDict`, though at the cost of not getting real time updates anymore.

2. Streaming update: This is usually fast, depending on the size and amount of that data that was changed but not depending on the size of the whole `UltraDict`. Only the data that was actually changed has to be unserialized.

3. Full dump load: This can be slow, depending on the total size of your data. If your `UltraDict` is big it might take long to unserialize it.

Given the above 3 cases, you need to balance the size of your data and your write patterns with the streaming `buffer_size` of your UltraDict. If the streaming buffer is full, a full dump has to be created. Thus, if your full dumps are expensive due to their size, try to find a good `buffer_size` to avoid creating too many full dumps.

On the other hand, if for example you only change back and forth the value of one single key in your `UltraDict`, it might be useless to process a stream of all these back and forth changes. It might be much more efficient to simply do one full dump which might be very small because it only contains one key.

## Locking

Every UltraDict instance has a `lock` attribute which is either a [multiprocessing.RLock](https://docs.python.org/3/library/multiprocessing.html#multiprocessing.RLock) or an `UltraDict.SharedLock` if you set `shared_lock=True` when creating the UltraDict.

RLock is the fastest locking method that is used by default but you can only use it if you fork your child processes. Forking is the default on Linux systems.

In contrast, on Windows systems, forking is not available and Python will automatically use the spawn method when creating child processes. You should then use the parameter `shared_lock=True` when using UltraDict. This requires that the external [atomics](https://github.com/doodspav/atomics) package is installed.

### How to use the locking?
```python
ultra = UltraDict(shared_lock=True)

with ultra.lock:
	ultra['counter']++

# The same as above with all default parameters
with ultra.lock(timeout=None, block=True, steal=False, sleep_time=0.000001):
	ultra['counter']++

# Busy wait, will result in 99 % CPU usage, fastest option
# Ideally number of processes using the UltraDict should be < number of CPUs
with ultra.lock(sleep_time=0):
	ultra['counter']++

try:
	result = ultra.lock.acquire(block=False)
	ultra.lock.release()
except UltraDict.Exceptions.CannotAcquireLock as e:
	print(f'Process with PID {e.blocking_pid} is holding the lock')

try:
	with ultra.lock(timeout=1.5):
		ultra['counter']++
except UltraDict.Exceptions.CannotAcquireLockTimeout:
	print('Stale lock?')

with ultra.lock(timeout=1.5, steal_after_timeout=True):
	ultra['counter']++

```

## Explicit cleanup

Sometimes, when your program crashes, no cleanup happens and you might have a corrupted shared memeory buffer that only goes away if you manually delete it.

On Linux/Unix systems, those buffers usually live in a memory based filesystem in the folder `/dev/shm`. You can simply delete the files there.

Another way to do this in code is like this:
```python
# Unlink both shared memory buffers possibly used by UltraDict
name = 'my-dict-name'
UltraDict.unlink_by_name(name, ignore_errors=True)
UltraDict.unlink_by_name(f'{name}_memory', ignore_errors=True)
```

## Advanced usage

See [examples](/examples) folder

```python
>>> ultra = UltraDict({ 'init': 'some initial data' }, name='my-name', buffer_size=100_000)
>>> # Let's use a value with 100k bytes length.
>>> # This will not fit into our 100k bytes buffer due to the serialization overhead.
>>> ultra[0] = ' ' * 100_000
>>> ultra.print_status()
{'buffer': SharedMemory('my-name_memory', size=100000),
 'buffer_size': 100000,
 'control': SharedMemory('my-name', size=1000),
 'full_dump_counter': 1,
 'full_dump_counter_remote': 1,
 'full_dump_memory': SharedMemory('psm_765691cd', size=100057),
 'full_dump_memory_name_remote': 'psm_765691cd',
 'full_dump_size': None,
 'full_dump_static_size_remote': <memory at 0x7fcbf5ca6580>,
 'lock': <RLock(None, 0)>,
 'lock_pid_remote': 0,
 'lock_remote': 0,
 'name': 'my-name',
 'recurse': False,
 'recurse_remote': <memory at 0x7fcbf5ca6700>,
 'serializer': <module 'pickle' from '/usr/lib/python3.9/pickle.py'>,
 'shared_lock_remote': <memory at 0x7fcbf5ca6640>,
 'update_stream_position': 0,
 'update_stream_position_remote': 0}
```

Note: All status keys ending with `_remote` are stored in the control shared memory space and shared across processes.

Other things you can do:
```python
>>> # Create a full dump
>>> ultra.dump()

>>> # Load latest full dump if one is available
>>> ultra.load()

>>> # Show statistics
>>> ultra.print_status()

>>> # Force load of latest full dump, even if we had already processed it.
>>> # There might also be streaming updates available after loading the full dump.
>>> ultra.load(force=True)

>>> # Apply full dump and stream updates to
>>> # underlying local dict, this is automatically
>>> # called by accessing the UltraDict in any usual way,
>>> # but can be useful to call after a forced load.
>>> ultra.apply_update()

>>> # Access underlying local dict directly for maximum performance
>>> ultra.data

>>> # Use any serializer you like, given it supports the loads() and dumps() methods
>>> import jsons
>>> ultra = UltraDict(serializer=jsons)

>>> # Close connection to shared memory; will return the data as a dict
>>> ultra.close()

>>> # Unlink all shared memory, it will not be visible to new processes afterwards
>>> ultra.unlink()

```

## Contributing

Contributions are always welcome!
