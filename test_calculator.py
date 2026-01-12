"""
Test script for FIXED Hub Project Status Calculator
Tests with actual list columns (not string representations)
"""

import pandas as pd
import numpy as np
from hub_project_status_calculator_fixed import (
    DataLoader,
    ProjectDataJoiner,
    StatusProgressCalculator,
    HubProjectStatusPipeline
)


def create_synthetic_hub_data_with_lists():
    """Create synthetic hub data with ACTUAL list columns (like your real data)."""
    data = {
        'group': [100, 100, 100, 200, 200, 300],
        'x': [34.81, 34.81, 34.81, 32.07, 32.07, 35.20],
        'y': [32.04, 32.04, 32.04, 34.77, 34.77, 31.26],
        'HubNameHE': ['תל אביב מרכז'] * 3 + ['חיפה'] * 2 + ['באר שבע'],
        'h3_index': [
            '8a2a1072b59ffff',
            '8a2a1072b5affff',
            '8a2a1072b5bffff',
            '8a3969a34d9ffff',
            '8a3969a34daffff',
            '8a2b0a434c1ffff'
        ],
        # ACTUAL LISTS - like your real data
        'intersecting_points': [
            ['proj_001', 'proj_002'],  # actual list
            ['proj_003'],               # actual list
            [],                         # empty list
            ['proj_004', 'proj_005'],   # actual list
            ['proj_006'],               # actual list
            ['proj_007', 'proj_008']    # actual list
        ],
        'intersecting_lines': [
            ['proj_009'],               # actual list
            [],                         # empty list
            ['proj_010'],               # actual list
            [],                         # empty list
            ['proj_011'],               # actual list
            []                          # empty list
        ],
        'intersecting_multilines': [
            [],                         # empty list
            ['proj_012'],               # actual list
            [],                         # empty list
            ['proj_013'],               # actual list
            [],                         # empty list
            ['proj_014', 'proj_015']    # actual list
        ]
    }
    
    return pd.DataFrame(data)


def create_hub_data_with_duplicates():
    """Create hub data with DUPLICATE UIDs within groups to test deduplication."""
    data = {
        'group': [100, 100, 200],
        'x': [34.81, 34.81, 32.07],
        'y': [32.04, 32.04, 34.77],
        'HubNameHE': ['תל אביב מרכז', 'תל אביב מרכז', 'חיפה'],
        'h3_index': [
            '8a2a1072b59ffff',
            '8a2a1072b5affff',
            '8a3969a34d9ffff'
        ],
        # Same project appears in multiple columns - should be deduplicated
        'intersecting_points': [
            ['proj_001', 'proj_002'],
            ['proj_001', 'proj_003'],  # proj_001 appears in group 100 twice!
            ['proj_004']
        ],
        'intersecting_lines': [
            ['proj_002'],  # proj_002 also in points for same group!
            [],
            []
        ],
        'intersecting_multilines': [
            [],
            ['proj_002'],  # proj_002 appears again!
            []
        ]
    }
    
    return pd.DataFrame(data)


