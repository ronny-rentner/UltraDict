from setuptools import setup, Extension
import Cython.Build

ext = Extension(
    name="UltraDict", 
    sources=["UltraDict.py"],
)

setup(
    name='UltraDict',
    version='0.0.1',
    description='UltraDict',
    author='Ronny Rentner',
    author_email='mail@ronny-rentner.de',
    url='https://github.com/ronny-rentner/UltraDict',
    cmdclass={'build_ext': Cython.Build.build_ext},
    package_dir={'UltraDict': '.'},
    packages=['UltraDict'],
    zip_safe=False,
    ext_modules=Cython.Build.cythonize(ext),
    setup_requires=['cython>=0.24.1'],
)
