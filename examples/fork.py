#
# Two processes incrementing a counter in parallel
#
# This only without shared_lock, using multiprocessing.RLock() internally.
# This is much faster than the spawn alterntive.
#

import sys
sys.path.insert(0, '..')

from UltraDict import UltraDict

import multiprocessing

count = 100000

def run(d, target, x):
    for i in range(target): 
        # Adding 1 to the counter is unfortunately not an atomic operation in Python,
        # but UltraDict's shared lock comes to our resuce: We can simply reuse it.
        with d.lock:
            # Under the lock, we can safely read, modify and
            # write back any values in the shared dict
            d['counter'] += 1
            #print("counter: ", d['counter'], i, x)

if __name__ == '__main__':

    ultra = UltraDict(buffer_size=10_000)
    ultra['some-key'] = 'some value'
    ultra['counter'] = 0

    name = ultra.name

    #print(ultra)

    p1 = multiprocessing.Process(target=run, name="Process 1", args=[ultra, count//2, 1])
    p2 = multiprocessing.Process(target=run, name="Process 2", args=[ultra, count//2, 2])

    # These processes should write more or less at the same time
    p1.start()
    p2.start()

    p1.join()
    p2.join()

    #print(ultra)
    #ultra.print_status()
    #ultra.lock.print_status()

    print("Counter: ", ultra['counter'], ' == ', count)
