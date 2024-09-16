#
# UltraDict Example
# -----------------
#
# Four processes are incrementing a counter in parallel.
#
# In this example we use the shared_lock=True parameter.
# This way of shared locking is safe accross independent
# processes on all operting systems but it is slower than
# using the built-in default locking method using `multiprocessing.RLock()`.
#
# UltraDict uses the pthread library on Linux and the atomics package on other OS for shared locking.


# Make the example find UltraDict
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from UltraDict import UltraDict

import multiprocessing

count = 100_000

def run(name, target, x):
    # Connect to the existing UltraDict by its name
    d = UltraDict(name=name, shared_lock=True)
    for i in range(target):
        # Adding 1 to the counter is unfortunately not an atomic operation in Python,
        # but UltraDict's shared lock comes to our resuce: We can simply reuse it.
        with d.lock:
            # Under the lock, we can safely read, modify and write back any values
            # in the shared dict and be sure that nobody else has modified them
            # between reading and writing.
            d['counter'] += 1
            #print("counter: ", d['counter'], i, x)

if __name__ == '__main__':

    # No name provided to create a new dict with random name.
    # To make it work under Windows, we need to set a static `full_dump_size`
    ultra = UltraDict(buffer_size=10_000, shared_lock=True, full_dump_size=10_000)
    ultra['counter'] = 0

    # Our children will use the name to attach to the existing dict
    name = ultra.name

    ctx = multiprocessing.get_context("spawn")

    p1 = ctx.Process(target=run, name="Process 1", args=[name, count//4, 1])
    p2 = ctx.Process(target=run, name="Process 2", args=[name, count//4, 2])
    p3 = ctx.Process(target=run, name="Process 3", args=[name, count//4, 3])
    p4 = ctx.Process(target=run, name="Process 4", args=[name, count//4, 4])

    # These processes should write more or less at the same time
    p1.start()
    p2.start()
    p3.start()
    p4.start()

    print ("Started 4 processes..")

    p1.join()
    p2.join()
    p3.join()
    p4.join()

    print ("Joined 4 processes")

    print("Counter: ", ultra['counter'], ' == ', count)
