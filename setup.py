from pathlib import Path
from setuptools import setup, Extension
import Cython.Build

# read the contents of your README file
this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text()

version = '0.0.4'

ext = Extension(name="UltraDict", sources=["UltraDict.py"])

setup(
    name='UltraDict',
    version=version,
    description='Sychronized, streaming dictionary that uses shared memory as a backend',
    long_description=long_description,
    long_description_content_type='text/markdown',
    author='Ronny Rentner',
    author_email='ultradict.code@ronny-rentner.de',
    url='https://github.com/ronny-rentner/UltraDict',
    cmdclass={'build_ext': Cython.Build.build_ext},
    package_dir={'UltraDict': '.'},
    packages=['UltraDict'],
    zip_safe=False,
    ext_modules=Cython.Build.cythonize(ext, compiler_directives={'language_level' : "3"}),
    setup_requires=['cython>=0.24.1'],
    python_requires=">=3.9",
)
