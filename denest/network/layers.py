#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# network/layers.py

"""Layer objects."""

import itertools
import logging
import random

import numpy as np

from ..base_object import NestObject
from ..utils import spike_times
from ..utils.validation import ParameterError
from .utils import flatten, if_created, if_not_created

log = logging.getLogger(__name__)


class AbstractLayer(NestObject):
    """Abstract base class for a layer.

    Defines the layer interface.
    """

    def __init__(self, name, params, nest_params):
        super().__init__(name, params, nest_params)
        self._gid = None
        self._gids = None  # list of layer GIDs
        self._layer_locations = {}  # {<gid>: (row, col)}
        self._population_locations = {}  # {<gid>: (row, col, unit_index)}
        self._populations = params["populations"]  # {<population>: <number>}
        self._shape = nest_params["rows"], nest_params["columns"]
        # Record if we change some of the layer units' state probabilistically
        self._prob_changed = False

    #TODO
    def __iter__(self):
        """Iterate on layer locations."""
        yield from itertools.product(range(self.shape[0]), range(self.shape[1]))

    @if_not_created
    def create(self):
        """Create the layer in NEST."""
        raise NotImplementedError

    @property
    def populations(self):
        """Return ``{<population_name>: <number_units>}`` dictionary."""
        return self._populations

    @property
    def layer_shape(self):
        """Return shape of the layer."""
        return self.shape

    @property
    def population_shape(self):
        """Return shape of a population = layer_shape + (pop_n_units,)"""
        return {
            population_name: self.shape + (self.populations[population_name],)
            for population_name in self.population_names()
        }

    @property
    @if_created
    def gid(self):
        """Return the NEST global ID (GID) of the layer object."""
        return self._gid

    @if_created
    def _connect(self, target, nest_params):
        """Connect to target layer. Called by `Connection.create()`"""
        # NOTE: Don't use this method directly; use a Connection instead
        from nest import topology as tp

        tp.ConnectLayers(self.gid, target.gid, nest_params)

    def gids(self, population=None, location=None, population_location=None):
        """Return element GIDs, optionally filtered by population/location.

        Args:
            population (str): Matches population name that has ``population`` as
                a substring.
            location (tuple[int]): The location within the layer to filter
                by.
            population_location (tuple[int]): The location within the population
                to filter by.

        Returns:
            list: The GID(s).
        """
        raise NotImplementedError

    def change_unit_states(
        self, changes_dict, population=None, proportion=1.0, change_type="constant"
    ):
        """Set parameters for some units.

        Args:
            changes_dict (dict): Dictionary specifying changes applied to
                selected units, of the form::
                    {
                        <param_1>: <change_value_1>,
                        <param_2>: <change_value_2>
                    }
                The values are set multiplicatively or without modification
                depending on the ``change_type`` parameter.
            population (str | None): Name of population from which we select
                units. All layer's populations if None.
            proportion (float): Proportion of candidate units to which the
                changes are applied. (default 1.0)
            change_type (str): 'constant' (default) or 'multiplicative'.
                Specifies how parameter values are set from ``change_dict``. If
                "constant", the values in ``change_dict`` are set to the
                corresponding parameters without modification. If
                "multiplicative", the values in ``change_dict`` are multiplied
                to the current value of the corresponding parameter for each
                unit.
        """
        if change_type not in ["constant", "multiplicative"]:
            raise ParameterError(
                "``change_type`` argument should 'constant' or 'multiplicative'"
            )
        if proportion > 1 or proportion < 0:
            raise ParameterError("``proportion`` parameter should be within [0, 1]")
        if not changes_dict:
            return
        if self._prob_changed and proportion != 1.0:
            raise Exception(
                "Attempting to change probabilistically some "
                "units' state multiple times."
            )
        all_gids = self.gids(population=population)
        if proportion != 1.0:
            log.info(f"    Select subset of gids (proportion = {proportion})")
        gids_to_change = self.get_gids_subset(all_gids, proportion)
        log.info(
            '    Apply "%s" parameter changes on %s/%s units (layer=%s, population=%s)',
            change_type,
            len(gids_to_change),
            len(all_gids),
            self.name,
            population,
        )
        self.apply_unit_changes(gids_to_change, changes_dict, change_type=change_type)
        self._prob_changed = True

    @staticmethod
    def apply_unit_changes(gids_to_change, changes_dict, change_type="constant"):
        """Change the state of a list of units."""
        assert change_type in ["constant", "multiplicative"]
        import nest

        if change_type == "constant":
            nest.SetStatus(gids_to_change, changes_dict)
        elif change_type == "multiplicative":
            for gid, (change_key, change_ratio) in itertools.product(
                gids_to_change, changes_dict.items()
            ):
                current_value = nest.GetStatus((gid,), change_key)[0]
                nest.SetStatus((gid,), {change_key: current_value * change_ratio})

    @staticmethod
    def get_gids_subset(gids_list, proportion):
        """Return a proportion of gids picked randomly from a list."""
        return [
            gids_list[i]
            for i in sorted(
                random.sample(range(len(gids_list)), int(len(gids_list) * proportion))
            )
        ]


