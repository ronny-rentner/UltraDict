import sys, os, time, multiprocessing
import ultraimport

ultraimport('__dir__/lib.py', '*', globals=locals())
UltraDict = ultraimport('__dir__/../../UltraDict.py', 'UltraDict')

count = 1_000_000
count = 100_000

# Test Redis performance without Python:
# redis-benchmark -q -n 1000000 -t set,get

def main():

    print(f"\nTesting Performance with {count!r} operations each\n")


    ##
    ## Redis
    ##

    import redis
    r = redis.Redis()

    # Redis (writes)
    t_start = time.perf_counter()
    for i in range(count):
        r.set(1, 1)
    t_end = time.perf_counter()
    print_perf('Redis', 'writes', t_start, t_end, count)

    # Redis (reads)
    t_start = time.perf_counter()
    for i in range(count):
        x = r.get(1)
    t_end = time.perf_counter()
    print_perf('Redis', 'reads', t_start, t_end, count)

    ##
    ## Python MPM dict
    ##

    with multiprocessing.Manager() as manager:
        # Python MPM dict (writes)
        d = manager.dict()
        t_start = time.perf_counter()
        for i in range(count):
            d[1] = 1
        t_end = time.perf_counter()
        print_perf('Python MPM dict', 'writes', t_start, t_end, count)

        # Python MPM dict (reads)
        t_start = time.perf_counter()
        for i in range(count):
            x = d[1]
        t_end = time.perf_counter()
        print_perf('Python MPM dict', 'reads', t_start, t_end, count)

    ##
    ## Python dict
    ##

    # Python dict (writes)
    d = dict()
    t_start = time.perf_counter()
    for i in range(count):
        d[1] = 1
    t_end = time.perf_counter()
    print_perf('Python dict', 'writes', t_start, t_end, count)

    # Python dict (reads)
    t_start = time.perf_counter()
    for i in range(count):
        x = d[1]
    t_end = time.perf_counter()
    print_perf('Python dict', 'reads', t_start, t_end, count)

    ##
    ## UltraDict
    ##

    import UltraDict
    ultra = UltraDict.UltraDict()

    # UltraDict (writes)
    t_start = time.perf_counter()
    for i in range(count):
        ultra[1] = 1
    t_end = time.perf_counter()
    print_perf('UltraDict', 'writes', t_start, t_end, count)

    # UltraDic (reads)
    t_start = time.perf_counter()
    for i in range(count):
        x = ultra[1]
    t_end = time.perf_counter()
    print_perf('UltraDict', 'reads', t_start, t_end, count)

    ##
    ## UltraDict with shared_lock=True
    ##

    ultra = UltraDict.UltraDict(shared_lock=True)
    section = 'UltraDict (shared_lock=True)'

    # UltraDict with shared_lock=True (writes)
    t_start = time.perf_counter()
    for i in range(count):
        with ultra.lock:
            ultra[1] = 1
    t_end = time.perf_counter()
    print_perf(section, 'writes', t_start, t_end, count)

    # UltraDic with shared_lock=True (reads)
    t_start = time.perf_counter()
    for i in range(count):
        x = ultra[1]
    t_end = time.perf_counter()
    print_perf(section, 'reads', t_start, t_end, count)

    ##
    ## UltraDict with shared_lock='pymutex'
    ##

    ultra = UltraDict.UltraDict(shared_lock='pymutex')
    section = 'UltraDict (shared_lock=\'pymutex\')'

    # UltraDict with shared_lock='pymutex' (writes)
    t_start = time.perf_counter()
    for i in range(count):
        with ultra.lock:
            ultra[1] = 1
    t_end = time.perf_counter()
    print_perf(section, 'writes', t_start, t_end, count)

    # UltraDic with shared_lock='pymutex' (reads)
    t_start = time.perf_counter()
    for i in range(count):
        x = ultra[1]
    t_end = time.perf_counter()
    print_perf(section, 'reads', t_start, t_end, count)

    print_ranking()

if __name__ == '__main__':
    main()

