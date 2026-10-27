"""The canonical product guard tells the operator how to recover safely."""
import unittest

from aclad.models import GateError
from aclad.portfolio import validate_offerings


class PortfolioOfferGuidanceTests(unittest.TestCase):
    def test_service_label_is_rejected_with_canonical_product_recovery_guidance(self):
        with self.assertRaises(GateError) as error:
            validate_offerings([{'id': 'core', 'name': 'Implantação e suporte Oracle NetSuite', 'kind': 'netsuite'}])
        self.assertEqual(error.exception.code, 'offering_outside_portfolio')
        self.assertIn('Oracle NetSuite', str(error.exception))
        self.assertIn('partner.services', str(error.exception))


if __name__ == '__main__':
    unittest.main()
