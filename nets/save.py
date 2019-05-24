#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# save.py


"""Save and load movies, networks, activity and simulation parameters."""

# pylint: disable=missing-docstring,ungrouped-imports

import os
import pickle
import shutil
from os.path import abspath, exists, isdir, isfile, join

import numpy as np
import scipy.sparse
import yaml

# Use LIL as the default sparse format
sparse_format = scipy.sparse.lil_matrix # pylint:disable=invalid-name

# Modify along with FILENAME_FUNCS dict (see end of file)
OUTPUT_SUBDIRS = {'params': (),
                  'git_hash': (),
                  'raw_data': ('data',), # Raw recorder data (NEST output)
                  'recorders_formatted': ('data_formatted',), # Formatted recorder data
                  'recorders_metadata': ('data',), # Metadata for recorders (contains filenames and gid/location mappings)
                  'connection_recorders_formatted': ('connection_recorders_formatted',),
                  'connection_recorders_metadata': ('data',),
                  'session_movie': ('sessions',),
                  'session_labels': ('sessions',),
                  'session_metadata': ('sessions',),
                  'session_times': ('sessions',),
                  'connections': ('connection_plots',), # NEST connection plots
                  'dump': ('network_dump',), # Network dump
                  'rasters': ('rasters',),
                  'plots': ('plots',),
                  'measures': ('measures',),
}

# Subdirectories that are cleared if the simulation parameter 'clear_output_dir'
# is set to true.
CLEAR_SUBDIRS = [subdir for subdir in OUTPUT_SUBDIRS.values()]

def output_subdir(output_dir, data_keyword, session_name=None, create_dir=True):
    """Create and return the output subdirectory where a data type is saved.

    Args:
        output_dir (str): path to the main output directory for a simulation.
        data_keyword (str): String designating the type of data for which we
            return an output subdirectory. Should be a key of the OUTPUT_SUBDIRS
            dictionary.
        session_name (str or None): If a session is provided, data is organized
            by subdirectories with that session's name.
    """
    if session_name is None:
        subdir = join(output_dir, *OUTPUT_SUBDIRS[data_keyword])
    else:
        subdir = join(output_dir, *OUTPUT_SUBDIRS[data_keyword], session_name)
    if create_dir:
        os.makedirs(subdir, exist_ok=True)
    return subdir


def output_filename(data_keyword, *args, **kwargs):
    """Return the filename under which a type of data is saved.

    Args:
        data_keyword (str): String designating the type of data for which we
            return a filename.
        *args: Optional arguments passed to the function generating a filename
            for a given data type.
    """
    return FILENAME_FUNCS[data_keyword](*args, **kwargs)


def output_path(output_dir, data_keyword, *args, session_name=None, **kwargs):
    return join(output_subdir(output_dir,
                              data_keyword,
                              session_name=session_name),
                output_filename(data_keyword, *args, **kwargs))


def make_output_dir(output_dir, clear_output_dir=True,
                    delete_subdirs_list=None):
    """Create and possibly clear output directory.

    Create the directory if it doesn't exist.
    If `clear_output_dir` is True, we clear the directory. We iterate over all
    the subdirectories specified in CLEAR_SUBDIRS, and for each of those we:
        - delete all the files
        - delete all the directories whose name is in the `delete_subdirs` list.

    Args:
        output_dir (str):
        clear_output_dir (bool): Whether we clear the CLEAR_SUBDIRS
        delete_subdirs_list (list of str or None): List of subdirectories of
            CLEAR_SUBDIRS that we delete.
    """
    if delete_subdirs_list is None:
        delete_subdirs_list = []
    os.makedirs(output_dir, exist_ok=True)
    if clear_output_dir:
        for clear_dir in [join(output_dir, *subdir)
                          for subdir in CLEAR_SUBDIRS
                          if isdir(join(output_dir, *subdir))]:
            print(f'-> Clearing {clear_dir}')
            # Delete files in the CLEAR_SUBDIRS
            delete_files(clear_dir)
            # Delete the contents of all the delete_subdirs we encounter
            delete_subdirs(clear_dir, delete_subdirs_list)


def delete_files(clear_dir):
    """Delete all files in a directory."""
    for f in os.listdir(clear_dir):
        path = join(clear_dir, f)
        if os.path.isfile(path):
            os.remove(path)

