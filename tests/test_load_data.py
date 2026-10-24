"""Above MAX_RAM the sampling strategies are recomputed. Each label must load
with its new strategy, and silence must stay background."""
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import lib.load_data
from lib.load_data import rebalance_sampling_strategies_for_memory

# Bytes per sample assumed by the rebalance
SAMPLE_BYTES = 160 * 4 + 32


def entry(strategy, total_size, total_loaded):
    return {
        "strategy": strategy,
        "total_size": total_size,
        "total_loaded": total_loaded,
        "truncate_after": 1000,
        "sample_from_each": -1,
    }


class RebalanceForMemoryTest(unittest.TestCase):
    def test_cap_rewrites_strategies(self):
        strategies = {
            "big": entry("sample", 1000, 1000),
            "small": entry("oversample", 450, 900),
            "silence": entry("background", 1000, 1000),
        }
        # Half the RAM needed, so truncate_after drops from 1000 to 500
        max_ram = 2900 * SAMPLE_BYTES // 2
        with mock.patch.object(lib.load_data, "MAX_RAM", max_ram), \
             mock.patch.object(lib.load_data, "SHOULD_FIT_INSIDE_RAM", True), \
             mock.patch("builtins.print"):
            result = rebalance_sampling_strategies_for_memory(strategies, True)

        self.assertEqual(result["big"]["truncate_after"], 500)
        self.assertEqual(result["big"]["strategy"], "undersample")
        self.assertEqual(result["small"]["strategy"], "sample")
        self.assertEqual(result["silence"]["strategy"], "background")


if __name__ == "__main__":
    unittest.main()
