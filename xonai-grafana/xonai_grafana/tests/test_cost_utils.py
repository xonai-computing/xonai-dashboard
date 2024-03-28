# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import unittest

from xonai_grafana.tests.utilities import TestUtils
from xonai_grafana.utils.cloud import EmrUtils, ClusterUtils


class EmrUtilsTestCase(unittest.TestCase):
    def test_cost_utils(self):
        self.assertDictEqual(EmrUtils._empty_costmap(), {'TOTAL': 0.0, 'CORE.EC2': 0.0, 'CORE.EMR': 0.0, 'MASTER.EC2': 0.0, 'MASTER.EMR': 0.0, 'MASTER.EBS': 0.0, 'CORE.EBS': 0.0})
        added_costs = ClusterUtils.add_costs([TestUtils.cost_info])
        self.assertEqual(added_costs['TOTAL'], 1.0)
        self.assertEqual(added_costs['CORE.EC2'], 2.0)
        self.assertEqual(added_costs['CORE.EMR'], 3.0)
        self.assertEqual(added_costs['MASTER.EC2'], 4.0)
        self.assertEqual(added_costs['MASTER.EMR'], 5.0)
        self.assertEqual(added_costs['MASTER.EBS'], 6.0)
        self.assertEqual(added_costs['CORE.EBS'], 7.0)
        added_costs = ClusterUtils.add_costs([TestUtils.cost_info, EmrUtils._empty_costmap()])
        self.assertEqual(added_costs['TOTAL'], 1.0)
        self.assertEqual(added_costs['CORE.EC2'], 2.0)
        self.assertEqual(added_costs['CORE.EMR'], 3.0)
        self.assertEqual(added_costs['MASTER.EC2'], 4.0)
        self.assertEqual(added_costs['MASTER.EMR'], 5.0)
        self.assertEqual(added_costs['MASTER.EBS'], 6.0)
        self.assertEqual(added_costs['CORE.EBS'], 7.0)
        added_costs = ClusterUtils.add_costs([TestUtils.cost_info, TestUtils.cost_info])
        self.assertEqual(added_costs['TOTAL'], 2.0)
        self.assertEqual(added_costs['CORE.EC2'], 4.0)
        self.assertEqual(added_costs['CORE.EMR'], 6.0)
        self.assertEqual(added_costs['MASTER.EC2'], 8.0)
        self.assertEqual(added_costs['MASTER.EMR'], 10.0)
        self.assertEqual(added_costs['MASTER.EBS'], 12.0)
        self.assertEqual(added_costs['CORE.EBS'], 14.0)


if __name__ == '__main__':
    unittest.main()
