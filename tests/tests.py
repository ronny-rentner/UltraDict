import unittest
import subprocess

# Make the tests find UltraDict
import sys, os
sys.path.insert(0, os.path.join(os.path.basename(__file__), '..'))
from UltraDict import UltraDict

# Disable logging
if hasattr(UltraDict.log, 'disable'):
    UltraDict.log.disable(UltraDict.log.CRITICAL)
else:
    UltraDict.log.set_level(UltraDict.log.Levels.error)

class UltraDictTests(unittest.TestCase):

    def setUp(self):
        pass

    def exec(self, filepath):
        ret = subprocess.run([sys.executable, filepath],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        #print(ret.stdout.decode())
        ret.stdout = ret.stdout.replace(b'\r\n', b'\n');
        self.assertEqual(ret.returncode, 0, f"Running '{filepath}' returned exit code '{ret.returncode}' but expected exit code is '0'")
        return ret

    def exec_show_output(self, ret):
        return f"\n\n{ret}\n\nOutput:\n{ret.stdout.decode()}\n"

    def assertReturnCode(self, ret, target=0):
        return self.assertEqual(ret.returncode, target, self.exec_show_output(ret))

    def test_count(self):
        ultra = UltraDict()
        other = UltraDict(name=ultra.name)

        count = 100
        for i in range(count//2):
            ultra[i] = i

        for i in range(count//2, count):
            other[i] = i

        self.assertEqual(len(ultra), len(other))

    def test_huge_value(self):
        ultra = UltraDict()

        # One megabyte string
        self.assertEqual(ultra.full_dump_counter, 0)

        length = 1_000_000

        ultra['huge'] = ' ' * length

        self.assertEqual(ultra.full_dump_counter, 1)
        self.assertEqual(len(ultra.data['huge']), length)

        other = UltraDict(name=ultra.name)

        self.assertEqual(len(other.data['huge']), length)

    def test_parameter_passing(self):
        ultra = UltraDict(shared_lock=True, buffer_size=4096*8, full_dump_size=4096*8)
        # Connect `other` dict to `ultra` dict via `name`
        other = UltraDict(name=ultra.name)

        if sys.platform.startswith("linux"):
            self.assertIsInstance(ultra.lock, ultra.SharedMutexLock)
            self.assertIsInstance(other.lock, other.SharedMutexLock)
        else:
            self.assertIsInstance(ultra.lock, ultra.SharedLock)
            self.assertIsInstance(other.lock, other.SharedLock)

        self.assertEqual(ultra.buffer_size, other.buffer_size)

    def test_iter(self):
        ultra = UltraDict()
        # Connect `other` dict to `ultra` dict via `name`
        other = UltraDict(name=ultra.name)

        ultra[1] = 1
        ultra[2] = 2

        counter = 0
        for i in other.items():
            counter += 1

        self.assertEqual(counter, 2)

        self.assertEqual(ultra.items(), other.items())

    def test_delete(self):
        import random
        import string
        letters = string.ascii_lowercase
        rand_str =   ''.join(random.choice(letters) for i in range(1000))
        my_dict = UltraDict(buffer_size=10_000_000)
        for i in range(100_000):
            my_dict[i] = rand_str
        for i in list(my_dict.keys()):
            del my_dict[i]
        self.assertEqual(len(my_dict), 0)

    def test_already_exists(self):
        name = 'ultra_test'
        # Ensure we have a clean state before the test
        UltraDict.unlink_by_name(name, ignore_errors=True)
        UltraDict.unlink_by_name(name + '_memory', ignore_errors=True)
        # Create should be possible now
        u1 = UltraDict(name=name, create=True)
        with self.assertRaises(UltraDict.Exceptions.AlreadyExists):
            u2 = UltraDict(name=name, create=True)

    def test_not_already_exists(self):
        name = 'ultra_test'
        # Ensure we have a clean state before the test
        UltraDict.unlink_by_name(name, ignore_errors=True)
        UltraDict.unlink_by_name(name + '_memory', ignore_errors=True)

        with self.assertRaises(UltraDict.Exceptions.CannotAttachSharedMemory):
            ultra = UltraDict(name=name, create=False)

    def test_lock_blocking(self):
        pass

    def test_full_dump(self):
        # TODO
        pass

    # Turns out MacOS can only do 24 characters in total
    #def test_longest_name(self):
    #    for i in range(5, 50):
    #        print('Loop ', i)
    #        ultra = UltraDict(name='x' * i)

    @unittest.skipUnless(sys.platform.startswith("linux"), "requires Linux")
    def test_cleanup(self):
        # TODO
        import psutil
        p = psutil.Process()
        file_count = len(p.open_files())
        self.assertEqual(file_count, 0, "file handle count before before tests should be 0")
        ultra = UltraDict(nested={ 1: 1})
        file_count = len(p.open_files())
        self.assertEqual(file_count, 4, "file handle count with one simple UltraDict should be 4")
        del ultra
        file_count = len(p.open_files())
        self.assertEqual(file_count, 0, "file handle count after deleting the UltraDict should be 0 again")
        ultra = UltraDict(nested={ 1: 1}, recurse=True)
        file_count = len(p.open_files())
        self.assertEqual(file_count, 12, "nested file handle count should be 12")
        del ultra
        file_count = len(p.open_files())
        self.assertEqual(file_count, 0, "nested file handle count after deleting UltraDict should be 0 again")

    def test_example_simple(self):
        filename = "examples/simple.py"
        ret = self.exec(filename)
        self.assertReturnCode(ret)
        self.assertEqual(ret.stdout.splitlines()[-1], b"Length:  100000  ==  100000  ==  100000", self.exec_show_output(ret))

    def test_example_parallel(self):
        filename = "examples/parallel.py"
        ret = self.exec(filename)
        self.assertReturnCode(ret)
        self.assertEqual(ret.stdout.splitlines()[-1], b'Counter:  100000  ==  100000', self.exec_show_output(ret))

    def test_example_nested(self):
        filename = "examples/nested.py"
        ret = self.exec(filename)
        self.assertReturnCode(ret)
        self.assertEqual(ret.stdout.splitlines()[-1], b"{'nested': {'deeper': {0: 2}}}  ==  {'nested': {'deeper': {0: 2}}}", self.exec_show_output(ret))

    def test_example_recover_from_stale_lock(self):
        filename = "examples/recover_from_stale_lock.py"
        ret = self.exec(filename)
        self.assertReturnCode(ret)
        self.assertEqual(ret.stdout.splitlines()[-1], b"Counter: 100 == 100", self.exec_show_output(ret))


    def test_export_as_pure_dict(self):
        ultra = UltraDict(
            {
                "1": "hello",
                "2": 5,
                "3": {
                    "1": 1,
                    "2": {
                        "1": True,
                        "2": None,
                        "3": [1, 2, 3]
                    },
                    "3": [4, 5, 6, {"7": 8}]
                }
            },
            recurse=True
        )

        ultra2 = UltraDict(
            {
                "1": "hello",
                "2": 5,
                "3": {
                    "1": 1,
                    "2": {
                        "1": True,
                        "2": None,
                        "3": [1, 2, 3]
                    },
                    "3": [4, 5, 6, {"7": 8}]
                }
            },
            recurse=False
        )


        def assert_pure_dict(elem):
            self.assertNotIsInstance(elem, UltraDict)

            if isinstance(elem, dict):
                for key in elem.keys():
                    assert_pure_dict(elem[key])

        
        with self.assertRaises(AssertionError):
            assert_pure_dict(ultra)
            assert_pure_dict(ultra2)

        assert_pure_dict(ultra.as_pure_dictionary())
        assert_pure_dict(ultra2.as_pure_dictionary())


if __name__ == '__main__':
    if len(sys.argv) > 1:
        for i in range(0, len(sys.argv)):
            if sys.argv[i].startswith('-'):
                continue
            if '.' not in sys.argv[i]:
                sys.argv[i] = f"UltraDictTests.{sys.argv[i]}"
    unittest.main()
