import sys
sys.path.insert(0, '..')
sys.path.insert(0, '../..')

import multiprocessing
import random
import string
import time
import subprocess
import sys

from UltraDict import UltraDict

name='ultra6'

def P1():

    print("START P1", file=sys.stderr)
    ultra = UltraDict(name=name)

    while True:
        ultra['banned'][f"{random.randint(1, 254)}.{random.randint(1, 254)}.{random.randint(1, 254)}.{random.randint(1, 254)}"] = True
        #print('P1', subprocess.check_output(f"lsof -p {multiprocessing.current_process().pid} |wc -l", shell=True))
        print('P1', ultra)

        #if len(ultra['banned']) > 1000:
        #    ultra['banned'].pop()

def P2():

    print("START P2", file=sys.stderr)
    ultra = UltraDict(name=name)

    while True:
        chars = "".join([random.choice(string.ascii_lowercase) for i in range(8)])
        ultra['banned'][f"{random.randint(1, 254)}.{random.randint(1, 254)}.{random.randint(1, 254)}.{random.randint(1, 254)}"] = chars
        print('P2', ultra)

if __name__ == '__main__':

    print("START MA", file=sys.stderr)

    # Make sure the UltraDict with name='ultra6' does not exist,
    # it could be left over from a previous crash

    UltraDict.unlink_by_name(name, ignore_errors=True)

    ultra = UltraDict({'banned': { '127.0.0.1': True }}, name=name, buffer_size=10_000, shared_lock=True, recurse=True)

    p1 = multiprocessing.Process(target=P1)
    p1.start()

    p2 = multiprocessing.Process(target=P2)
    p2.start()

    while True:
        print('MA', ultra)
        #print('MA', subprocess.check_output(f"lsof -p {multiprocessing.current_process().pid} |wc -l", shell=True))
        #x = str(ultra)

    p1.join()
    p2.join()
