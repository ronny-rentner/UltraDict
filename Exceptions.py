#
# UltraDict
#
# A sychronized, streaming Python dictionary that uses shared memory as a backend
#
# Copyright [2022] [Ronny Rentner] [ultradict.code@ronny-rentner.de]
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import time

class CannotAttachSharedMemory(Exception):
    pass

class CannotAcquireLock(Exception):
    def __init__(self, *args, blocking_pid=0, timestamp=None, **kwargs):
        super().__init__('Cannot acquire lock', *args, *kwargs)
        self.blocking_pid = blocking_pid
        self.timestamp = timestamp or time.monotonic()

class CannotAcquireLockTimeout(CannotAcquireLock):
    def __init__(self, *args, time_passed=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.time_passed = time_passed

class ParameterMismatch(Exception):
    pass

class AlreadyClosed(Exception):
    pass

class AlreadyExists(Exception):
    pass

class FullDumpMemoryFull(Exception):
    pass

class MissingDependency(Exception):
    pass

