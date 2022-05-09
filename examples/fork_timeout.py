#
# N processes incrementing a counter in parallel
#

import sys, os
sys.path.insert(0, '..')

from UltraDict import UltraDict

import multiprocessing, time, signal

# For better visibility in console, only count to 100
count = 100
#count = 100_000

number_of_processes = 5

# The process that will find the counter to be 10 will
# simulate a hard crash and a stale lock
simulate_crash_at_count = 10

def simulate_crash(d):

        # Simulate random crash in one of the processes.
        # This will cause the lock to be stale and not released.
        if d['counter'] == simulate_crash_at_count:
            process = multiprocessing.process.current_process()
            print(f"Simulating crash, kill process name={process.name}, pid={process.pid}, lock={d.lock}")
            # SIGKILL is a hard kill on kernel level leaving the process
            # no time for any cleanup whatsoever
            os.kill(process.pid, signal.SIGKILL)
            # This message should never print
            print("Killed")

def run(d, target):
    process = multiprocessing.process.current_process()
    print(f"Started process name={process.name}, pid={process.pid} {d.lock}")
    
    # Give all processes some grace period to print their start messages
    time.sleep(1)

    # Timer to protect from stale locks
    time_start = 0

    while True:
        print("start count: ", d['counter'], ' | ', process.name, process.pid)
        try:
            # Adding 1 to the counter is unfortunately not an atomic operation in Python,
            # but UltraDict's shared lock comes to our resuce: We can simply reuse it.
            with d.lock:
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

                simulate_crash(d)

        except d.CannotAcquireLockException:
            # We measure the time on how long we fail to acquire a lock
            if not time_start:
                time_start = time.monotonic()

            time_passed = time.monotonic() - time_start

            # If the lock is stale for more than 1 second (plus the time for the initial attempt),
            # we will steal it.
            if time_passed >= 1:
                print(process.name, process.pid, 'cannot acquire lock, more than 1 s have passed, lock must be stale')
                
                # Check that the process is dead that is owning the stale lock
                pid = d.lock.get_remote_pid()

                # The lock pid must not be our pid, after all we could not acquire the lock
                assert process.pid != pid

                # No process must exist anymore with the pid
                try:
                    import psutil
                    p = psutil.Process(pid)
                    if p and p.is_running() and p.status() not in [psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD]:
                        raise Exception(f"Stale lock but process is still alive, something seems really wrong {pid} / {process.pid}")
                except psutil.NoSuchProcess:
                    # If the process is already gone, we cannot find information about it.
                    # It will be safe to steal the lock.
                    pass
                except Exception as e:
                    raise e

                # Steal the stale lock
                print(f"Process {multiprocessing.current_process().pid} is resetting lock from {pid}")
                d.lock.reset()
            else:
                print(f'{process.name} cannot acquire lock, will try again, {time_passed:.3f} s have passed')



if __name__ == '__main__':

    ultra = UltraDict(buffer_size=10_000, shared_lock=True)
    ultra['some-key'] = 'some value'
    ultra['counter'] = 0

    name = ultra.name

    #print(ultra)

    processes = []

    for x in range(number_of_processes):
        processes.append(multiprocessing.Process(target=run, name=f"Process {x}", args=[ultra, count]))

    # These processes should write more or less at the same time
    for p in processes:
        p.start()

    for p in processes:
        p.join()

    #print(ultra)
    #ultra.print_status()
    #ultra.lock.print_status()

    print("Counter: ", ultra['counter'], ' == ', count)
