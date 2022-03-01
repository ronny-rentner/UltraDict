# UltraDict
Shared, streaming Python dict

Features:
* Fast
* No running manager processes
* Works in spawn and fork context
* Tested with Python >= v3.9 on Linux and Windows

## General Concept

`UltraDict` uses [multiprocessing.shared_memory](https://docs.python.org/3/library/multiprocessing.shared_memory.html#module-multiprocessing.shared_memory) to synchronize a dict data between multiple processes.

It does so by using a *stream of updates* in a shared memory buffer. This is efficient because only changes have to be serialized.

If the buffer is full, `UltraDict` will automatically do a full dump once to a new shared
memory space, reset the streaming buffer and continue to stream future updates. All users
of the `UltraDict` will automatically receive all full dumps and streaming updates.

## Issues

On Windows, if no process has any handles on the shared memory, the OS will gc all of the shared memory making it inaccessible for
future processes. This is a bug in Python. 

## Alternatives

There are many alternatives:

 * [multiprocessing.Manager](https://docs.python.org/3/library/multiprocessing.html#managers)
 * [shared-memory-dict](https://github.com/luizalabs/shared-memory-dict)
 * Redis
 * Memcached

## How to use?

In one process:

```python
Python 3.9.2 on linux
>>> 
>>> from UltraDict import UltraDict
>>> ultra = UltraDict({ 1:1 }, some_key='some_value')
>>> ultra
{1: 1, 'some_key': 'some_value'}
>>> orig = dict({ 1:1 }, some_key='some_value')
>>> orig
{1: 1, 'some_key': 'some_value'}
>>>
>>> # We need the shared memory name in the other process.
>>> ultra.name
'psm_ad73da69'
```

In another process:

```python
Python 3.9.2 on linux
>>> 
>>> from UltraDict import UltraDict
>>> # Connect to the shared memory with the name above
>>> ultra = UltraDict(name='psm_ad73da69')
>>> ultra
{1: 1, 'some_key': 'some_value'}
```

## Performance comparison

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
>>> # Now let's to some performance testing
>>> import multiprocessing, timeit
>>> orig = dict(ultra)
>>> len(orig)
10000
>>> orig[500]
500
>>> managed = multiprocessing.Manager().dict(orig)
>>> len(managed)
10000
```

### Read performance

```python
>>> timeit.timeit('orig[1]', globals=globals())
0.03503723500762135
>>>
>>> timeit.timeit('ultra[1]', globals=globals())
0.380401570990216
>>>
>>> timeit.timeit('managed[1]', globals=globals())
15.848494678968564
>>>
>>> # We are factor 10 slower than a real, local dict,
>>> # but way faster than using a Manager
>>>
>>> # If you need full read performance, you can access the underlying
>>> # cache directly and get almost original dict performance,
>>> # of course at the cost of not having real-time updates anymore.
>>>
>>> timeit.timeit('ultra.data[1]', globals=globals())
0.047667117964010686
```

### Write performance

```python
>>> timeit.timeit('orig[1] = 1', globals=globals())
0.02869905502302572
>>>
>>> timeit.timeit('ultra[1] = 1', globals=globals())
2.259694856009446
>>>
>>> timeit.timeit('managed[1] = 1', globals=globals())
16.352361536002718
>>>
>>> # We are factor 100 slower than a real, local dict,
>>> # but still way faster than using a Manager
```

## Parameters

`Ultradict(*arg, name=None, buffer_size=10000, serializer=marshal, shared_lock=False, full_dump_size=None, **kwargs)`

`name`: Name of the shared memory. A random name will be chosen if not set. If a name is given
a new shared memory space is created if it does not exist yet. Otherwise the existing shared
memory space is attached.

`buffer_size`: Size of the shared memory buffer used for streaming changed of the dict.

The buffer size limits the biggest change that can be streamed, so when you use large values or
deeply nested dicts you might need a bigger buffer. Otherwise, if the buffer is too small,
it will fall back to a full dump.

Whenever the buffer is full, a full dump will be executed. A new shared memory is allocated just
big enough for the full dump. Afterwards the streaming buffer is reset.  All other user of the
dict will automatically read the full dump and continue with the reset streaming buffer.


## Advanced usage

See `example.py` and `example_fork.py`

```python
>>> ultra = UltraDict({ 'init': 'some initial data' }, name='my-name', buffer_size=100_000)
>>> # Lets use a value with 100.000 bytes length, this will not fit into our 100k bytes buffer
>>> # due to the serialization overhead.
>>> ultra[0] = ' ' * 100_000
>>> ultra.print_status()
{'buffer': SharedMemory('my-name_memory', size=100000),
 'control': SharedMemory('my-name', size=300),
 'full_dump_counter': 1,
 'full_dump_counter_remote': 1,
 'full_dump_lock_pid_remote': 0,
 'full_dump_lock_remote': 0,
 'full_dump_memory_name_remote': 'psm_a99c3a83',
 'lock': <Lock(owner=None)>,
 'lock_pid_remote': 0,
 'lock_remote': 0,
 'name': 'my-name',
 'shared_lock': SharedLock @0x7f0828864040 lock_name='full_dump_lock_remote', has_lock=0, pid=455581),
 'update_stream_position': 0,
 'update_stream_position_remote': 0}
```

Other things you can do:
```python
>>> # Load latest full dump if one is available
>>> ultra.load()

>>> # Show statistics
>>> ultra.print_status()

>>> # Force load of latest full dump, even if we had already processed it.
>>> # There might also be streaming updates available after loading the full dump.
>>> ultra.load(force=True)

>>> # Apply full dump and stream updates to
>>> # underlying local dict, this is automatically
>>> # called when you normally access the UltraDict,
>>> # but can be useful to call after a forced load.
>>> ultra.apply_update()

>>> # Access uderlying local dict directly
>>> ultra.data

>>> # Use any serialize you like, given it supports the loads() and dumps() methods
>>> import pickle 
>>> ultra = UltraDict(serializer=pickle)



```