def delete_subdirs(clear_dir, delete_subdirs_list):
    """Delete some subdirectories in a directory."""
    for f in os.listdir(clear_dir):
        path = join(clear_dir, f)
        if os.path.isdir(path) and f in delete_subdirs_list:
            shutil.rmtree(path)

def save_array(path, array):
    """Save array either as dense or sparse depending on data type."""
    try:
        save_sparse(path, array)
    except TypeError:
        np.save(path, array)

# TODO: fix pickle.dump failure for large files
def save_dict(path, dictionary):
    """Save a big dic with pickle."""
    try:
        with open(path, 'wb') as f:
            pickle.dump(dictionary, f)
    except OSError as e:
        msg = (f"Could not save data at {f}! \n"
               f"... Ignoring the following error: {str(e)}`")
        warnings.warn(msg)

def load_dict(path):
    """Load a big dic with pickle."""
    with open(path, 'rb') as f:
        return pickle.load(f)


def load_as_numpy(path):
    """Load as numpy a file saved with ``save_array`` or ``np.save``."""
    ext = os.path.splitext(path)[1]
    if ext == '.npy':
        return np.load(path)
    return load_sparse(path)


def save_as_yaml(path, tree):
    """Save <tree> as yaml file at <path>."""
    with open(path, 'w') as f:
        yaml.dump(tree, f, default_flow_style=False)


def load_yaml(*args):
    """Load yaml file from joined (os.path.join) arguments.

    Return empty list if the file doesn't exist.
    """
    path = join(*args) # pylint:disable=no-value-for-parameter
    if exists(path):
        with open(join(*args), 'rt') as f: # pylint:disable=no-value-for-parameter
            return yaml.load(f)
    else:
        return []

def load(metadata_path, all_unit_indices=True, data_format='df'):
    """Load tabular data from metadata file and return a x_array or pandas df.

    The data files are assumed to be in the same directory as the metadata.

    Args:
        metadata_path (str or Path): Path to the yaml file containing the
            metadata for a recorder.

    Kwargs:
        all_unit_indices (bool): If True, the returned xarray possesses a third
            spatial dimension ("z") corresponding to the index of the unit at a
            given grid location. Otherwise, data for only a single unit at each
            grid location is returned (we index by z=0), and the array has no
            "z" dimension.
        data_format (str): 'df' or 'xarray'

    Returns:
        xarray.Dataset: Contains 'time', 'x', 'y' (and possibly 'z') dimensions.
    """
    print(f"Loading {metadata_path}")
    metadata = load_yaml(metadata_path)
    filepaths = get_filepaths(metadata_path)

    if data_format == 'xarray':
        data = load_as_xarray(metadata['colnames'], metadata['locations'],
                              *filepaths)
        if all_unit_indices:
            return data
        # Index by z=0
        return data.sel(z=0)

    elif data_format == 'df':
        data = load_as_df(metadata['colnames'], metadata['locations'],
                          *filepaths)
        if all_unit_indices:
            return data
        # Index by z=0
        return data.loc[data['z'] == 0]

    else:
        raise Exception('Unrecognized value for `data_format` kwarg')

def load_as_xarray(names, locations, *paths, sep='\t', index_col=False,
                   **kwargs):
    """Load tabular data from one or more files and return a x_array dataset.

    Keyword arguments are passed to ``pandas.read_csv()``.

    Arguments:
        colnames (tuple[str]): The names of the columns.
        locations (dict of int:tuple): Dictionary containing the gid to
            (x,y,z)-positions mappings for the population. Locations are
            3-tuples of int. First two dimensions correspond to x and y
            location in the layer, 3rd dimension corresponds to the "unit
            index" (if there is more than one unit per grid location)
        *paths (filepath or buffer): The file(s) to load data from.

    Returns:
        xarray.Dataset: The loaded data. Contains 'time', 'x', 'y', 'z'
            dimensions
    """
    # Read data from disk
    data = pd.concat(
        pd.read_csv(path, sep=sep, names=names, index_col=index_col, **kwargs)
        for path in paths
    )
    # Add x,y,z spatial location information
    data = assign_locations(data, locations)
    # Index and sort dataframe by time and spatial location
    data.set_index(['time', 'x', 'y', 'z'], inplace=True)
    data = data.sort_index()
    # Return as x_array
    return data.to_xarray()

