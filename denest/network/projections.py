#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# network/projections.py

"""ProjectionModel and Projection objects."""

from ..base_object import NestObject
from ..utils.validation import ParameterError
from .utils import if_not_created


class BaseProjectionModel(NestObject):
    """Represent a NEST projection model.

    Projection objects inherit ``nest_params`` and ``params`` attributes from
    ProjectionModel objects.

    Args:
        name (str): Name of the projection model.
        params (dict-like): Dictionary of parameters. The following parameters
            are recognized:
                type (str): Type of projection. Currently, only projections of
                    type 'topological' are supported
        nest_params (dict-like): Dictionary of parameters that will be passed
            to NEST during the ``tp.ConnectLayer`` call. The following
            parameters are mandatory: ``['synapse_model'``. The ``sources`` and
            ``targets`` NEST parameters are reserved. The source and target
            populations are set by ``Projection`` objects via the
            ``source_population`` and ``target_population`` projection
            parameters.
    """

    # RESERVED_PARAMS = []
    # MANDATORY_PARAMS = []
    # OPTIONAL_PARAMS = {}
    # # Validation of `nest_params`
    # RESERVED_NEST_PARAMS = []
    # MANDATORY_NEST_PARAMS = []
    # OPTIONAL_NEST_PARAMS = {}

    def __init__(self, name, params, nest_params):
        super().__init__(name, params, nest_params)
        self._type = self.params["type"]
        # Check that the projection types are recognized and nothing is missing.
        assert self.type in ["topological", "multisynapse"]

    @property
    def type(self):
        return self._type


class TopoProjectionModel(BaseProjectionModel):
    """Projection model for topological connections."""

    RESERVED_PARAMS = []
    MANDATORY_PARAMS = []
    OPTIONAL_PARAMS = {
        "type": "topological",
    }
    # Validation of `nest_params`
    RESERVED_NEST_PARAMS = ["sources", "targets"]
    MANDATORY_NEST_PARAMS = ["synapse_model", "connection_type"]
    OPTIONAL_NEST_PARAMS = None


# Backward compatibility
class ProjectionModel(TopoProjectionModel):
    pass


# Backward compatibility
class MultiSynapseProjectionModel(BaseProjectionModel):
    """Projection model for multisynapse projections."""

    RESERVED_PARAMS = []
    MANDATORY_PARAMS = ["query_synapse_label"]
    OPTIONAL_PARAMS = {
        "type": "multisynapse",
        "make_symmetric": False,
    }
    # Validation of `nest_params`
    RESERVED_NEST_PARAMS = [
        "sources", "targets", "connection_type", "synapse_model"
    ]
    MANDATORY_NEST_PARAMS = ["model"]
    OPTIONAL_NEST_PARAMS = None


