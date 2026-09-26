"""Checks for comparable search scopes and immutable partition evidence."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from final_code.compare_runs import collect
from final_code.problem4.solver import validate_frozen_partition, run
from tests.test_audit_q4 import frozen_fixture


class ReviewTests(unittest.TestCase):
    def test_comparison_rejects_different_q3_scopes(self):
        with tempfile.TemporaryDirectory() as temp:
            roots = [Path(temp) / name for name in ('independent', 'coupled')]
            for root, groups in zip(roots, (0, 3)):
                root.mkdir()
                (root / 'manifest.json').write_text(json.dumps({
                    'input_sha256': {'data/input': 'same'},
                    'parameters': {'q3_partition_groups': groups}}))
            with patch('final_code.compare_runs.q3_gate', return_value={'ready': False}):
                with self.assertRaisesRegex(ValueError, 'scopes'):
                    collect(roots)

    def test_saved_transport_rejects_duplicate_and_orphan_deliveries(self):
        from final_code.replay import load_transport
        from final_code.problem2.transport import load_task_boxes
        from tests.test_audit_q4 import write_csv
        box = load_task_boxes()[0]
        row = {'货箱编号': box.code, '服务区编号': box.site, '架次编号': 'T1',
               '交付完成时刻（s）': 100}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_csv(root / 'box_delivery_audit.csv', [row, row])
            with self.assertRaisesRegex(ValueError, 'Duplicate'):
                load_transport(root, None)
            write_csv(root / 'box_delivery_audit.csv', [row])
            write_csv(root / 'sorties_audit.csv', [{'架次编号': 'T2'}])
            with self.assertRaisesRegex(ValueError, 'unknown sorties'):
                load_transport(root, None)

    def test_frozen_gate_rejects_changed_screening_and_old_policy(self):
        from final_code.problem4.solver import RESOURCE_KEYS
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = frozen_fixture(root)
            with patch('final_code.problem4.solver.load_inventory', return_value={k: 30 for k in RESOURCE_KEYS}), \
                 patch('final_code.problem4.solver._battery_full_charge_s', return_value={'A': 100}):
                result = run(source, root / 'q4')
            validate_frozen_partition(source, result)
            with self.assertRaisesRegex(ValueError, 'policy'):
                validate_frozen_partition(source, {**result, 'partition_policy': 'duplicate'})
            (source / 'screening.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'changed'):
                validate_frozen_partition(source, result)


if __name__ == '__main__':
    unittest.main()
