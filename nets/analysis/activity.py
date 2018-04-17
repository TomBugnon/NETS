#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# input_encoding.py
"""Utility functions to get statistics about units' activity."""

import itertools
import warnings

import numpy as np


def mean_activity(activity, variable='spikes', interval=None):
    """Return an array containing the mean activity over time for each unit.

    If the activity array contains spikes, multiply the result by 1000/interval
    to obtain firing rates expressed in Hz (rather than spikes per
    slices).
    """
    constant = 1000. / interval if variable == 'spikes' else 1.
    return constant * np.sum(activity, axis=0) / np.size(activity, axis=0)


def isi(spike_train, interval=None):
    """Return the inter-spike intervals of a list-like of 0 and 1."""
    spike_times = [int(t * interval) for t, spike in enumerate(spike_train)
                   if spike]
    if not spike_times:
        return []
    return [
        spike_times[i + 1] - spike_times[i]
        for i in range(len(spike_times) - 1)
    ]


def all_isi(activity, interval=None):
    """Return an array of lists of inter-spike intervals from activity array."""
    _, nrows, ncols = activity.shape
    if not activity.any():
        warnings.warn('Activity array is all 0s. Not computing ISIs.')
        return
    isis = np.empty((nrows, ncols), dtype=list)
    for row, col in itertools.product(range(nrows), range(ncols)):
        isis[row, col] = isi(activity[:, row, col], interval=interval)
    return isis


def all_cv(activity, interval=None):
    """Return array of coefficients of variation. CV = sd(ISI)/mean(ISI)."""
    _, nrows, ncols = activity.shape
    if not activity.any():
        warnings.warn('Activity array is all 0s. No CV computed. Return zeros')
        return np.zeros((nrows, ncols))
    cvs = np.zeros((nrows, ncols))
    for row, col in itertools.product(range(nrows), range(ncols)):
        inter_spike_list = isi(activity[:, row, col], interval=interval)
        if not inter_spike_list:
            cvs[row, col] = 0.0
        else:
            cvs[row, col] = (
                float(np.std(inter_spike_list)) / float(np.mean(inter_spike_list)))
    return cvs