class BaseProjection(NestObject):
    """Base class for all population-to-population projections.

    A Projection consists in synapses between two populations that have a
    specific projection model. Population-to-population projections are
    specified in the ``projections`` network/topology parameter. Projection
    models are specified in the ``projection_models`` network parameter.

    ``(<projection_model_name>, <source_layer_name>, <source_population_name>,
    <target_layer_name>, <target_population_name>)`` tuples fully specify each
    individual projection and should be unique. Refer to
    ``Network.build_projections`` for a description of how these arguments are
    parsed.

    Projection weights can be recorded by 'weight_recorder' devices,
    represented by ProjectionRecorder objects. Because the weight recorder
    device's GID must be specified in a synapse model's default parameters
    (using nest.SetDefaults or nest.CopyModel), the actual NEST synapse model
    used by a projection (`self.nest_synapse_model`) might be different from the
    one specified in the projection's parameters (`self.base_synapse_model`)

    Args:
        model (``ProjectionModel``): ``ProjectionModel`` object. The ``params``
            and ``nest_params`` parameter dictionaries are inherited from the
            ``ProjectionModel`` object.
        source_layer, target_layer (``Layer``): source and target Layer object
        source_population, target_population (str | None): Name of the
            source and target population. If None, all populations are used.
            Wrapper for the ``sources`` and ``targets`` ``nest.ConnectLayers``
            parameters.
    """

    # TODO: Make some methods private?
    # pylint: disable=too-many-instance-attributes,too-many-public-methods

    def __init__(
        self, model, source_layer, source_population, target_layer, target_population
    ):
        """Initialize Projection object."""
        # Inherit params and nest_params from projection model
        super().__init__(model.name, model.params, model.nest_params)
        ##
        # Define the source and targets
        self.model = model
        self.source = source_layer
        self.target = target_layer
        self.source_population = source_population
        self.target_population = target_population
        # Key containing synapse_model. Either "synapse_model" (topological
        # connections using Tp.ConnectLayer) or "model" (connections using
        # nest.Connect).
        self.synapse_model_key = None
        assert self.model.params['type'] in ['topological', 'multisynapse']
        if self.model.params['type'] == 'topological':
            self.synapse_model_key = 'synapse_model'
        elif self.model.params['type'] == 'multisynapse':
            self.synapse_model_key = 'model'
        assert self.synapse_model_key in self.nest_params
        # Base synapse model is retrieved from nest_params. If a weight_recorder
        # is created for this projection, a different synapse model will be used
        self._base_synapse_model = self.nest_params[self.synapse_model_key]
        self._nest_synapse_model = self.nest_params[self.synapse_model_key]
        self._validate_projection()

    # Properties:
    @property
    def base_synapse_model(self):
        """Return synapse model specified in Projection's model."""
        return self._nest_synapse_model

    @property
    def nest_synapse_model(self):
        """Return synapse model used in NEST for this projection.

        May differ from self.base_synapse_model to allow recording to a
        weight_recorder.
        """
        return self._nest_synapse_model

    def __str__(self):
        return "-".join(
            [
                self.name,
                self.source.name,
                str(self.source_population),
                self.target.name,
                str(self.target_population),
            ]
        )

    def __lt__(self, other):
        return self.__str__() < other.__str__()

    # Creation and projection

    @if_not_created
    def create(self):
        """Create the projections in NEST and the projection recorders."""
        pass

    def _connect_projection_recorder(
        self, recorder_type="weight_recorder", recorder_gid=None
    ):
        """Create and use new synapse model connected to a ProjectionRecorder.

        The new `nest_synapse_model` will be used during creation rather than
        the `base_synapse_model` specified in the nest parameters.
        """
        import nest

        if recorder_type == "weight_recorder":
            # If we want to record the synapse, we create a new model and change
            # its default params so that it connects to the weight recorder
            self._nest_synapse_model = self._nest_synapse_model_name()
            nest.CopyModel(
                self._base_synapse_model,
                self._nest_synapse_model,
                {recorder_type: recorder_gid},
            )
            # Use modified synapse model for projection
            self.nest_params[self.synapse_model_key] = self._nest_synapse_model
        else:
            raise ParameterError(
                f"ProjectionRecorder type `{recorder_type}` not recognized"
            )

    def _nest_synapse_model_name(self):
        return f"{self._base_synapse_model}-{self.__str__()}"

    # Save and plot stuff
    def save(self, output_dir):
        pass

    def _validate_projection(self):
        """Check the projection to avoid bad errors.

        Raise ValueError if:
            1. ``InputLayer`` layers are never targets
            2. The source population of ``InputLayer`` layers is
                ``parrot_neuron``
        """

        if type(self.target).__name__ == "InputLayer":
            raise ValueError(
                f"Invalid target in projection {str(self)}: `InputLayer` layers"
                f" cannot be projection targets."
            )
        if (
            type(self.source).__name__ == "InputLayer"
            and self.source_population != self.source.PARROT_MODEL
        ):
            raise ValueError(
                f"Invalid source population for projection {str(self)}: "
                f" the source population of projections must be"
                f"{self.source.PARROT_MODEL} for `InputLayer` layers"
            )


class TopoProjection(BaseProjection):
    """Represent a topological projection."""

    def __init__(self, *args):
        super().__init__(*args)
        if self.source_population:
            self.nest_params["sources"] = {"model": self.source_population}
        if self.target_population:
            self.nest_params["targets"] = {"model": self.target_population}

    # Creation functions not inherited from BaseProjection

    @if_not_created
    def create(self):
        """Create the projections in NEST using ``tp.ConnectLayers``."""
        self.source._connect(self.target, self.nest_params)


class MultiSynapseProjection(BaseProjection):
    """Replicate an existing labelled connection with different parameters.

    We use this type of connection as a workaround to connect the same pairs of
    neurons multiple times. See
    https://github.com/nest/nest-simulator/issues/905

    Usage:
        Say we want to duplicate the specific connection `proj1`, which uses the
        synapse AMPA, with different weights/synapse_models/etc.
        1 - Set the `synapse_label` SynapseModel parameter to a unique value for
            proj1 (note that the synapse
            model must accept labels, eg `static_synapse_lbl`).
        2 - Define a projection model of type `multisynapse`. Set the
            `query_synapse_label` param to the same value as the
            `synapse_label` of `proj2`
        3 - Define a specific connection `proj2` with the same source and target
            population as `proj1`, and the `multisynapse` connection_model.
            The connections between the source/target population with the
            synapse label <query_synapse_label> will be duplicated with
            different parameters using a nest.Connect call
    """

    def __init__(self, *args):
        super().__init__(*args)
        # Label used to query the connections
        self.query_synapse_label = self.params['query_synapse_label']
        assert self.query_synapse_label is not None
        # Make symmetric flag is passed during the nest.Connect() call
        self.make_symmetric = self.params['make_symmetric']

    @if_not_created
    def create(self):
        """Create the projections in NEST using ``nest.Connect``."""
        # Get the connections that have the proper query label and src/tgt pop
        import nest
        all_label_conns = nest.GetConnections(
            synapse_label=self.query_synapse_label
        )
        src_pop_gids = self.source.gids(population=self.source_population)
        tgt_pop_gids = self.target.gids(population=self.target_population)
        conns = [
            c for c in all_label_conns
            if c[0] in src_pop_gids and c[1] in tgt_pop_gids
        ]
        if not conns:
            raise ParameterError(
                "Could not find any connection in network with label "
                f"`query_synapse_label` == {self.query_synapse_label}."
            )
        srcs, tgts, _, _, _ = zip(*conns)
        # Add additional connections only for those connections
        nest.Connect(
            srcs,
            tgts,
            conn_spec={
                'rule': 'one_to_one',
                'make_symmetric': self.make_symmetric,
            },
            syn_spec=self.nest_params,
        )