def load_as_df(names, locations, *paths, sep='\t', index_col=False,
               **kwargs):
    """Load tabular data from one or more files and return a pandas df.

    Keyword arguments are passed to ``pandas.read_csv()``.

    Arguments:
        colnames (tuple[str]): The names of the columns.
        locations (dict of int:tuple): Dictionary containing the gid to
            (x,y,z)-positions mappings for the population. Locations are
            3-tuples of int. First two dimensions correspond to x and y
            location in the layer, 3rd dimension corresponds to the "unit
            index" (if there is more than one unit per grid location)
        *paths (filepath or buffer): The file(s) to load data from.

    Returns:
        xarray.Dataset: The loaded data. Contains 'time', 'x', 'y', 'z'
            dimensions
    """
    # Read data from disk
    data = pd.concat(
        pd.read_csv(path, sep=sep, names=names, index_col=index_col, **kwargs)
        for path in paths
    )
    return assign_locations(data, locations)

def load_session_times(output_dir):
    """Load session time from output dir."""
    return load_yaml(output_path(output_dir, 'session_times'))


def load_session_stim(output_dir, session_name, filt=0):
    """Load full stimulus movie of a session.

    Args:
        output_dir (str): Output directory
        session_name (str): session_name
        filt (int or None): Movie filter. Return all filters if None.
    """
    movie_prefix = output_filename('session_movie', session_name)
    sessions_dir = output_subdir(output_dir, 'session_movie')
    movie_filenames = [f for f in os.listdir(sessions_dir)
                       if f.startswith(movie_prefix)]
    movie = load_as_numpy(join(sessions_dir, movie_filenames[0]))
    if filt is None:
        return movie
    return movie[:, filt]

def load_weight_recorder(output_dir, conn_name, start_trim=None):
    path = output_path(output_dir,
                       'connection_recorders',
                       conn_name)
    w_dict = load_dict(path)
    if start_trim is None:
        return w_dict
    time_i = [i for i, t in enumerate(w_dict['times']) if t >= start_trim]
    return {
        key: data[time_i]
        for key, data in w_dict.items()
    }


def load_files(directory, filename_prefix):
    """Load all files with prefix and concatenate along the second dimension."""
    all_filenames = [f for f in os.listdir(directory)
                     if f.startswith(filename_prefix)
                     and isfile(join(directory, f))]
    # Load the activity arrays and concatenate along the second dimension.
    try:
        return np.concatenate(
            [load_as_numpy(join(directory, filename))
             for filename in all_filenames],
            axis=1
        )
    except ValueError:
        error = (f"Couldn't load filenames with prefix: ``{filename_prefix}``\n"
                 f"...in directory: ``{abspath(directory)}``")
        raise Exception(error)

def load_session_activity(output_dir, layer, population, variable='spikes',
                          session=None, all_units=False):
    # Get all filenames for that population (one per unit index)
    recorders_dir = output_subdir(output_dir, 'recorders',
                                  session_name=session)
    unit_index = None if all_units else 0
    filename_prefix = output_filename('recorders', layer, population,
                                      variable=variable,
                                      unit_index=unit_index)
    return load_files(recorders_dir, filename_prefix)


def load_activity(output_dir, layer, population, variable='spikes',
                  session=None, all_units=False, start_trim=None,
                  end_trim=None, interval=1.0):
    """Load activity of a given variable for a population.

        Args:
            - `output_dir` (str): Output directory,
            - `layer`, `population` (str): Population name,
            - `variable` (str): Loaded variable (default 'spikes'),
            - `session` (str): Session for which the activity is loaded. Loads
                all sessions if None. (default None)
            - `all_units` (bool): Return activity only for one unit at each grid
                location if False (default False)
            - `start_trim`, `end_trim` (int): Duration of activity trimmed at
                the start or the end of the recording (applied after selecting
                activity of a given session)
            - `interval` (int or float): time between two consecutive slices
    """
    # pylint: disable=too-many-arguments

    # Get list of sessions that we load
    if session is None:
        all_session_times = load_session_times(output_dir)
        all_sessions = sorted(list(all_session_times.keys()))
    else:
        all_sessions = [session]

    all_sessions_activity = np.concatenate(
        [
            load_session_activity(output_dir, layer, population,
                                  variable=variable, session=session,
                                  all_units=all_units)
            for session in all_sessions
        ],
        axis=0
    )

    # Possibly trim the beginning and the end, after selecting for session
    min_slice, max_slice = 0, len(all_sessions_activity)
    if start_trim is not None and start_trim > 0:
        min_slice = max(min_slice, int(start_trim / interval))
    if end_trim is not None and end_trim > 0:
        end_trim_slice = len(all_sessions_activity) - int(end_trim / interval)
        max_slice = min(max_slice, end_trim_slice)
    return all_sessions_activity[min_slice:max_slice]


