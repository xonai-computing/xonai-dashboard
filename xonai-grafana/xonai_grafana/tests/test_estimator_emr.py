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
import gzip
import json
from os import path
from typing import List
from xonai_grafana.cost_estimation.estimator import Ec2EmrPricing, EmrCostEstimator
from xonai_grafana.schemata.cloud_objects import InstanceResGroup
from xonai_grafana.tests.utilities import TestUtils


class EmrEstimatorTestCase(unittest.TestCase):
    hours_run = None
    instance_group_json = None
    instance_fleet_json = None
    resource_path = None

    @classmethod
    def setUpClass(cls) -> None:
        """Create EMR and EC2 pricing files for tests."""
        resource_path = path.join(path.dirname(path.abspath(__file__)), 'resources')
        emr_file = path.join(path.join(resource_path, 'emr'), 'us-east-1' + '.json.gz')
        ec2_file = path.join(path.join(resource_path, 'ec2'), 'us-east-1' + '.json.gz')
        with gzip.open(emr_file, "wb") as f:
            f.write(json.dumps(TestUtils.sku_info_emr).encode())
        with gzip.open(ec2_file, "wb") as f:
            f.write(json.dumps(TestUtils.sku_info_ec2).encode())
        inst_group_file = path.join(path.join(resource_path, 'emr'), 'list_instance_groups.json.gz')
        inst_fleet_file = path.join(path.join(resource_path, 'emr'), 'list_instance_fleets.json.gz')
        with gzip.open(inst_group_file, mode="rt") as f:
            cls.instance_group_json = json.loads(f.read())
        with gzip.open(inst_fleet_file, mode="rt") as f:
            cls.instance_fleet_json = json.loads(f.read())
        cls.hours_run = 2.5

    def test_info_lookup(self):
        cost_map: Ec2EmrPricing = Ec2EmrPricing('us-east-1', '')
        cost_map.ec2_prices = {'instance1': 1.1, 'instance2': 2.2, 'instance3': 3.3}
        cost_map.emr_prices = {'instance1': 0.1, 'instance2': 0.2, 'instance3': 0.3}
        cost_map.instance_type_info = {'instance1': {'key1': 'value1', 'key2': 'value2'}}
        self.assertFalse(cost_map.available_ec2_price('unknown'))
        self.assertTrue(cost_map.available_ec2_price('instance1'))
        self.assertTrue(cost_map.available_ec2_price('instance2'))
        self.assertTrue(cost_map.available_ec2_price('instance3'))
        self.assertEqual(cost_map.get_ec2_price('instance1'), 1.1)
        self.assertEqual(cost_map.get_ec2_price('instance2'), 2.2)
        self.assertEqual(cost_map.get_ec2_price('instance3'), 3.3)
        self.assertEqual(cost_map.get_ec2_price('unknown'), 0)
        self.assertEqual(cost_map.get_emr_price('instance1'), 0.1)
        self.assertEqual(cost_map.get_emr_price('instance2'), 0.2)
        self.assertEqual(cost_map.get_emr_price('instance3'), 0.3)
        self.assertEqual(cost_map.get_emr_price('unknown'), 0)
        self.assertDictEqual(cost_map.get_instance_info('unknown'), {})
        self.assertDictEqual(cost_map.get_instance_info('instance1'), {'key1': 'value1', 'key2': 'value2'})
        self.assertDictEqual(cost_map.get_instance_info('instance2'), {})
        self.assertDictEqual(cost_map.get_instance_info('instance3'), {})

    def test_cost_parsing(self):
        resource_path = path.join(path.dirname(path.abspath(__file__)), 'resources')
        cost_map: Ec2EmrPricing = Ec2EmrPricing('us-east-1', resource_path)
        # EMR cost map"
        self.assertEqual(cost_map.emr_prices['instance_1'], 0.1)
        self.assertEqual(cost_map.emr_prices['instance_2'], 0.2)
        self.assertEqual(cost_map.emr_prices['instance_3'], 0.3)
        # EC2 cost map:
        self.assertEqual(cost_map.ec2_prices['instance_1'], 1.0)
        self.assertEqual(cost_map.ec2_prices['instance_2'], 2.0)
        self.assertFalse(cost_map.available_ec2_price('instance_3'))  # instance_3 present in EMR map but not in EC2

    def test_ebs_group_estimations(self):
        instance_groups: List[InstanceResGroup] = []
        for group in EmrEstimatorTestCase.instance_group_json['InstanceGroups']:  # simulating EmrCostEstimator._get_instance_groups
            inst_group = InstanceResGroup(group['Id'], group['InstanceType'], group['InstanceGroupType'], EmrCostEstimator._get_ebs_block_devices(group))
            instance_groups.append(inst_group)
        master_group = instance_groups[0]
        self.assertEqual(master_group.group_type, 'MASTER')
        ebs_cost = EmrCostEstimator._estimate_ebs_costs(master_group.ebs_block_devices, EmrEstimatorTestCase.hours_run)
        self.assertEqual(ebs_cost, 15 * 0.1 * 0.931323 * EmrEstimatorTestCase.hours_run / 720)  # "EbsBlockDevices": [] => only root volume cost
        self.assertEqual(ebs_cost, EmrCostEstimator._estimate_root_volume_cost(EmrEstimatorTestCase.hours_run))
        core_group = instance_groups[1]
        self.assertEqual(core_group.group_type, 'CORE')
        ebs_cost = EmrCostEstimator._estimate_ebs_costs(core_group.ebs_block_devices, EmrEstimatorTestCase.hours_run)
        expected = EmrCostEstimator._estimate_root_volume_cost(EmrEstimatorTestCase.hours_run)
        expected += 0.08 * 10 * 0.931323 * EmrEstimatorTestCase.hours_run / 720  # "VolumeType":"gp3", "SizeInGB":10
        expected += 0.1 * 10 * 0.931323 * EmrEstimatorTestCase.hours_run / 720  # "VolumeType":"gp2", "SizeInGB":10
        expected += 0.125 * 50 * 0.931323 * EmrEstimatorTestCase.hours_run / 720  # "VolumeType":"io1", "SizeInGB":50
        self.assertEqual(ebs_cost, expected)
        task_group = instance_groups[2]
        self.assertEqual(task_group.group_type, 'TASK')
        ebs_cost = EmrCostEstimator._estimate_ebs_costs(task_group.ebs_block_devices, EmrEstimatorTestCase.hours_run)
        expected = EmrCostEstimator._estimate_root_volume_cost(EmrEstimatorTestCase.hours_run)
        expected += 0.1 * 10 * 0.931323 * EmrEstimatorTestCase.hours_run / 720  # "VolumeType":"gp2", "SizeInGB":10
        expected += 0.08 * 10 * 0.931323 * EmrEstimatorTestCase.hours_run / 720  # "VolumeType":"gp3", "SizeInGB":10
        expected += 0.125 * 15 * 0.931323 * EmrEstimatorTestCase.hours_run / 720  # "VolumeType":"io1", "SizeInGB":15
        expected += 0.05 * 20 * 0.931323 * EmrEstimatorTestCase.hours_run / 720  # "VolumeType": "standard", "SizeInGB": 20
        expected += 0.045 * 500 * 0.931323 * EmrEstimatorTestCase.hours_run / 720  # "VolumeType": "st1","SizeInGB": 500,
        expected += 0.015 * 500 * 0.931323 * EmrEstimatorTestCase.hours_run / 720  # "VolumeType": "sc1", "SizeInGB": 500
        self.assertEqual(ebs_cost, expected)

    def test_ebs_fleet_estimations(self):
        instance_fleets: List[InstanceResGroup] = []
        for fleet in EmrEstimatorTestCase.instance_fleet_json['InstanceFleets']:  # Simulating EmrCostEstimator._get_instance_fleets
            inst_fleet = InstanceResGroup(fleet['Id'], fleet['InstanceTypeSpecifications'][0]['InstanceType'], fleet['InstanceFleetType'],
                                          EmrCostEstimator._get_ebs_block_devices(fleet['InstanceTypeSpecifications'][0]))
            instance_fleets.append(inst_fleet)
        master_group = instance_fleets[0]
        self.assertEqual(master_group.group_type, 'MASTER')
        ebs_cost = EmrCostEstimator._estimate_ebs_costs(master_group.ebs_block_devices, EmrEstimatorTestCase.hours_run)
        expected = EmrCostEstimator._estimate_root_volume_cost(EmrEstimatorTestCase.hours_run)
        expected += 64 * 0.1 * 0.931323 * EmrEstimatorTestCase.hours_run / 720  # "VolumeType":"gp2", "SizeInGB":32, "VolumeType":"gp2", "SizeInGB":32
        self.assertEqual(ebs_cost, expected)

        core_group = instance_fleets[1]
        self.assertEqual(core_group.group_type, 'CORE')
        ebs_cost = EmrCostEstimator._estimate_ebs_costs(core_group.ebs_block_devices, EmrEstimatorTestCase.hours_run)
        expected = EmrCostEstimator._estimate_root_volume_cost(EmrEstimatorTestCase.hours_run)
        expected += 10 * 0.08 * 0.931323 * EmrEstimatorTestCase.hours_run / 720  # "VolumeType":"gp3","SizeInGB":10
        expected += 10 * 0.1 * 0.931323 * EmrEstimatorTestCase.hours_run / 720  # "VolumeType":"gp2", "SizeInGB":10
        expected += 10 * 0.125 * 0.931323 * EmrEstimatorTestCase.hours_run / 720  # "VolumeType":"io1", "SizeInGB":10
        self.assertEqual(ebs_cost, expected)


if __name__ == '__main__':
    unittest.main()
