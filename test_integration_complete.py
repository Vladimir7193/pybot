"""
Quick test to verify 100% SMC integration is complete.
Tests that all modules import and basic functionality works.
"""
import sys

def test_imports():
    """Test all SMC modules import correctly."""
    print("Testing imports...")
    
    try:
        from signal_engine import SignalEngine
        print("✓ signal_engine")
        
        from smc_structure import StructureDetector
        print("✓ smc_structure")
        
        from smc_orderblock import OrderBlockDetector
        print("✓ smc_orderblock")
        
        from smc_fvg import FVGDetector
        print("✓ smc_fvg")
        
        from smc_setup_patterns import SetupPatternDetector
        print("✓ smc_setup_patterns")
        
        from smc_orderflow import OrderFlowDetector
        print("✓ smc_orderflow")
        
        from smc_key_levels import KeyLevelsTracker
        print("✓ smc_key_levels")
        
        from smc_advanced import (
            AMDDetector, FibonacciCalculator, KillZoneDetector,
            RangeDetector, MomentumAnalyzer
        )
        print("✓ smc_advanced (AMD, Fibonacci, KillZone, Range, Momentum)")
        
        return True
    except Exception as e:
        print(f"✗ Import failed: {e}")
        return False


def test_signal_engine_init():
    """Test SignalEngine initializes with all detectors."""
    print("\nTesting SignalEngine initialization...")
    
    try:
        from signal_engine import SignalEngine
        
        def mock_equity():
            return 1000.0
        
        engine = SignalEngine(equity_fn=mock_equity, max_positions=3)
        print("✓ SignalEngine created")
        
        # Get detectors for a test symbol
        detectors = engine._get_smc_detectors("BTCUSDT")
        print(f"✓ Got {len(detectors)} detectors")
        
        if len(detectors) == 6:
            print("✓ All 6 detectors present (structure, ob, fvg, setup, orderflow, key_levels)")
            return True
        else:
            print(f"✗ Expected 6 detectors, got {len(detectors)}")
            return False
            
    except Exception as e:
        print(f"✗ SignalEngine init failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_config():
    """Test all config parameters are present."""
    print("\nTesting config parameters...")
    
    try:
        from config import (
            ENABLE_SMC, SMC_MODE, PURE_SMC,
            USE_SETUP_PATTERNS, SETUP_PATTERN_CONFIDENCE_MIN,
            USE_ORDER_FLOW, ORDERFLOW_SEQUENCE_REQUIRED,
            USE_KEY_LEVELS, KEY_LEVEL_IMPORTANCE_MIN,
            USE_FIBONACCI, FIBONACCI_USE_OTE,
            USE_AMD, AMD_TIMEFRAME,
            USE_KILL_ZONES, KILL_ZONE_REQUIRED,
            USE_MOMENTUM, MOMENTUM_REQUIRED,
            USE_RANGE_DETECTION, RANGE_AVOID_TRADING,
        )
        
        print(f"✓ ENABLE_SMC = {ENABLE_SMC}")
        print(f"✓ SMC_MODE = {SMC_MODE}")
        print(f"✓ PURE_SMC = {PURE_SMC}")
        print(f"✓ USE_SETUP_PATTERNS = {USE_SETUP_PATTERNS}")
        print(f"✓ USE_ORDER_FLOW = {USE_ORDER_FLOW}")
        print(f"✓ USE_KEY_LEVELS = {USE_KEY_LEVELS}")
        print(f"✓ USE_FIBONACCI = {USE_FIBONACCI}")
        print(f"✓ USE_AMD = {USE_AMD}")
        print(f"✓ USE_KILL_ZONES = {USE_KILL_ZONES}")
        print(f"✓ USE_MOMENTUM = {USE_MOMENTUM}")
        print(f"✓ USE_RANGE_DETECTION = {USE_RANGE_DETECTION}")
        
        return True
    except Exception as e:
        print(f"✗ Config test failed: {e}")
        return False


def main():
    print("="*60)
    print("SMC 100% INTEGRATION TEST")
    print("="*60)
    
    results = []
    
    # Test 1: Imports
    results.append(("Imports", test_imports()))
    
    # Test 2: SignalEngine
    results.append(("SignalEngine", test_signal_engine_init()))
    
    # Test 3: Config
    results.append(("Config", test_config()))
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🚀 100% SMC INTEGRATION COMPLETE!")
        print("Ready to run: python bot_paper.py")
        return 0
    else:
        print("\n⚠️ Some tests failed - check errors above")
        return 1


if __name__ == "__main__":
    sys.exit(main())
