import os
from glob import glob

from setuptools import find_packages, setup

PACKAGE = "d3_sim"

setup(
    name=PACKAGE,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + PACKAGE]),
        ("share/" + PACKAGE, ["package.xml"]),
        (os.path.join("share", PACKAGE, "fixtures"), glob("fixtures/*.jsonl")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Santi T",
    maintainer_email="111019208+STinjaca@users.noreply.github.com",
    description="Simulador de la API local del Double 3 (/tmp/doubleapi) para desarrollar sin el robot.",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "d3_sim = d3_sim.sim:main"
        ],
    },
)
