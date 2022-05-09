import unittest
import subprocess
import sys

sys.path.insert(0, '..')

from UltraDict import UltraDict

class TestUltradict(unittest.TestCase):

    def setUp(self):
        pass

    def exec(self, filepath):
        ret = subprocess.run([sys.executable, filepath],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        ret.stdout = ret.stdout.replace(b'\r\n', b'\n');
        return ret

    def testCount(self):
        ultra = UltraDict()
        other = UltraDict(name=ultra.name)

        count = 100
        for i in range(count//2):
            ultra[i] = i

        for i in range(count//2, count):
            other[i] = i

        self.assertEqual(len(ultra), len(other))

    def testHugeValue(self):
        ultra = UltraDict()

        # One megabyte string
        self.assertEqual(ultra.full_dump_counter, 0)

        length = 1_000_000

        ultra['huge'] = ' ' * length

        self.assertEqual(ultra.full_dump_counter, 1)
        self.assertEqual(len(ultra.data['huge']), length)

        other = UltraDict(name=ultra.name)

        self.assertEqual(len(other.data['huge']), length)

    def testParameterPassing(self):
        ultra = UltraDict(shared_lock=True, buffer_size=4096*8, full_dump_size=4096*8)
        # Connect `other` dict to `ultra` dict via `name`
        other = UltraDict(name=ultra.name)

        self.assertIsInstance(ultra.lock, ultra.SharedLock)
        self.assertIsInstance(other.lock, other.SharedLock)

        self.assertEqual(ultra.buffer_size, other.buffer_size)

    def testFullDump(self):
        # TODO
        pass

    def testExampleSimple(self):
        filename = "examples/simple.py"
        ret = self.exec(filename)
        self.assertEqual(ret.returncode, 0, f'Running {filename} did return with an error.')
        self.assertEqual(ret.stdout, b"Length:  100000  ==  100000  ==  100000\n")

    def testExampleParallel(self):
        filename = "examples/parallel.py"
        ret = self.exec(filename)
        self.assertEqual(ret.returncode, 0, f'Running {filename} did return with an error.')
        self.assertEqual(ret.stdout, b'Started 2 processes..\nJoined 2 processes\nCounter:  100000  ==  100000\n')

    def testExampleNested(self):
        filename = "examples/nested.py"
        ret = self.exec(filename)
        self.assertEqual(ret.returncode, 0, f'Running {filename} did return with an error.')
        self.assertEqual(ret.stdout, b"{'nested': {'deeper': {0: 2}}}  ==  {'nested': {'deeper': {0: 2}}}\n")

if __name__ == '__main__':
    unittest.main()
