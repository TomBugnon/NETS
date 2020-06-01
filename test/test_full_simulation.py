#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# test_full_simulation.py

"""Regression testing of the full simulation outputs."""

import pickle

import pytest

import denest
import denest.io.load

PARAMS_PATH = "./params/tree_paths.yml"
INPUT_DIR = "./input"
OUTPUT_DIR = "./output"


@pytest.fixture(scope="module")
def output_dir():
    denest.run(PARAMS_PATH, input_dir=INPUT_DIR, output_dir=OUTPUT_DIR)
    return OUTPUT_DIR


@pytest.fixture(scope="module")
def metadata_paths(output_dir):
    return denest.io.load.metadata_paths(output_dir,)


def test_parameter_tree(output_dir, data_regression):
    params_tree = denest.io.load.load_yaml(denest.io.load.output_path(output_dir, "tree"))
    data_regression.check(params_tree)


def test_session_times(output_dir, data_regression):
    session_times = denest.io.load.load_session_times(output_dir)
    data_regression.check(session_times)


def test_recorder_metadata(metadata_paths, data_regression):
    # Load metadata for all recorders
    all_metadatas = {}
    for metadata_path in metadata_paths:
        metadata = denest.io.load.load_yaml(metadata_path)
        all_metadatas[str(metadata_path)] = metadata
    # Compare all
    data_regression.check(all_metadatas)


def test_data(metadata_paths, file_regression):
    # Test equality of sorted data, rounded to 4 decimals
    all_datas = {}
    for metadata_path in metadata_paths:
        recorder_data = denest.io.load.load(metadata_path)
        # Sort dataframe and round 4
        all_datas[str(metadata_path)] = (
            recorder_data.sort_values(list(recorder_data.columns))
            .reset_index(drop=True)
            .round(4)
            .fillna("NaN")
        )
    file_regression.check(pickle.dumps(all_datas), binary=True, extension="")
