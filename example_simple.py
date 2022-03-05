#
# Simple counter example
#
# Two dicts `ultra` and `other` are linked together using shared memory.

from UltraDict import UltraDict

import multiprocessing, time

count = 100_000

if __name__ == '__main__':

    # No name provided, create a new dict with random name
    ultra = UltraDict(auto_unlink = False)
    # Connect `other` dict to `ultra` dict via `name`
    other = UltraDict(name=ultra.name)

    for i in range(count//2):
        ultra[i] = i

    for i in range(count//2, count):
        other[i] = i

    print("Length: ", len(other), ' == ', len(ultra), ' == ', count)
