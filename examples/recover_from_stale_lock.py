#
# This example uses a configurable amount of worker processes to jointly increment a counter.
#
# A crash is simulated in one of the processes while it currently holds the shared lock.
# A strategy for recovery with a timeout is demonstrated.
#
# NOTE: There is recover_from_stale_lock.py and recover_from_stale_lock_manual.py. The manual example
#       manages the decision itself when a lock is stale.

import sys, os
sys.path.insert(0, '..')

from UltraDict import UltraDict

import multiprocessing, time, signal, subprocess

# For better visibility in console, only count to 100
count = 100
#count = 100_000

number_of_processes = 5

# The process that will find the counter to be 10 will
# simulate a hard crash (using SIGKILL) and a stale lock
simulate_crash_at_target_count = 10

# Contract to never hold the lock longer than this amount of seconds.
# If any user/process is holding the lock longer, the other processes
# should be allowed to steal the lock (afterchecking that the blocking
# process is actually dead).
stale_lock_timeout = 5.0

def possibly_simulate_crash(d):
    """
    Simulate random crash if the counter has reached the target value.
    This will cause the lock to be stale and not released.
    """
    if d['counter'] == simulate_crash_at_target_count:
        process = multiprocessing.process.current_process()
        print(f"Simulating crash, kill process name={process.name}, pid={process.pid}, lock={d.lock}")
        # SIGKILL is a hard kill on kernel level leaving the process
        # no time for any cleanup whatsoever
        if hasattr(signal, 'SIGKILL'):
            os.kill(process.pid, signal.SIGKILL)
        elif sys.platform == 'win32':
            subprocess.call(['taskkill', '/F', '/PID',  str(process.pid)])
        else:
            raise Exception("Don't know how to kill process to simulate a crash")

        # Wait for the kill to happen
        time.sleep(1)

        # This message should never print
        print("Killed. (This message should never print!)")

        raise Exception("We should never reach this point, because the process should have been killed before.")

def run(name, target):
    d = UltraDict(name=name)
    process = multiprocessing.process.current_process()
    print(f"Started process name={process.name}, pid={process.pid} {d.lock}")

    # Give all processes some grace period to print their start messages
    time.sleep(1)

    need_to_count = True
    while need_to_count:
        print("start count: ", d['counter'], ' | ', process.name, process.pid)
        # Adding 1 to the counter is unfortunately not an atomic operation in Python,
        # but UltraDict's shared lock comes to our resuce: We can simply reuse it.
        with d.lock(timeout=stale_lock_timeout, steal_after_timeout=True):
            if need_to_count := d['counter'] < target:
                # Under the lock, we can safely read, modify and
                # write back any values in the shared dict.
                d['counter'] += 1

            print("end   count: ", d['counter'], ' | ', process.name, process.pid)

            possibly_simulate_crash(d)

if __name__ == '__main__':

    ultra = UltraDict(buffer_size=10_000, shared_lock=True)
    ultra['counter'] = 0

    processes = []

    ctx = multiprocessing.get_context("spawn")

    for x in range(number_of_processes):
        processes.append(ctx.Process(target=run, name=f"Process {x}", args=[ultra.name, count]))

    # These processes should write more or less at the same time
    for p in processes:
        p.start()

    for p in processes:
        p.join()

    #print(ultra)
    #ultra.print_status()
    #ultra.lock.print_status()

    print("Counter:", ultra['counter'], '==', count)
