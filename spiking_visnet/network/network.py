#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# network/network.py
"""Provide a class to construct a network from independent parameters."""

import os
import random

from tqdm import tqdm

from .connections import (ConnectionModel, FromFileConnection,
                          RescaledConnection, TopoConnection)
from .layers import InputLayer, Layer
from .models import Model, SynapseModel
from .populations import Population
from .utils import if_not_created, log

# pylint: disable=too-few-public-methods

LAYER_TYPES = {
    None: Layer,
    'InputLayer': InputLayer,
}

CONNECTION_TYPES = {
    'topological': TopoConnection,
    'rescaled': RescaledConnection,
    'from_file': FromFileConnection
}


class Network:
    def __init__(self, params):
        self._created = False
        self._changed = False
        self.params = params
        # Build network components
        # ~~~~~~~~~~~~~~~~~~~~~~~~
        self.neuron_models = self.build_named_leaves_dict(
            Model, self.params.c['neuron_models'])
        self.synapse_models = self.build_named_leaves_dict(
            SynapseModel, self.params.c['synapse_models'])
        self.recorder_models = self.build_named_leaves_dict(
            Model, self.params.c['recorders'])
        # Layers can have different types
        self.layers = {
            name: LAYER_TYPES[leaf['type']](name, leaf)
            for name, leaf in self.params.c['layers'].named_leaves()
        }
        self.connection_models = self.build_named_leaves_dict(
            ConnectionModel, self.params.c['connection_models'])
        # Connections must be built last
        self.connections = sorted([
            self.build_connection(connection)
            for connection in self.params.c['topology']['connections']
        ])
        # Populations are represented as a list
        self.populations = sorted(
            self.build_named_leaves_list(self.build_population,
                                         self.params.c['populations']))

    @staticmethod
    def build_named_leaves_dict(constructor, node):
        return {
            name: constructor(name, leaf)
            for name, leaf in node.named_leaves()
        }

    @staticmethod
    def build_named_leaves_list(constructor, node):
        return [constructor(name, leaf) for name, leaf in node.named_leaves()]

    def build_connection(self, params):
        source = self.layers[params['source_layer']]
        target = self.layers[params['target_layer']]
        model = self.connection_models[params['connection']]
        return CONNECTION_TYPES[model.type](source, target, model, params)

    def build_population(self, pop_name, pop_params):
        # Get the gids and locations for the population from the layer object.
        layer = self.layers[pop_params['layer']]
        return Population(pop_name, layer, pop_params)

    def __repr__(self):
        return '{classname}({params})'.format(
            classname=type(self).__name__, params=(self.params))

    def __str__(self):
        return repr(self)

    def _create_all(self, objects):
        for obj in tqdm(objects):
            obj.create()

    def _layer_call(self, method_name, *args, layer_type=None, **kwargs):
        """Call a method on each input layer."""
        for layer in self._get_layers(layer_type=layer_type):
            method = getattr(layer, method_name)
            method(*args, **kwargs)

    def _layer_get(self, attr_name, layer_type=None):
        """Get an attribute from each layer."""
        return tuple(
            getattr(layer, attr_name)
            for layer in self._get_layers(layer_type=layer_type))

    def _get_layers(self, layer_type=None):
        if layer_type is None:
            return sorted(self.layers.values())
        return [
            l for l in sorted(self.layers.values())
            if type(l).__name__ == layer_type
        ]

    def _get_synapses(self, synapse_type=None):
        if synapse_type is None:
            return sorted(self.synapse_models.values())
        return [
            syn for syn in sorted(self.synapse_models.values())
            if syn.type == synapse_type
        ]

    @property
    def input_shapes(self):
        return set(self._layer_get('shape', layer_type='InputLayer'))

    @property
    def max_input_shape(self):
        """Max of each dimension."""
        return (max([s[0] for s in self.input_shapes]),
                max([s[1] for s in self.input_shapes]))

    @if_not_created
    def create(self, dry_run=False):
        # TODO: use progress bar from PyPhi?
        log.info('Creating neuron models...')
        self._create_all(self.neuron_models.values())
        log.info('Creating synapse models...')
        self._create_all(self.synapse_models.values())
        log.info('Creating recorder models...')
        self._create_all(self.recorder_models.values())
        log.info('Creating layers...')
        self._create_all(self._get_layers())
        log.info('Connecting layers...')
        self._create_all(self.connections)
        self.print_network_size()
        if not dry_run:
            log.info('Creating recorders...')
            self._create_all(self.populations)
        else:
            print('Dry run: -> not creating recorders.')

    def dump_connections(self, output_dir):
        for connection in tqdm(self.connections, desc='Dumping connections'):
            connection.dump(output_dir)

    def change_synapse_states(self, synapse_changes):
        """Change parameters for some connections of a population.

        Args:
            synapse_changes (list): List of dictionaries each of the form::
                    {
                        'synapse_model': <synapse_model>,
                        'params': {<key>: <value>,
                                    ...}
                    }
                where the ``'params'`` key contains the parameters to set for
                all synapses of a given model.
        """
        import nest
        for changes in tqdm(
                sorted(synapse_changes, key=synapse_sorting_map),
                desc="-> Changing synapses's state."):
            nest.SetStatus(
                nest.GetConnections(synapse_model=changes['synapse_model']),
                changes['params'])

    def change_unit_states(self, unit_changes):
        """Change parameters for some units of a population.

        Args:
            unit_changes (list): List of dictionaries each of the form::
                    {
                        'layer': <layer_name>,
                        'layer_type': <layer_type>,
                        'population': <pop_name>,
                        'change_type': <change_type>,
                        'proportion': <prop>,
                        'params': {<param_name>: <param_value>,
                                   ...}
                    }
                where:
                ``<layer_name>`` (default None) is the name of the considered
                    layer. If not specified, changes are applied to all the
                    layers of type <layer_type>.
                ``<layer_type>`` (default None) is the name of the type of
                    layers to which the changes are applied. Should be 'Layer'
                    or 'InputLayer'. Used only if <layer_name> is None.
                ``<population_name>`` (default None) is the name of the
                    considered population. If not specified, changes are applied
                    to all the populations.
                ``<change_type>`` ('multiplicative' or None). If
                    'multiplicative', the set value for each parameter is the
                    product between the preexisting value and the given value.
                    Otherwise, the given value is set without regard for the
                    preexisting value.
                ``<prop>`` (default 1) is the proportion of units of the
                    considered population for which the parameters are changed.
                ``'params'`` (default {}) is the dictionary of parameter changes
                    applied to the selected units.
        """
        for changes in tqdm(
                sorted(unit_changes, key=unit_sorting_map),
                desc="-> Changing units' state"):
            # Pass if no parameter dictionary.
            if not changes['params']:
                continue

            proportion = changes.get('proportion', 1)
            # Avoid probabilistic changes in multiple sessions.
            if self._changed and proportion != 1:
                raise Exception("Attempting to change probabilistically some "
                                "units' state multiple times.")

            # Verbose
            print('--> Applying unit changes dictionary: ', changes)

            # Iterate on all layers of a given subtype or on a specific layer
            change_layer = changes.get('layer', None)
            if change_layer is None:
                layers = self._get_layers(
                    layer_type=changes.get('layer_type', None))
            else:
                layers = [self.layers[change_layer]]

            for layer in layers:

                gids_to_change = self.get_gids_subset(
                    layer.gids(population=changes.get('population', None)),
                    proportion)

                self.apply_unit_changes(gids_to_change, changes)
        self._changed = True

    def reset(self):
        import nest
        nest.ResetNetwork()

    def set_input(self, stimulus, start_time=0.):
        self._layer_call('set_input', stimulus, start_time,
                         layer_type='InputLayer')

    def save(self, output_dir, with_rasters=True):
        # Save synapses
        for conn in self.connections:
            conn.save(output_dir)
        # Save recorders
        for population in tqdm(self.populations,
                               desc='Saving formatted recorders'):
            population.save(output_dir, with_rasters=with_rasters)

    def plot_connections(self, output_dir):
        for conn in tqdm(self.connections, desc='Creating connection plots'):
            conn.save_plot(output_dir)

    @staticmethod
    def print_network_size():
        import nest
        print('------------------------')
        print('Network size (without recorders)')
        print('Number of nodes: ', nest.GetKernelStatus('network_size'))
        print('Number of connections: ',
              nest.GetKernelStatus('num_connections'))
        print('------------------------')

    def populations_by_gids(self, layer_type='Layer'):
        """Return a dictionary of the form {'gid': (layer_name, pop_name)}."""
        all_pops = {}
        for layer in self._get_layers(layer_type=layer_type):
            all_pops.update({
                gid: (layer.name, population)
                for gid, population in layer._populations.items()
            })
        return all_pops

    def dump_connection_numbers(self, ratio_dump_dir):
        """Count the incoming connections by population and synapse type."""
        from ..save import save_as_yaml
        from os.path import join
        from ..utils.autodict import AutoDict, dictify
        import nest

        def increase_autodict_count(autodict, keys):
            """Increase the count or initialize it at 1."""
            if isinstance(autodict[keys], int):
                autodict[keys] += 1
            else:
                # type Autodict of not yet created
                autodict[keys] = 1

        all_connections = nest.GetStatus(nest.GetConnections())
        all_populations_by_gid = self.populations_by_gids(
            layer_type='Layer')  #{gid: (layer, pop)}

        # Use an autodict for easy deep modification with tuples
        connection_summary = AutoDict({})

        for conn in tqdm(all_connections, desc='Dumping connection numbers'):
            layer, pop = all_populations_by_gid.get(conn['target'],
                                                    (None, None))
            if layer is None:
                # We're not interested in InputLayers
                continue
            synapse_name = str(conn['synapse_model'])
            keys = (layer, pop, synapse_name)
            # Add to 'synapse' count.
            increase_autodict_count(connection_summary, keys)

            # Add to 'exc' or 'inh' count
            syn_type = self.synapse_models[synapse_name].type
            if syn_type is None:
                pass
            elif syn_type > 0:
                increase_autodict_count(connection_summary, (layer, pop, 'exc'))
            elif syn_type < 0:
                increase_autodict_count(connection_summary, (layer, pop, 'inh'))

        # Dictify now that we're done with deep modifications
        connection_summary = dictify(connection_summary)
        # Update exc/inh ratio in place
        for layer_numbers in connection_summary.values():
            for pop_numbers in layer_numbers.values():
                pop_numbers['exc_inh_ratio'] = (
                    pop_numbers.get('exc', 0.) / pop_numbers.get('inh', 1e-9))

        save_as_yaml(
            join(ratio_dump_dir, 'synapse_numbers.yml'), connection_summary)


def unit_sorting_map(unit_change):
    """Map by (layer, population, proportion, params_items for sorting."""
    return (unit_change.get('layer', 'None'),
            unit_change.get('layer_type', 'None'),
            unit_change.get('population', 'None'),
            unit_change.get('proportion', '1'),
            sorted(unit_change['params'].items()))


def synapse_sorting_map(synapse_change):
    """Map by (synapse_model, params_items) for sorting."""
    return (synapse_change['synapse_model'],
            sorted(synapse_change['params'].items()))
