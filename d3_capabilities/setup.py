import os
from glob import glob

from setuptools import find_packages, setup

PACKAGE = "d3_capabilities"

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
    description="Equivalentes de los 6 nodos naoqi_* (speech, perception, navigation, manipulation, miscellaneous, interface) para el Double 3.",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "d3_speech_node = d3_capabilities.speech_node:main",
            "d3_perception_node = d3_capabilities.perception_node:main",
            "d3_navigation_node = d3_capabilities.navigation_node:main",
            "d3_manipulation_node = d3_capabilities.manipulation_node:main",
            "d3_miscellaneous_node = d3_capabilities.miscellaneous_node:main",
            "d3_interface_node = d3_capabilities.interface_node:main"
        ],
    },
)