def load_labels(output_dir, session_name):
    """Load labels of a session."""
    return np.load(join(output_subdir(output_dir, 'sessions'),
                        output_filename('session_labels', session_name)))

def load_measure(output_dir, measure_name, session=None, start_trim=None,
                 end_trim=None):
    """Load previously saved measure (eg LFP)"""
    measure_dir = join(output_subdir(output_dir, 'measures'))
    filenames = [f for f in os.listdir(measure_dir)
                 if f.startswith(measure_name)]
    assert len(filenames) == 1
    measure = load_as_numpy(join(measure_dir, filenames[0]))
    # Possibly extract the times corresponding to a specific session
    if session is not None:
        times = load_session_times(output_dir)[session]
    else:
        times = range(len(measure))
    # Possibly trim the beginning and the end, after selecting for session
    if start_trim is not None:
        times = range(min(times) + int(start_trim), max(times))
    if end_trim is not None:
        times = range(min(times), max(times) - int(end_trim))
    return measure[times]

def save_measure(output_dir, measure, measure_name):
    """Save measure as np-array (eg LFP)."""
    path = join(output_subdir(output_dir, 'measures'), measure_name)
    np.save(path, measure)
    return path

# TODO: fix pickle.dump failure for large files
def save_sparse(path, array):
    """Save an array in a sparse format."""
    # Normalize file extension
    path = ensure_ext(path, ext='.pkl')
    # Store shape
    shape = array.shape
    # Ensure 2D
    array = array.reshape(shape[0], -1)
    # Save
    data = {'shape': shape,
            'data': sparse_format(array)}
    try:
        with open(path, 'wb') as f:
            pickle.dump(data, f)
        return True
    except OSError as e:
        msg = (f"Could not save data at {f}! \n"
               f"... Ignoring the following error: {str(e)}`")
        warnings.warn(msg)


def ensure_ext(path, ext='.pkl'):
    """Add a file extension if there isn't one."""
    path, _ext = os.path.splitext(path)
    _ext = _ext or ext
    return path + _ext


def load_sparse(path):
    """Load an array saved with ``save_array``."""
    # Normalize file extension
    path = ensure_ext(path, ext='.pkl')
    # Load
    with open(path, 'rb') as f:
        loaded = pickle.load(f)
    shape, data = loaded['shape'], loaded['data']
    # Convert to dense
    data = data.toarray()
    # Reshape
    return data.reshape(shape)


def recorder_formatted_filename(layer, pop, unit_index=None, variable='spikes',
                      formatting_interval=None):
    """Return filename for a population x unit_index."""
    base_filename = (layer + '_' + pop + '_'
                     + variable)
    suffix = ''
    if unit_index is not None:
        suffix = ('_' + 'units' + '_'
                  + str(unit_index))
    if formatting_interval is not None:
        suffix = suffix + ('_' + 'interval' + '_' + str(formatting_interval))
    return base_filename + suffix


def recorder_metadata_filename(label):
    """Return filename for a recorder from its label."""
    return label


def save_plot(fig, output_dir, filename, overwrite=False):
    """Save matplotlib figure in 'plot' subdirectory."""
    filename = filename.replace('.', ',')
    path = join(output_subdir(output_dir, 'plots'), filename)
    if os.path.exists(path) and not overwrite:
        print(f'Not overwriting file at {path}')
        return
    fig.savefig(path)

def movie_filename():
    return 'session_movie'


def labels_filename():
    return 'session_labels'


def metadata_filename():
    return 'session_metadata'


def session_times_filename():
    return 'session_times'


def params_filename():
    return 'params'


def rasters_filename(layer, pop):
    return 'spikes_raster_' + layer + '_' + pop + '.png'

def git_hash_filename():
    return 'git_hash'


FILENAME_FUNCS = {'params': params_filename,
                  'recorders_formatted': recorder_formatted_filename,
                  'recorders_metadata': recorder_metadata_filename,
                  'connection_recorders': recorder_metadata_filename,
                  'connection_recorders_metadata': recorder_metadata_filename,
                  'session_times': session_times_filename,
                  'session_metadata': metadata_filename,
                  'session_labels': labels_filename,
                  'session_movie': movie_filename,
                  'rasters': rasters_filename,
                  'git_hash': git_hash_filename,
}
