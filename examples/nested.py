#
# Nested example
#
# Two dicts `ultra` and `other` are linked together using shared memory.

import sys
sys.path.insert(0, '..')

from UltraDict import UltraDict

import pickle

if __name__ == '__main__':

    # No name provided, create a new dict with random name
    ultra = UltraDict(recurse=True)
    # Connect `other` dict to `ultra` dict via `name`
    other = UltraDict(name=ultra.name)

    #ultra['nested'] = { 1: 1 }

    ultra['nested'] = { 'inner': 'value', 'deeper': { 0: 1 } }
    ultra['nested']['deeper'][0] = 2

    #print(ultra, type(ultra), isinstance(ultra, dict))
    #print(other, type(other), isinstance(ultra, dict))

    # No apply_update() done, yet, so they're not equal
    print(other == ultra)

    other.apply_update()

    # Now they are equal
    print(other == ultra)

    # Automatically run apply_update()
    print(ultra, ' == ', other)
