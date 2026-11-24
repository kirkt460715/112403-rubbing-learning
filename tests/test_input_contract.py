import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from input_audit import inspect_inputs


class InputContractTests(unittest.TestCase):
    def test_all_declared_inputs_can_be_read(self):
        counts = inspect_inputs()
        self.assertTrue(counts)
        self.assertTrue(all(count > 0 for count in counts.values()))


if __name__ == "__main__":
    unittest.main()
