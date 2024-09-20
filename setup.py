from pathlib import Path
from setuptools import setup, Extension
import os
import shutil

# Read the contents of your README file
this_directory = Path(__file__).parent
long_description = (this_directory / "readme.md").read_text()

version = '0.0.7'

# Function to detect if a C compiler is available
def has_compiler():
    # Check if gcc or clang is available
    return shutil.which('gcc') or shutil.which('clang')

# Decide whether to build C extensions or skip based on the availability of a compiler
def get_extension_modules():
    # If a C compiler is not available, skip the extension
    if not has_compiler():
        print("No C compiler detected. Skipping C extension building.")
        return []

    # C compiler available, attempt to use Cython or pre-generated C code
    try:
        from Cython.Build import cythonize
        ext = Extension(name="UltraDict", sources=["UltraDict.py"])
        return cythonize(ext, compiler_directives={'language_level': "3"})
    except ImportError:
        # Fall back to pre-generated C file
        if os.path.exists("UltraDict.c"):
            ext = Extension(name="UltraDict", sources=["UltraDict.c"])
            return [ext]
        print("No Cython or C source file available. Skipping C extension building.")
        return []

# Get the extension modules (empty list if no compilation)
ext_modules = get_extension_modules()

setup(
    name='UltraDict',
    version=version,
    description='Sychronized, streaming dictionary that uses shared memory as a backend',
    long_description=long_description,
    long_description_content_type='text/markdown',
    author='Ronny Rentner',
    author_email='ultradict.code@ronny-rentner.de',
    url='https://github.com/ronny-rentner/UltraDict',
    package_dir={'UltraDict': '.', 'UltraDict.pymutex': 'pymutex'},
    packages=['UltraDict', 'UltraDict.pymutex'],
    zip_safe=False,
    ext_modules=ext_modules,  # Only add extensions if a compiler is available
    setup_requires=['cython>=0.24.1'] if ext_modules else [],
    python_requires=">=3.8",
)
