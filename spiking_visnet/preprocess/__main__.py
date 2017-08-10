#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# preprocess/__main__.py


"""
preprocessing.

~~~~~~~~~~~~~~

Usage:
    python -m spiking_visnet.preprocess <preprocessing_params> <sim_params> [-i <input_dir>]
    python -m spiking_visnet.preprocess -h | --help

Arguments:
    <preprocessing_params>  Relative path to preprocessing parameter yaml file
    <sim_params>            Relative path to full simulation parameter file

Options:
    -i --input=<input_dir>  Input directory. If not specified, uses INPUT_DIR from config.
    -h --help               Show this
"""

import random
import sys

from docopt import docopt

from config import PYTHON_SEED
from user_config import INPUT_DIR

from . import run
from ..parameters import Params

random.seed(PYTHON_SEED)

# Maps CLI options to their corresponding path in the parameter tree.
_SIM_CLI_ARG_MAP = {
    '<sim_params>': ('children', 'simulation', 'param_file_path')
}
_PREPRO_CLI_ARG_MAP = {}


def main():
    """Preprocess inputs from the command line."""
    # Construct a new argument list to allow docopt's parser to work with the
    # `python -m spiking_visnet` calling pattern.
    argv = ['-m', 'spiking_visnet.preprocess'] + sys.argv[1:]
    # Get command-line args from docopt.
    arguments = docopt(__doc__, argv=argv)
    if not arguments['--input']:
        arguments['--input'] = INPUT_DIR
    sim_overrides = Params({_SIM_CLI_ARG_MAP[key]: value
                            for key, value in arguments.items()
                            if key in _SIM_CLI_ARG_MAP})
    prepro_overrides = Params({_PREPRO_CLI_ARG_MAP[key]: value
                            for key, value in arguments.items()
                            if key in _PREPRO_CLI_ARG_MAP})

    run(arguments,
        sim_overrides=sim_overrides,
        prepro_overrides=prepro_overrides)

if __name__ == '__main__':
    main()
