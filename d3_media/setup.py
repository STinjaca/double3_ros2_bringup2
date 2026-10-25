import os
from glob import glob

from setuptools import find_packages, setup

PACKAGE = "d3_media"

setup(
    name=PACKAGE,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + PACKAGE]),
        ("share/" + PACKAGE, ["package.xml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Santi T",
    maintainer_email="111019208+STinjaca@users.noreply.github.com",
    description="TTS (espeak-ng/Piper) y ASR (Vosk) en el host para el Double 3.",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            
        ],
    },
)