class Layer(AbstractLayer):
    """Represents a NEST layer composed of populations of units

    Args:
        name (str): Name of the layer
        params (dict-like): Dictionary of parameters. The following parameters
            are expected:
                populations (dict): Dictionary of the form ``{<model>: <number>}
                    specifying the elements within the layer. Analogous to the
                    ``elements`` nest.Topology parameter
        nest_params (dict-like): Dictionary of parameters that will be passed
            to NEST during the ``nest.CreateLayer`` call. The following
            parameters are mandatory: ``['rows', 'columns']``. The
            ``elements`` parameter is reserved. Please use the ``populations``
            parameter instead to specify layer elements.
    """

    # Validation of `params`
    RESERVED_PARAMS = None
    MANDATORY_PARAMS = ["populations"]
    OPTIONAL_PARAMS = {"type": None}
    # Validation of `nest_params`
    RESERVED_NEST_PARAMS = ["elements"]
    MANDATORY_NEST_PARAMS = ["rows", "columns"]
    OPTIONAL_NEST_PARAMS = None

    def __init__(self, name, params, nest_params):
        super().__init__(name, params, nest_params)
        self.nest_params["elements"] = self._build_elements()

    def _build_elements(self):
        """Convert ``populations`` parameters to format expected by NEST

        From the ``populations`` layer parameter, which is a dict of the
        form::
            {
                <population_name>: <number_of_units>
            }
        return a NEST element specification, which is a list of the form::
            [<model_name>, <number of units>]
        """
        populations = self.params["populations"]
        if not populations or any(
            [not isinstance(n, int) for n in populations.values()]
        ):
            raise ParameterError(
                "Invalid format for `populations` parameter {populations} of "
                f"layer {str(self)}: expects non-empty dictionary of the form"
                "`{<population_name>: <number_of_units>}` with integer values"
            )
        # Map types to numbers
        return flatten(
            [population, number] for population, number in populations.items()
        )

    @if_not_created
    def create(self):
        """Create the layer in NEST and update attributes."""
        from nest import topology as tp
        import nest

        self._gid = tp.CreateLayer(self.nest_params)
        self._gids = nest.GetNodes(self.gid)[0]
        # Update _layer_locations: eg ``{gid: (row, col)}``
        # and _population_locations: ``{gid: (row, col, unit_index)}``
        for index, _ in np.ndenumerate(np.empty(self.shape)): # Hacky
            loc_gids = tp.GetElement(self._gid, index[::-1])
            # IMPORTANT: rows and columns are switched in the GetElement query
            for k, gid in enumerate(loc_gids):
                self._layer_locations[gid] = index
                self._population_locations[gid] = index + (k,)
        assert set(self._gids) == set(self._layer_locations.keys())

    @if_created
    def gids(self, population=None, location=None, population_location=None):
        import nest

        return [
            gid
            for gid in self._gids
            if (
                (population is None or nest.GetStatus((gid,), "model")[0] == population)
                and (location is None or self.locations[gid] == location)
                and (population_location is None
                     or self.population_locations[gid] == population_location)
            )
        ]

    @property
    def shape(self):
        """Return layer shape (eg ``(nrows, ncols)``)"""
        return self._shape

    @property
    def layer_shape(self):
        """Return layer shape (eg ``(nrows, ncols)``)"""
        return self.shape

    @property
    def population_shapes(self):
        """Return population shapes: ``{<pop_name>: (nrows, ncols, nunits)``"""
        return {
            pop_name: self.shape + (self.populations[pop_name],)
            for pop_name in self.populations
        }

    @property
    @if_created
    def locations(self):
        """Return ``{<gid>: index}`` dict of locations within the layer."""
        return self._layer_locations

    @property
    @if_created
    def population_locations(self):
        """Return ``{<gid>: index}`` dict of locations within the population.

        There's an extra (last) dimension for the population locations compared
        to the [layer] locations, corresponding to the index of the unit within
        the population.
        """
        return self._population_locations

    @if_created
    @staticmethod
    def position(*args):
        import nest.topology as tp

        return tp.GetPosition(args)

    def population_names(self):
        """Return a list of population names within this layer."""
        return list(self.params["populations"].keys())

    def recordable_population_names(self):
        """Return list of names of recordable population names in this layer."""
        return self.population_names()

    @if_created
    def set_state(self, variable, values, population=None):
        """Set the state of a variable for all units in a layer.

        If value is a 2D array the same size as the layer, set the values of
        variable per location.
        """
        import nest

        if isinstance(values, np.ndarray):
            value_per_location = True
            assert (
                np.shape(values) == self.shape
            ), "Array has the wrong shape for setting layer values"
        for location in self:
            value = values[location] if value_per_location else values
            nest.SetStatus(
                self.gids(population=population, location=location), {variable: value}
            )


