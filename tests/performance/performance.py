import sys, os, time, multiprocessing
sys.path.insert(0, '../../..')

count = 1_000_000

# Test Redis performance without Python:
# redis-benchmark -q -n 1000000 -t set,get

print(f"\nTesting Performance with {count!r} operations each\n")

def print_perf(name, t_start, t_end, iterations):
    t = t_end - t_start
    speed = round(iterations / t)
    print(f"{name} = {speed} ops per second ")

## Redis
import redis
r = redis.Redis()

# Redis (writes)
t_start = time.perf_counter()
for i in range(count):
    r.set(1, 1)
t_end = time.perf_counter()
print_perf('Redis (writes)', t_start, t_end, count)

# Redis (reads)
t_start = time.perf_counter()
for i in range(count):
    x = r.get(1)
t_end = time.perf_counter()
print_perf('Redis (reads)', t_start, t_end, count)

## UltraDict
import UltraDict
ultra = UltraDict.UltraDict()

# UltraDict (writes)
t_start = time.perf_counter()
for i in range(count):
    ultra[1] = 1
t_end = time.perf_counter()
print_perf('UltraDict (writes)', t_start, t_end, count)

# UltraDic (reads)
t_start = time.perf_counter()
for i in range(count):
    x = ultra[1]
t_end = time.perf_counter()
print_perf('UltraDict (reads)', t_start, t_end, count)

