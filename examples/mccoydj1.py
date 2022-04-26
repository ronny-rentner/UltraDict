import sys
sys.path.insert(0, '..')

import multiprocessing
from UltraDict import UltraDict
import random
import string
import json
import pickle

serializer=pickle

def P1():
    ultra = UltraDict(name='ultra6', serializer=serializer)

    while True:
        ultra['P1'] = random.random()
        #ultra['P2']

def P2():
    ultra = UltraDict(name='ultra6', serializer=serializer)

    while True:
        chars = "".join([random.choice(string.ascii_lowercase) for i in range(8)])
        ultra['P2'] = chars
        #ultra['P1']

if __name__ == '__main__':

    ultra = UltraDict({'P1':float(0), 'P2':''}, name='ultra6', buffer_size=100_000, shared_lock=False, auto_unlink=True, serializer=serializer)

    p1 = multiprocessing.Process(target=P1)
    p1.start()

    p2 = multiprocessing.Process(target=P2)
    p2.start()

    import time
    while True:
        #print(ultra)
        #time.sleep(1)
        x = ultra

    p1.join()
    p2.join()
