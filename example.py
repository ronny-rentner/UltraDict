#
# Two processes incrementing a counter in parallel
#
# In this example we use the shared_lock=True parameter.
# This uses the atomic package internally for locking.
# 
# Unfortunately, this makes writing values to the dict rather slow,
# due to the overhead for aquiring the shared lock,
# so think carefully when you really need it.
#

from UltraDict import UltraDict

#from utils import log

#log.set_level(log.Levels.warn)

import atomics
import multiprocessing, time

count = 1000

def process1(name, target, x):
    # Connect to the existing ultra dict
    d = UltraDict(name=name, shared_lock=True)
    for i in range(target): 
        # Adding 1 to the counter is unfortunately not an atomic operation in Python,
        # but UltraDict's shared lock comes to our resuce: We can simply reuse it.
        with d.lock:
            # Under the lock, we can safely read, modify and
            # write back any values in the shared dict
            d['counter'] += 1
            print("counter: ", d['counter'], i, x)

if __name__ == '__main__':

    # No name provided, create a new dict with random name
    ultra = UltraDict(buffer_size=10_000, shared_lock=True, full_dump_size=10_000)
    ultra['some-key'] = 'some value'
    ultra['counter'] = 0

    # Our children will use the name to attach to the existing dict
    name = ultra.name

    #print(ultra)

    ctx = multiprocessing.get_context("spawn")

    p1 = ctx.Process(target=process1, name="Process 1", args=[name, count//2, 1])
    p2 = ctx.Process(target=process1, name="Process 2", args=[name, count//2, 2])

    # These processes should write more or less at the same time
    p1.start()
    p2.start()

    print ("Started")

    p1.join()
    p2.join()

    print ("Joined")

    ultra.print_status()
    ultra.lock.print_status()
    print(ultra)

    print("Counter: ", ultra['counter'], ' == ', count)
