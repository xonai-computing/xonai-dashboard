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
from typing import Tuple
from xonai_grafana.cost_estimation.estimator import DbxPricing, DbxClusterType, CostMap


class DbxEstimatorTestCase(unittest.TestCase):
    calc = None

    @classmethod
    def setUpClass(cls) -> None:
        """Initialize Dbx estimator"""
        cls.calc = DbxPricing('dummy-region')
        cls.calc.ec2_prices = {'c6i.12xlarge': 2.04, 'i3.2xlarge': 0.624, 'r6id.xlarge': 0.3024, 'i3.4xlarge': 1.248, 'i3.xlarge': 0.312}
        cls.calc.dbu_info['c6i.12xlarge'] = {(DbxClusterType.ALL_PURPOSE_BASIC, 'enterprise'): (8.34, 5.421), (DbxClusterType.JOB_BASIC, 'enterprise'): (8.34, 1.668), (DbxClusterType.ALL_PURPOSE_BASIC, 'premium'): (8.34, 4.587), (DbxClusterType.JOB_BASIC, 'premium'): (8.34, 1.251), (DbxClusterType.ALL_PURPOSE_BASIC, 'standard'): (8.34, 3.336), (DbxClusterType.JOB_BASIC, 'standard'): (8.34, 0.834), (DbxClusterType.JOB_LIGHT, 'enterprise'): (8.34, 1.0842), (DbxClusterType.JOB_LIGHT, 'premium'): (8.34, 0.834), (DbxClusterType.JOB_LIGHT, 'standard'): (8.34, 0.5838)}
        cls.calc.dbu_info['i3.2xlarge'] = {(DbxClusterType.ALL_PURPOSE_BASIC, 'enterprise'): (2.0, 1.3), (DbxClusterType.JOB_BASIC, 'enterprise'): (2.0, 0.4), (DbxClusterType.ALL_PURPOSE_BASIC, 'premium'): (2.0, 1.1), (DbxClusterType.JOB_BASIC, 'premium'): (2.0, 0.3), (DbxClusterType.ALL_PURPOSE_BASIC, 'standard'): (2.0, 0.8), (DbxClusterType.JOB_BASIC, 'standard'): (2.0, 0.2), (DbxClusterType.JOB_LIGHT, 'enterprise'): (2.0, 0.26), (DbxClusterType.JOB_LIGHT, 'premium'): (2.0, 0.2), (DbxClusterType.JOB_LIGHT, 'standard'): (2.0, 0.14), (DbxClusterType.ALL_PURPOSE_PHOTON, 'enterprise'): (4.0, 2.6), (DbxClusterType.JOB_PHOTON, 'enterprise'): (5.8, 1.16), (DbxClusterType.ALL_PURPOSE_PHOTON, 'premium'): (4.0, 2.2), (DbxClusterType.JOB_PHOTON, 'premium'): (5.8, 0.87), (DbxClusterType.ALL_PURPOSE_PHOTON, 'standard'): (4.0, 1.6), (DbxClusterType.JOB_PHOTON, 'standard'): (5.8, 0.58)}
        cls.calc.dbu_info['r6id.xlarge'] = {(DbxClusterType.ALL_PURPOSE_BASIC, 'enterprise'): (1.02, 0.663), (DbxClusterType.JOB_BASIC, 'enterprise'): (1.02, 0.204), (DbxClusterType.ALL_PURPOSE_BASIC, 'premium'): (1.02, 0.561), (DbxClusterType.JOB_BASIC, 'premium'): (1.02, 0.153), (DbxClusterType.ALL_PURPOSE_BASIC, 'standard'): (1.02, 0.408), (DbxClusterType.JOB_BASIC, 'standard'): (1.02, 0.102), (DbxClusterType.JOB_LIGHT, 'enterprise'): (1.02, 0.1326), (DbxClusterType.JOB_LIGHT, 'premium'): (1.02, 0.102), (DbxClusterType.JOB_LIGHT, 'standard'): (1.02, 0.0714), (DbxClusterType.ALL_PURPOSE_PHOTON, 'enterprise'): (2.04, 1.326), (DbxClusterType.JOB_PHOTON, 'enterprise'): (2.958, 0.5916), (DbxClusterType.ALL_PURPOSE_PHOTON, 'premium'): (2.04, 1.122), (DbxClusterType.JOB_PHOTON, 'premium'): (2.958, 0.4437), (DbxClusterType.ALL_PURPOSE_PHOTON, 'standard'): (2.04, 0.816), (DbxClusterType.JOB_PHOTON, 'standard'): (2.958, 0.2958)}
        cls.calc.dbu_info['i3.4xlarge'] = {(DbxClusterType.ALL_PURPOSE_BASIC, 'enterprise'): (4.0, 2.6), (DbxClusterType.JOB_BASIC, 'enterprise'): (4.0, 0.8), (DbxClusterType.ALL_PURPOSE_BASIC, 'premium'): (4.0, 2.2), (DbxClusterType.JOB_BASIC, 'premium'): (4.0, 0.6), (DbxClusterType.ALL_PURPOSE_BASIC, 'standard'): (4.0, 1.6), (DbxClusterType.JOB_BASIC, 'standard'): (4.0, 0.4), (DbxClusterType.JOB_LIGHT, 'enterprise'): (3.86, 0.5018), (DbxClusterType.JOB_LIGHT, 'premium'): (3.86, 0.386), (DbxClusterType.JOB_LIGHT, 'standard'): (3.86, 0.2702), (DbxClusterType.ALL_PURPOSE_PHOTON, 'enterprise'): (8.0, 5.2), (DbxClusterType.JOB_PHOTON, 'enterprise'): (11.6, 2.32), (DbxClusterType.ALL_PURPOSE_PHOTON, 'premium'): (8.0, 4.4), (DbxClusterType.JOB_PHOTON, 'premium'): (11.6, 1.74), (DbxClusterType.ALL_PURPOSE_PHOTON, 'standard'): (8.0, 3.2), (DbxClusterType.JOB_PHOTON, 'standard'): (11.6, 1.16)}
        cls.calc.dbu_info['i3.xlarge'] = {(DbxClusterType.ALL_PURPOSE_BASIC, 'enterprise'): (1.0, 0.65), (DbxClusterType.JOB_BASIC, 'enterprise'): (1.0, 0.2), (DbxClusterType.ALL_PURPOSE_BASIC, 'premium'): (1.0, 0.55), (DbxClusterType.JOB_BASIC, 'premium'): (1.0, 0.15), (DbxClusterType.ALL_PURPOSE_BASIC, 'standard'): (1.0, 0.4), (DbxClusterType.JOB_BASIC, 'standard'): (1.0, 0.1), (DbxClusterType.JOB_LIGHT, 'enterprise'): (1.0, 0.13), (DbxClusterType.JOB_LIGHT, 'premium'): (1.0, 0.1), (DbxClusterType.JOB_LIGHT, 'standard'): (1.0, 0.07), (DbxClusterType.ALL_PURPOSE_PHOTON, 'enterprise'): (2.0, 1.3), (DbxClusterType.JOB_PHOTON, 'enterprise'): (2.9, 0.58), (DbxClusterType.ALL_PURPOSE_PHOTON, 'premium'): (2.0, 1.1), (DbxClusterType.JOB_PHOTON, 'premium'): (2.9, 0.435), (DbxClusterType.ALL_PURPOSE_PHOTON, 'standard'): (2.0, 0.8), (DbxClusterType.JOB_PHOTON, 'standard'): (2.9, 0.29)}

    def test_info_lookup(self):
        instance_times = {'i3.xlarge': 3440, 'i3.2xlarge': 6900}
        cluster_type = DbxClusterType.ALL_PURPOSE_BASIC
        plan = 'standard'
        ec2_costs: CostMap = {}
        dbus: CostMap = {}
        dbu_costs: CostMap = {}
        for instance, time in instance_times.items():
            instance_costs = self.calc.calculate_ec2_cost(instance, time)
            ec2_costs[instance] = instance_costs
        for instance, time in instance_times.items():
            current_dbus: Tuple[float, float] = self.calc.calculate_dbus_costs(instance, time, cluster_type, plan)
            dbus[instance] = current_dbus[0]
            dbu_costs[instance] = current_dbus[1]
        # EC2 cost estimations:
        self.assertAlmostEqual(ec2_costs['i3.xlarge'], 3440 * 0.312 / 3600.0, places=7)
        self.assertAlmostEqual(ec2_costs['i3.2xlarge'], 6900 * 0.624 / 3600.0, places=7)
        # DBUs estimations:
        self.assertAlmostEqual(dbus['i3.xlarge'], 3440 * 1.0 / 3600.0, places=7)
        self.assertAlmostEqual(dbus['i3.2xlarge'], 6900 * 2.0 / 3600.0, places=7)
        # DBU cost estimations:
        self.assertAlmostEqual(dbu_costs['i3.xlarge'], 3440 * 0.4 / 3600.0, places=7)
        self.assertAlmostEqual(dbu_costs['i3.2xlarge'], 6900 * 0.8 / 3600.0, places=7)
        plan = 'enterprise'
        for instance, time in instance_times.items():
            instance_costs = self.calc.calculate_ec2_cost(instance, time)
            ec2_costs[instance] = instance_costs
        for instance, time in instance_times.items():
            current_dbus: Tuple[float, float] = self.calc.calculate_dbus_costs(instance, time, cluster_type, plan)
            dbus[instance] = current_dbus[0]
            dbu_costs[instance] = current_dbus[1]
        # EC2 cost estimations, no changes:
        self.assertAlmostEqual(ec2_costs['i3.xlarge'], 3440 * 0.312 / 3600.0, places=7)
        self.assertAlmostEqual(ec2_costs['i3.2xlarge'], 6900 * 0.624 / 3600.0, places=7)
        # DBUs estimations, no changes:
        self.assertAlmostEqual(dbus['i3.xlarge'], 3440 * 1.0 / 3600.0, places=7)
        self.assertAlmostEqual(dbus['i3.2xlarge'], 6900 * 2.0 / 3600.0, places=7)
        # DBU cost estimations:
        self.assertAlmostEqual(dbu_costs['i3.xlarge'], 3440 * 0.65 / 3600.0, places=7)
        self.assertAlmostEqual(dbu_costs['i3.2xlarge'], 6900 * 1.3 / 3600.0, places=7)
        cluster_type = DbxClusterType.ALL_PURPOSE_PHOTON
        for instance, time in instance_times.items():
            instance_costs = self.calc.calculate_ec2_cost(instance, time)
            ec2_costs[instance] = instance_costs
        for instance, time in instance_times.items():
            current_dbus: Tuple[float, float] = self.calc.calculate_dbus_costs(instance, time, cluster_type, plan)
            dbus[instance] = current_dbus[0]
            dbu_costs[instance] = current_dbus[1]
        # EC2 cost estimations, no changes:
        self.assertAlmostEqual(ec2_costs['i3.xlarge'], 3440 * 0.312 / 3600.0, places=7)
        self.assertAlmostEqual(ec2_costs['i3.2xlarge'], 6900 * 0.624 / 3600.0, places=7)
        # DBUs estimations, no changes:
        self.assertAlmostEqual(dbus['i3.xlarge'], 3440 * 2.0 / 3600.0, places=7)
        self.assertAlmostEqual(dbus['i3.2xlarge'], 6900 * 4.0 / 3600.0, places=7)
        # DBU cost estimations:
        self.assertAlmostEqual(dbu_costs['i3.xlarge'], 3440 * 1.3 / 3600.0, places=7)
        self.assertAlmostEqual(dbu_costs['i3.2xlarge'], 6900 * 2.6 / 3600.0, places=7)


if __name__ == '__main__':
    unittest.main()
