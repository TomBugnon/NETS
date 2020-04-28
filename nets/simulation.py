#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# simulation.py

"""Provides the ``Simulation`` class."""

import logging

from .network import Network
from .io.save import make_output_dir, output_path, output_subdir, save_as_yaml
from .session import Session
from .utils import misc, validation


log = logging.getLogger(__name__)  # pylint: disable=invalid-name


class Simulation(object):
    """Represents a simulation.

    Handles building the network, running it with a series of sessions, and
    saving output.

    Args:
        tree (ParamsTree): Full simulation parameter tree. The following
            ``ParamsTree`` subtrees are expected:

                - ``simulation`` (``ParamsTree``). Defines input and output
                    paths, and the simulation steps performed. The following
                    parameters (`params` field) are recognized:
                        - ``output_dir`` (str): Path to the output directory
                            (default 'output').
                        - ``input_dir`` (str): Path to the directory in which
                            input files are searched for for each session.
                            (default 'input')
                        - ``sessions`` (list(str)): Order in which sessions are
                            run. Elements of the list should be the name of
                            session models defined in the ``session_models``
                            parameter subtree (default [])
                - ``kernel`` (``ParamsTree``): Used for NEST kernel
                    initialization. Refer to ``Simulation.init_kernel`` for a
                    description of kernel parameters.
                - ``session_models`` (``ParamsTree``): Parameter tree, the
                  leaves of which define session models. Refer to ``Sessions``
                  for a description of session parameters.
                - ``network`` (``ParamsTree``): Parameter tree defining the
                  network in NEST. Refer to `Network` for a full description of
                  network parameters.

    Kwargs:
        input_dir (str | None): None or the path to the input. If defined,
            overrides the `input_dir` simulation parameter
        output_dir (str | None): None or the path to the output directory. If
            defined, overrides `output_dir` simulation parameter.
    """

    # Validate children subtrees
    MANDATORY_CHILDREN = []
    OPTIONAL_CHILDREN = ['kernel', 'simulation', 'session_models', 'network']

    # Validate "simulation" params
    # TODO: Check there is no "nest_params"
    MANDATORY_SIM_PARAMS = []
    OPTIONAL_SIM_PARAMS = {
        'sessions': [],
        'input_dir': 'input',
        'output_dir': 'output',
    }

    def __init__(self, tree, input_dir=None, output_dir=None):
        """Initialize simulation.

            - Set input and output paths
            - Initialize NEST kernel and set python seed
            - Initialize and build Network in NEST,
            - Create sessions
            - Save simulation metadata
        """
        # Full parameter tree
        self.tree = tree.copy()

        # Validate params tree
        # ~~~~~~~~~~~~~~~~~~~~~~~~
        # Check that the full tree's data keys are empty
        validation.validate(
            "Full parameter tree", dict(tree.params), param_type='params',
            mandatory=[], optional={})
        validation.validate(
            "Full parameter tree", dict(tree.nest_params),
            param_type='nest_params', mandatory=[], optional={})
        # Check that the full parameter tree has the correct children
        validation.validate_children(
            self.tree, mandatory_children=self.MANDATORY_CHILDREN,
            optional_children=self.OPTIONAL_CHILDREN
        )
        # Validate "simulation" subtree
        # ~~~~~~~~~~~~~~~~~~~~~~~~
        simulation_tree = self.tree.children['simulation']
        # No nest_params in `simulation` subtree
        validation.validate(
            "simulation", dict(simulation_tree.nest_params),
            mandatory=[], optional={}, param_type='nest_params'
        )
        # No children in `simulation` subtree
        validation.validate_children(
            simulation_tree, mandatory_children=[], optional_children=[]
        )
        # Validate `params` and save in `simulation` subtree
        self.sim_params = validation.validate(
            "simulation", dict(simulation_tree.params),
            mandatory=self.MANDATORY_SIM_PARAMS,
            optional=self.OPTIONAL_SIM_PARAMS
        )

        # Incorporate `input_dir` and `output_dir` kwargs
        if output_dir is not None:
            self.sim_params['output_dir'] = output_dir
        self.output_dir = self.sim_params['output_dir']
        # Get input dir
        if input_dir is not None:
            self.sim_params['input_dir'] = input_dir
        self.input_dir = self.sim_params['input_dir']

        # Initialize kernel (should be after getting output dirs)
        log.info('Initializing NEST kernel and seeds...')
        kernel_tree = self.tree.children['kernel']
        # Validate "kernel" subtree
        # No children in `kernel` subtree
        validation.validate_children(
            kernel_tree, mandatory_children=[], optional_children=[]
        )
        self.init_kernel(
            dict(kernel_tree.params),
            dict(kernel_tree.nest_params)
        )
        log.info('Finished initializing kernel')

        # Create sessions
        log.info('Creating sessions...')
        self.sessions_order = self.sim_params['sessions']
        # Get session model params
        session_model_nodes = {
            session_name: session_node
            for session_name, session_node
            in self.tree.children['session_models'].named_leaves()
        }
        # Validate session_model nodes: no nest_params
        for name, node in session_model_nodes.items():
            validation.validate(
                name, dict(node.nest_params),
                mandatory=[], optional={}, param_type='nest_params'
            )
        # Create session objects
        self.sessions = []
        session_start_time = 0
        for i, session_model in enumerate(self.sessions_order):
            self.sessions.append(
                Session(self.make_session_name(session_model, i),
                        dict(session_model_nodes[session_model].params),
                        start_time=session_start_time,
                        input_dir=self.input_dir)
            )
            # start of next session = end of current session
            session_start_time = self.sessions[-1].end
        self.session_times = {
            session.name: (session.start, session.end)
            for session in self.sessions
        }
        log.info('Sessions: %s', self.sessions_order)
        log.info('Finished creating sessions')

        # Create network
        log.info('Creating network...')
        self.network = Network(self.tree.children['network'])
        self.network.create()
        log.info('Finished creating network')

        # Save simulation metadata
        log.info('Saving simulation metadata...')
        self.save_metadata()
        log.info('Finished saving simulation metadata')

    def save_metadata(self):
        """Save simulation metadata.

            - Save parameters
            - Save NETS git hash
            - Save sessions metadata (`Session.save_metadata`)
            - Save session times (start and end kernel time for each session)
            - Save network metadata (`Network.save_metadata`)
        """
        # Initialize output dir (create and clear)
        log.info('Creating output directory: %s', self.output_dir)
        make_output_dir(self.output_dir,
                        clear_output_dir=True)
        # Save params tree
        self.tree.write(output_path(self.output_dir, 'tree'))
        # Drop git hash
        misc.drop_git_hash(self.output_dir)
        # Save sessions
        for session in self.sessions:
            session.save_metadata(self.output_dir)
        # Save session times
        save_as_yaml(output_path(self.output_dir, 'session_times'),
                     self.session_times)
        # Save network metadata
        self.network.save_metadata(self.output_dir)

    def run(self):
        """Run simulation.

            - Run sessions in the order specified by the `sessions` simulation
                parameter
        """
        # Get list of recorders
        log.info('Running %s sessions...', len(self.sessions))
        for session in self.sessions:
            log.info("Running session: '%s'...", session.name)
            session.run(self.network)
            log.info("Done running session '%s'", session.name)
        log.info('Finished running simulation')

    def init_kernel(self, params, nest_params):
        """Initialize NEST kernel and set Python seed

            - Call ``nest.SetKernelStatus`` with ``nest_params``
            - Set NEST kernel ``data_path`` and seed
            - Set Python rng seed for ``numpy`` and ``random`` packages
            - Install extension modules

        Args:
            params (dict-like): Kernel parameters. The following parameters are
                recognized:
                    extension_modules (list(str)): List of modules to install.
                        (default [])
                    nest_seed (int): Used to set NEST kernel's rng seed (default
                        1)
                    python_seed (int): Seed in Python ``numpy`` and ``random``
                        packages. (default 1)
            nest_params (dict-like): Kernel "NEST" parameters, passed to
                ``nest.SetKernelStatus``. The following parameters are reserved:
                ``[data_path, 'grng_seed', 'rng_seed']``. The NEST seeds should
                be set via the ``nest_seed`` kernel parameter parameter.
        """

        MANDATORY_PARAMS = []
        OPTIONAL_PARAMS = {
            'extension_modules': [],
            'nest_seed': 1,
            'python_seed': 1
        }
        RESERVED_NEST_PARAMS = ['data_path', 'msd', 'grng_seed', 'rng_seed']

        # Validate params and nest_params
        params = validation.validate(
            "kernel", params, param_type='params', mandatory=MANDATORY_PARAMS,
            optional=OPTIONAL_PARAMS
        )
        nest_params = validation.validate(
            "kernel", nest_params, param_type='nest_params',
            reserved=RESERVED_NEST_PARAMS
        )

        import nest
        nest.ResetKernel()

        log.info('  Setting NEST kernel status...')
        log.info('    Calling `nest.SetKernelStatus(%s)`', nest_params)
        nest.SetKernelStatus(nest_params)
        # Set data path:
        data_path = output_subdir(self.output_dir, 'raw_data', create_dir=True)
        # Set seed. Do that after after first SetKernelStatus call in case
        # total_num_virtual_procs has changed
        n_vp = nest.GetKernelStatus(['total_num_virtual_procs'])[0]
        msd = params['nest_seed']
        kernel_params = {
            'data_path': str(data_path),
            'grng_seed': msd + n_vp,
            'rng_seeds': range(msd + n_vp + 1, msd + 2 * n_vp + 1),
        }
        log.info('    Calling `nest.SetKernelStatus(%s)', kernel_params)
        nest.SetKernelStatus(kernel_params)
        log.info('  Finished setting NEST kernel status')

        # Install extension modules
        log.info('  Installing external modules...')
        for module in params['extension_modules']:
            self.install_module(module)
        log.info('  Finished installing external modules')

        # Set python seed
        import numpy as np
        import random
        python_seed = params['python_seed']
        log.info('  Setting Python seed: %s', python_seed)
        np.random.seed(python_seed)
        random.seed(python_seed)

    @staticmethod
    def total_time():
        """Return the NEST kernel time."""
        import nest
        return nest.GetKernelStatus('time')

    @staticmethod
    def install_module(module_name):
        """Install module in NEST using nest.Install() and catch errors.

        Even after resetting the kernel, NEST throws a NESTError (rather than a)
        warning when the module is already loaded. I (Tom) couldn't find a way
        to test whether the module is already installed so this function catches
        the error if the module is already installed by matching the error
        message.

        Args:
            module_name (str): Name of the module.
        """
        import nest
        try:
            nest.Install(module_name)
        except nest.NESTError as exception:
            if 'loaded already' in str(exception):
                log.info('Module %s is already loaded', module_name)
                return
            if (
                'could not be opened' in str(exception)
                and 'file not found' in str(exception)
            ):
                log.error('Module %s could not be loaded. Did you compile and install the extension module?', module_name)
                raise exception
            raise

    @staticmethod
    def make_session_name(name, index):
        """Return a formatted session name comprising the session index."""
        return str(index).zfill(2) + '_' + name
