import sys
sys.path.insert(0, '..')

import multiprocessing
from UltraDict import UltraDict
import random
import string

name='ultra6'

def P1():
    ultra = UltraDict(name=name)

    while True:
        pass
        ultra['P1'] = random.random()
        #ultra['P2']

def P2():
    ultra = UltraDict(name=name)

    while True:
        chars = "".join([random.choice(string.ascii_lowercase) for i in range(8)])
        ultra['P2'] = chars
        #ultra['P1']

if __name__ == '__main__':

    # Make sure the UltraDict with name='ultra6' does not exist,
    # it could be left over from a previous crash

    UltraDict.unlink_by_name(name, ignore_error=True)

    ultra = UltraDict({'P1':float(0), 'P2':''}, name=name, buffer_size=10_000, shared_lock=True)

    p1 = multiprocessing.Process(target=P1)
    p1.start()

    p2 = multiprocessing.Process(target=P2)
    p2.start()

    import time
    while True:
        print(ultra)

    p1.join()
    p2.join()