class InputLayer(Layer):
    """A layer that provides input to the network.

    ``InputLayer`` extends the ``Layer`` class to handle layers of stimulation
    devices.

    `InputLayer` parameters should specify a single population of stimulation
    devices. A second population of parrot neurons will be created and connected
    one-to-one to the population of stimulators, to allow recording of activity
    in the layer.

    The state of stimulators within the `InputLayer` can be set from an input
    array via the ``InputLayer.set_input`` method.
    """

    # Append ``Layer`` docstring
    __doc__ += "\n".join(Layer.__doc__.split("\n")[1:])

    PARROT_MODEL = "parrot_neuron"
    STIMULATORS = ["spike_generator", "poisson_generator"]

    def __init__(self, name, params, nest_params):

        # TODO make deepcopies everywhere
        import copy

        params = copy.deepcopy(params)

        # Check populations and add a population of parrot neurons
        populations = params["populations"]
        if len(populations) != 1 or list(populations.values())[0] != 1:
            raise ParameterError(
                f"Invalid `population` parameter for `InputLayer` layer {name}."
                f" InputLayers should be composed of a single population of"
                f"stimulation devices, with a single element per location."
                f" Please check the `population` parameter: {populations}"
            )
        # Save the stimulator type
        stimulator_model, nunits = list(populations.items())[0]
        assert nunits == 1
        self.stimulator_model = stimulator_model
        self.stimulator_type = None  # TODO: Check stimulator type
        # Add a parrot population entry
        populations[self.PARROT_MODEL] = 1
        params["populations"] = populations

        # Initialize the layer
        super().__init__(name, params, nest_params)

    def create(self):
        """Create the layer and connect the stimulator and parrot populations"""
        super().create()
        import nest

        # Connect stimulators to parrots, one-to-one
        assert all([n == 1 for n in self.populations.values()])
        stim_gids = []
        parrot_gids = []
        for loc in self:
            stim_gids += self.gids(location=loc, population=self.stimulator_model)
            parrot_gids += self.gids(location=loc, population=self.PARROT_MODEL)
        nest.Connect(stim_gids, parrot_gids, "one_to_one", {"model": "static_synapse"})
        # Get stimulator type
        self.stimulator_type = nest.GetDefaults(self.stimulator_model, "type_id")

    # TODO: DOc
    def set_input(self, input_array, start_time=0.0):
        """Set stimulator state from input_array."""

        if self.stimulator_type not in self.STIMULATORS:
            raise ValueError(
                f"Input can be set for `InputLayer` only for stimulators of the"
                f"following type: {self.STIMULATORS}."
            )

        max_rate = np.max(input_array)
        assert input_array.ndim == 3
        log.info('  Setting input for "%s"', self.name)
        log.info("    Max instantaneous rate: %s Hz", str(max_rate))
        if self.stimulator_type == "poisson_generator":
            log.info(
                "Stimulator is a 'poisson_generator'; using only first frame of the %s stimulus array",
                input_array.shape,
            )
            # Use only first frame
            self.set_state("rate", input_array[0], population=self.stimulator_model)
        elif self.stimulator_type == "spike_generator":
            all_spike_times = spike_times.draw_spike_times(
                input_array, start_time=start_time
            )
            self.set_state(
                "spike_times", all_spike_times, population=self.stimulator_model
            )
        else:
            assert False

    def recordable_population_names(self):
        """Return list of names of recordable population names in this layer."""
        return ["parrot_neuron"]
