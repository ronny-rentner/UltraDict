import time, multiprocessing
import ultraimport
import atomics

ultraimport('__dir__/lib.py', '*', globals=locals())
UltraDict = ultraimport('__dir__/../../UltraDict.py', 'UltraDict')
pymutex = ultraimport('__dir__/../../pymutex/mutex.py', globals=locals())

count = 1_000_000
count = 100_000

def run(lock):
    t_start = time.perf_counter()
    for i in range(count):
        lock.acquire()
        lock.release()
    t_end = time.perf_counter()
    print_perf(lock.name, 'acquire/release', t_start, t_end, count)

class TestRLock:
    name = 'RLock'
    def __init__(self):
        self.lock = multiprocessing.RLock()

    def acquire(self):
        return self.lock.acquire()

    def release(self):
        return self.lock.release()

class TestBoolean:
    name = 'Boolean'

    def __init__(self):
        self.lock = False

    def acquire(self):
        self.lock = True

    def release(self):
        self.lock = False

class TestSharedLock:
    name = 'SharedLock'
    def __init__(self):
        self.ultra = UltraDict(shared_lock=True)
        self.lock = self.ultra.lock

    def acquire(self):
        self.lock.acquire(block=False)

    def release(self):
        self.lock.release()

class TestSharedMutexLock:
    name = 'SharedMutexLock'
    def __init__(self):
        self.ultra = UltraDict(shared_lock='pymutex')
        self.lock = self.ultra.lock

    def acquire(self):
        self.lock.acquire(block=False)

    def release(self):
        self.lock.release()

def main():
    run(TestRLock())
    run(TestBoolean())
    run(TestSharedLock())
    run(TestSharedMutexLock())
    print_ranking()

if __name__ == '__main__':
    main()
