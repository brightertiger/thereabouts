"""Compile the checked-in C source; distributors may request the Python wheel."""

import os

from setuptools import Extension, setup

extensions = []
if os.environ.get("THEREABOUTS_PURE_PYTHON") != "1":
    extensions.append(
        Extension(
            "thereabouts.reading._reader_cy",
            ["src/thereabouts/reading/_reader_cy.c"],
        )
    )

setup(ext_modules=extensions)
