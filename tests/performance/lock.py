import timeit
import multiprocessing
import ultraimport

class TestRLock:
    def __init__(self):
        self.lock = multiprocessing.RLock()

    def acquire(self):
        return self.lock.acquire()

    def release(self):
        return self.lock.release()


class TestBoolean:
    def __init__(self):
        self.lock = False

    def acquire(self):
        self.lock = True

    def release(self):
        self.lock = False

class TestPymutex:
    def __init__(self):
        import pymutex
        self.lock = pymutex.SharedMutex('/dev/shm/my_shared_mutex', None)
        print(self.lock._state, self.lock._state.mmap)

    def acquire(self):
        self.lock.lock()

    def release(self):
        self.lock.unlock()

class TestSharedLock:
    def __init__(self):
        UltraDict = ultraimport('__dir__/../../UltraDict.py', 'UltraDict')
        self.ultra = UltraDict(shared_lock=True)
        print(self.ultra.lock)
        self.lock = self.ultra.lock

    def acquire(self):
        self.lock.acquire()

    def release(self):
        self.lock.release()

a = TestRLock()
print('RLock', min(timeit.repeat('a.acquire(); a.release()', globals=globals())))

a = TestBoolean()
print('boolean', min(timeit.repeat('a.acquire(); a.release()', globals=globals())))

a = TestPymutex()
print('pymutex', min(timeit.repeat('a.acquire(); a.release()', globals=globals())))

a = TestSharedLock()
print('SharedLock', min(timeit.repeat('a.acquire(); a.release()', globals=globals())))
