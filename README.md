# UltraDict
Sychronized, streaming Python dictionary that uses shared memory as a backend

**Warning: This is an early hack. There are only few unit tests and so on. Maybe not stable!**

Features:
* Fast (compared to other sharing solutions)
* No running manager processes
* Works in spawn and fork context
* Safe locking between independent processes
* Tested with Python >= v3.8 on Linux and Windows
* Optional recursion for nested dicts

[![PyPI Package](https://img.shields.io/pypi/v/ultradict.svg)](https://pypi.org/project/ultradict)
[![Run Python Tests](https://github.com/ronny-rentner/UltraDict/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/ronny-rentner/UltraDict/actions/workflows/ci.yml)

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

Note that this comparison is not a real life workload. It was exectured on Debian Linux 11
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

We are factor 15 slower than a real, local dict, but way faster than using a Manager. If you need full read performance, you can access the underlying cache `ultra.data` directly and get almost original dict performance, of course at the cost of not having real-time updates anymore.
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

### Write performance

We are factor 100 slower than a real, local Python dict, but still factor 10 faster than using a Manager and much fast than Redis.

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

## Parameters

`Ultradict(*arg, name=None, buffer_size=10000, serializer=pickle, shared_lock=False, full_dump_size=None, auto_unlink=False, recurse=False, **kwargs)`

`name`: Name of the shared memory. A random name will be chosen if not set. If a name is given
a new shared memory space is created if it does not exist yet. Otherwise the existing shared
memory space is attached.

`buffer_size`: Size of the shared memory buffer used for streaming changes of the dict.

The buffer size limits the biggest change that can be streamed, so when you use large values or
deeply nested dicts you might need a bigger buffer. Otherwise, if the buffer is too small,
it will fall back to a full dump. Creating full dumps can be slow, depending on the size of your dict.

Whenever the buffer is full, a full dump will be created. A new shared memory is allocated just
big enough for the full dump. Afterwards the streaming buffer is reset.  All other users of the
dict will automatically load the full dump and continue streaming updates.

`serializer`: Use a different serialized from the default pickle, e. g. marshal, dill, json.
The module or object provided must support the methods *loads()* and *dumps()*

`shared_lock`: When writing to the same dict at the same time from multiple, independent processes,
they need a shared lock to synchronize and not overwrite each other's changes. Shared locks are slow.
They rely on the [atomics](https://github.com/doodspav/atomics) package for atomic locks. By default,
UltraDict will use a multiprocessing.RLock() instead which works well in fork context and is much faster.

`full_dump_size`: If set, uses a static full dump memory instead of dynamically creating it. This
might be necessary on Windows depending on your write behaviour. On Windows, the full dump memory goes
away if the process goes away that had created the full dump. Thus you must plan ahead which processes might
be writing to the dict and therefore creating full dumps.

`auto_unlink`: If True, the creator of the shared memory will automatically unlink the handle at exit so
it is not visible or accessible to new processes. All existing, still connected processes can continue to use the
dict.

`recurse`: If True, any nested dict objects will be automaticall wrapped in an `UltraDict` allowing transparent nested updates.

## Memory management

`UltraDict` uses shared memory buffers and those usually live is RAM. `UltraDict` does not use any management processes to keep track of buffers.  Also it cannot know when to free those shared memory buffers again because you might want the buffers to outlive the process that has created them.

By convention you should set the parameter `auto_unlink` to True for exactly one of the processes that is using the `UltraDict`. The first process
that is creating a certain `UltraDict` will automatically get the flag `auto_unlink=True` unless you explicitly set it to `False`.
When this process with the `auto_unlink=True` flag ends, it will try to unlink (free) all shared memory buffers.

A special case is the recursive mode using `recurse=True` parameter. This mode will use an additional internal `UltraDict` to keep
track of recursively nested `UltraDict` instances. All child `UltraDicts` will write to this register the names of the shared memory buffers
they are creating. This allows the buffers to outlive the processes and still being correctly cleanup up by at the end of the program.

**Buffer sizes and read performance:**

There are 3 cases that can occur when you read from an `UltraDict:

1. No new updates: This is the fastes cases. `UltraDict` was optimized for this case to find out as quickly as possible if there are no updates on the stream and then just return the desired data. If you want even better read perforamance you can directly access the underlying `data` attribute of your `UltraDict`, though at the cost of not getting real time updates anymore.

2. Streaming update: This is usually fast, depending on the size and amount of that data that was changed but not depending on the size of the whole `UltraDict`. Only the data that was actually changed has to be unserialized.

3. Full dump load: This can be slow, depending on the total size of your data. If your `UltraDict` is big it might take long to unserialize it.

Given the above 3 cases, you need to balance the size of your data and your write patterns with the streaming `buffer_size` of your UltraDict. If the streaming buffer is full, a full dump has to be created. Thus, if your full dumps are expensive due to their size, try to find a good `buffer_size` to avoid creating too many full dumps.

On the other hand, if for example you only change back and forth the value of one single key in your `UltraDict`, it might be useless to process a stream of all these back and forth changes. It might be much more efficient to simply do one full dump which might be very small because it only contains one key.






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
>>> import json
>>> ultra = UltraDict(serializer=json)

>>> # Close connection to shared memory; will return the data as a dict
>>> ultra.close()

>>> # Unlink all shared memory, it will not be visible to new processes afterwards
>>> ultra.unlink()

```

## Contributing

Contributions are always welcome!