def run_basic_test():
    """Run basic test with list columns."""
    print("="*70)
    print("TEST 1: BASIC FUNCTIONALITY WITH LIST COLUMNS")
    print("="*70)
    
    # Create synthetic hub data with lists
    print("\n1. Creating synthetic hub data with list columns...")
    hub_df = create_synthetic_hub_data_with_lists()
    print(f"✓ Created {len(hub_df)} hub hexagons across {hub_df['group'].nunique()} groups")
    print(f"\nData types:")
    print(f"  intersecting_points: {type(hub_df['intersecting_points'].iloc[0])}")
    print(f"  intersecting_lines: {type(hub_df['intersecting_lines'].iloc[0])}")
    print(f"  intersecting_multilines: {type(hub_df['intersecting_multilines'].iloc[0])}")
    
    # Load example project and weights data
    print("\n2. Loading example project and weights data...")
    loader = DataLoader()
    project_df = loader.load_csv('example_data.csv', encoding='utf-8')
    weights_df = loader.load_csv('example_status_weights.csv', encoding='utf-8')
    
    # Initialize pipeline
    print("\n3. Initializing pipeline...")
    pipeline = HubProjectStatusPipeline(
        hub_df=hub_df,
        project_df=project_df,
        status_weights_df=weights_df
    )
    
    # Run pipeline
    print("\n4. Running pipeline...")
    joined_df, progress_df = pipeline.run()
    
    # Display results
    print("\n" + "="*70)
    print("RESULTS")
    print("="*70)
    
    print(f"\n✓ Successfully processed {len(joined_df)} hub-project pairs")
    print(f"✓ Calculated progress for {len(progress_df)} hubs")
    
    if len(joined_df) > 0:
        print("\n📊 Sample Results:")
        print(joined_df[['group', 'uid', 'proj_name', 'Proj_status', 'status_weight']].head(10))
        
        print("\n📈 Progress Summary:")
        print(progress_df)
    else:
        print("\n❌ ERROR: No results generated!")
    
    return joined_df, progress_df


def run_deduplication_test():
    """Test deduplication of UIDs within groups."""
    print("\n\n" + "="*70)
    print("TEST 2: DEDUPLICATION WITHIN GROUPS")
    print("="*70)
    
    # Create hub data with duplicates
    print("\n1. Creating hub data with duplicate UIDs within groups...")
    hub_df = create_hub_data_with_duplicates()
    
    print("\nGroup 100 has:")
    print("  Row 1: points=['proj_001', 'proj_002'], lines=['proj_002']")
    print("  Row 2: points=['proj_001', 'proj_003'], multilines=['proj_002']")
    print("  Expected after dedup: proj_001, proj_002, proj_003 (3 unique)")
    
    # Load example project and weights data
    loader = DataLoader()
    project_df = loader.load_csv('example_data.csv', encoding='utf-8')
    weights_df = loader.load_csv('example_status_weights.csv', encoding='utf-8')
    
    # Initialize joiner only
    print("\n2. Testing ProjectDataJoiner...")
    joiner = ProjectDataJoiner(hub_df, project_df)
    joined_df = joiner.join_to_hubs()
    
    # Check deduplication
    print("\n3. Verifying deduplication...")
    group_100_projects = joined_df[joined_df['group'] == 100]['uid'].unique()
    
    print(f"\nGroup 100 unique projects: {sorted(group_100_projects)}")
    print(f"Count: {len(group_100_projects)} (expected 3)")
    
    if len(group_100_projects) == 3 and set(group_100_projects) == {'proj_001', 'proj_002', 'proj_003'}:
        print("✓ DEDUPLICATION WORKS CORRECTLY!")
    else:
        print("❌ DEDUPLICATION FAILED!")
    
    return joined_df


def run_all_tests():
    """Run all tests."""
    print("╔" + "="*68 + "╗")
    print("║" + " "*10 + "HUB PROJECT STATUS CALCULATOR - FIXED VERSION TESTS" + " "*6 + "║")
    print("╚" + "="*68 + "╝")
    
    # Test 1: Basic functionality
    joined_df1, progress_df1 = run_basic_test()
    
    # Test 2: Deduplication
    joined_df2 = run_deduplication_test()
    
    # Final summary
    print("\n\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    
    test1_pass = len(joined_df1) > 0 and len(progress_df1) > 0
    test2_pass = len(joined_df2[joined_df2['group'] == 100]['uid'].unique()) == 3
    
    print(f"\nTest 1 (Basic Functionality): {'✓ PASS' if test1_pass else '❌ FAIL'}")
    print(f"Test 2 (Deduplication): {'✓ PASS' if test2_pass else '❌ FAIL'}")
    
    if test1_pass and test2_pass:
        print("\n🎉 ALL TESTS PASSED! 🎉")
    else:
        print("\n⚠️  SOME TESTS FAILED")
    
    return joined_df1, progress_df1


if __name__ == "__main__":
    joined_df, progress_df = run_all_tests()
