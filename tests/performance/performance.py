import sys, os, time, multiprocessing
sys.path.insert(0, '../../..')

count = 1_000_000
count = 100_000

# Test Redis performance without Python:
# redis-benchmark -q -n 1000000 -t set,get

ranking = {}

def print_perf(name, operation, t_start, t_end, iterations):
    t = t_end - t_start
    speed = round(iterations / t)
    print(f"{name} ({operation}) = {speed:,d} ops per second")

    if not operation in ranking:
        ranking[operation] = {}

    ranking[operation][name] = speed

def print_ranking():
    print('\nRanking:')
    for operation_name, operation in ranking.items():
        print(f'  {operation_name}:')
        top = None
        for name, value in sorted(operation.items(), key=lambda i: i[1], reverse=True):
            if not top:
                top = value

            multiple = round(top/value, 2)
            print(f'    {name} = {value:,d} (factor {multiple})')

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

    ultra = UltraDict.UltraDict(shared_lock=True)

    # UltraDict with shared_lock=True (writes)
    t_start = time.perf_counter()
    for i in range(count):
        with ultra.lock:
            ultra[1] = 1
    t_end = time.perf_counter()
    print_perf('UltraDict (shared_lock=True)', 'writes', t_start, t_end, count)

    # UltraDic with shared_lock=True (reads)
    t_start = time.perf_counter()
    for i in range(count):
        x = ultra[1]
    t_end = time.perf_counter()
    print_perf('UltraDict (shared_lock=True)', 'reads', t_start, t_end, count)

    print_ranking()

if __name__ == '__main__':
    main()

