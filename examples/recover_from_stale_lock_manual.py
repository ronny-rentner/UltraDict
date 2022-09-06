#
# This example uses a configurable amount of worker processes to jointly increment a counter.
#
# A crash is simulated in one of the processes while it currently holds the shared lock.
# A strategy for recovery with a timeout is demonstrated.
#

import sys, os
sys.path.insert(0, '..')

from UltraDict import UltraDict

import multiprocessing, time, signal, subprocess

# For better visibility in console, only count to 100
count = 100
#count = 10_000

number_of_processes = 5

# The process that will find the counter to be 10 will
# simulate a hard crash (using SIGKILL) and a stale lock
simulate_crash_at_target_count = 10

# Contract to never hold the lock longer than this amount of seconds.
# If any user/process is holding the lock longer, the other processes
# should be allowed to steal the lock afterchecking that the blocking
# process is actually dead.
stale_lock_timeout = 1.0

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
        # This message should never print
        print("Killed. (This message should never print!)")

def run(name, target):
    d = UltraDict(name=name)
    process = multiprocessing.process.current_process()
    print(f"Started process name={process.name}, pid={process.pid} {d.lock}")

    # Give all processes some grace period to print their start messages
    time.sleep(1)

    # Timer to protect from stale locks
    time_start = 0

    # The pid of the process that is blocking the lock
    blocking_pid = 0

    while True:
        print("start count: ", d['counter'], ' | ', process.name, process.pid)
        try:
            # Adding 1 to the counter is unfortunately not an atomic operation in Python,
            # but UltraDict's shared lock comes to our resuce: We can simply reuse it.
            with d.lock(block=False):
                if d['counter'] < target:
                    # Under the lock, we can safely read, modify and
                    # write back any values in the shared dict
                    d['counter'] += 1

                    print("end   count: ", d['counter'], ' | ', process.name, process.pid)
                else:
                    # Finished counting to target
                    return

                # After sucessfully incrementing the counter we reset our timer
                time_start = 0

                possibly_simulate_crash(d)

        except d.Exceptions.CannotAcquireLock as e:

            # We measure the time on how long we fail to acquire a lock
            if not time_start:
                time_start = e.timestamp
                blocking_pid = e.blocking_pid

            # We should not be the blocking pid
            assert process.pid != blocking_pid

            #time.sleep(0.1)
            time_passed = time.monotonic() - time_start

            # If the lock is stale for more than 1 second (plus the time for the initial attempt),
            # we will steal it.
            if time_passed >= stale_lock_timeout:

                print(process.name, process.pid, f"cannot acquire lock, more than {stale_lock_timeout} s have passed, lock must be stale")

                # The lock blocking pid cannot not be our pid, after all we could not acquire the lock
                assert process.pid != blocking_pid

                # Steal lock and release it so on the next loop iteration, we or some other process can get it
                print(f"Process {process.name} ({process.pid}) is stealing and releasing lock from {blocking_pid}")
                # steal_from_dead() ensures the process we are stealing from is actually dead
                result = d.lock.steal_from_dead(from_pid=blocking_pid, release=True)
                print(f"Lock stealing result: {result} {d.lock.status()}")
                time_start = 0
                blocking_pid = 0
            else:
                print(f'{process.name} {multiprocessing.current_process().pid} cannot acquire lock, will try again, {time_passed:.3f} s have passed')



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
