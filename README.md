# UltraDict
Shared, streaming Python dict

Tested with Python >= v3.9

## General Concept

`UltraDict` uses [multiprocessing.shared memeory](https://docs.python.org/3/library/multiprocessing.shared_memory.html#module-multiprocessing.shared_memory) to synchronize dictionary data between multiple processes using the same data.

It does so by using a stream of updates in a shared memory buffer.

If the buffer is full, `UltraDict` will resort to do a full dump once,
reset the streaming buffer and continue to stream future updates after the full dump.

## Alternatives

There are many alternatives:

 * [multiprocessing.Manager](https://docs.python.org/3/library/multiprocessing.html#managers)
 * [shared-memoery-dict](https://github.com/luizalabs/shared-memory-dict)
 * Redis
 * Memcached

## How to use?

```python
Python 3.9.2 (default, Feb 28 2021, 17:03:44) 
[GCC 10.2.1 20210110] on linux
Type "help", "copyright", "credits" or "license" for more information.
>>> 
>>> from UltraDict import UltraDict
>>> ultra = UltraDict({ 1:1 }, some_key='some_value')
>>> ultra
{1: 1, 'some_key': 'some_value'}
>>> orig = dict({ 1:1 }, some_key='some_value')
>>> orig
{1: 1, 'some_key': 'some_value'}
>>>
>>> # We need the name to attach to the same dict in another process
>>> ultra.name
'psm_ad73da69'
```

```python
Python 3.9.2 (default, Feb 28 2021, 17:03:44) 
[GCC 10.2.1 20210110] on linux
Type "help", "copyright", "credits" or "license" for more information.
>>> 
>>> from UltraDict import UltraDict
>>> ultra = UltraDict(name='psm_ad73da69')
>>> ultra
{1: 1, 'some_key': 'some_value'}
>>>
>>> # Now let's to some performance testing
>>> import multiprocessing, timeit
>>> orig = dict({ 1:1 }, some_key='some_value')
>>> managed = multiprocessing.Manager().dict(orig)
>>> orig
{1: 1, 'some_key': 'some_value'}
>>> dict(managed)
{1: 1, 'some_key': 'some_value'}
```

## Read performance

```python
>>> timeit.timeit('orig[1]', globals=globals())
0.03503723500762135
>>> timeit.timeit('ultra[1]', globals=globals())
0.380401570990216
>>> # We are factor 10 slower than a real, local dict
>>> timeit.timeit('managed[1]', globals=globals())
15.848494678968564
>>> # But way faster than using a Manager
>>>
>>> # If you full performance, you can access the underlying
>>> # cache directly and get almost original dict performance,
>>> # of course at the cost of not having real-time updates anymore.
>>> timeit.timeit('ultra.data[1]', globals=globals())
0.047667117964010686
```

## Write performance

```python
>>> timeit.timeit('orig[1] = 1', globals=globals())
0.02869905502302572
>>> timeit.timeit('ultra[1] = 1', globals=globals())
2.259694856009446
>>> # We are factor 100 slower than a real, local dict,
>>> # but still way faster than using a Manager
>>> timeit.timeit('managed[1] = 1', globals=globals())
16.352361536002718
```

## Advanced usage

```python
>>> # The buffer size limits the biggest change that can be streamed, so when you use
>>> # deeply nested dicts you might need a bigger buffer. Otherwise, if the buffer is too small,
>>> # it will fall back to a full dump.
>>> ultra = UltraDict({ 'init': 'some initial data' }, name='my-name', buffer_size=100_000)
>>> # Lets use a value with 100.000 bytes length
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
>>>
>>> ultra.print_status()
>>>
>>> # Force load of latest full dump, even if we had already processed it.
>>> # There might also be streaming updates available after loading the full dump.
>>> ultra.load(force=True)
>>> ultra.print_status()

>>> # Apply full dump and stream updates to
>>> # underlying local dict, this is automatically
>>> # called when you normally access the UltraDict,
>>> # but can be useful to call after a forced load.
>>> ultra.apply_update()
>>>
>>> ultra.dump()
>>> ultra.print_status()
>>> # Access uderlying local dict directly
>>> ultra.data
>>> # Apply updates to underlying local dict,
>>> # this is automatically called when you normally
>>> # access the UltraDict
>>> ultra.apply_update()
```
