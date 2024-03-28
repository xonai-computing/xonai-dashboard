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

import datetime
from dateutil.tz import tzlocal
import unittest
from xonai_grafana.schemata.cloud_objects import ListedCluster, DescribedEmrCluster
from xonai_grafana.tests.utilities import TestUtils


class ListedClusterTestCase(unittest.TestCase):
    def test_active_cluster_parsing(self):
        listed_cluster: ListedCluster = ListedCluster.create_listed_cluster(TestUtils.active_cluster)
        self.assertEqual(listed_cluster.Status.Timeline.EndDateTime, None)
        self.assertEqual(listed_cluster.Status.Timeline.CreationDateTime, datetime.datetime(2023, 7, 27, 15, 58, 25, 798000, tzinfo=tzlocal()))
        self.assertEqual(listed_cluster.Id, "j-_____________")
        self.assertEqual(listed_cluster.Status.State, "RUNNING")
        self.assertEqual(listed_cluster.NormalizedInstanceHours, 0)


class DescribedClusterTestCase(unittest.TestCase):
    def test_cluster_parsing(self):
        described_cluster: DescribedEmrCluster = DescribedEmrCluster.create_dummy('ID', datetime.datetime(2023, 1, 1), datetime.datetime(2023, 1, 2))
        self.assertEqual(described_cluster.Id, 'ID')
        self.assertEqual(described_cluster.Name, 'NA')
        self.assertEqual(described_cluster.Status.State, 'TERMINATED')
        self.assertEqual(described_cluster.NormalizedInstanceHours, 0)
        self.assertEqual(described_cluster.Status.Timeline.CreationDateTime, datetime.datetime(2023, 1, 1))
        self.assertEqual(described_cluster.Status.Timeline.EndDateTime, datetime.datetime(2023, 1, 2))
        # obj method:
        self.assertEqual(described_cluster.get_runtime(), datetime.datetime(2023, 1, 2) - datetime.datetime(2023, 1, 1))

    def test_pydantic_parsing(self):
        described_cluster: DescribedEmrCluster = DescribedEmrCluster.create_dummy('ID', datetime.datetime(2023, 1, 1), datetime.datetime(2023, 1, 2))
        described_dict = described_cluster.__dict__
        reparsed: DescribedEmrCluster = DescribedEmrCluster(**described_dict)
        self.assertEqual(reparsed.Id, 'ID')
        self.assertEqual(reparsed.Name, 'NA')
        self.assertEqual(reparsed.Status.State, 'TERMINATED')
        self.assertEqual(reparsed.NormalizedInstanceHours, 0)
        self.assertEqual(reparsed.Status.Timeline.CreationDateTime, datetime.datetime(2023, 1, 1))
        self.assertEqual(reparsed.Status.Timeline.EndDateTime, datetime.datetime(2023, 1, 2))
        self.assertEqual(reparsed.get_runtime(), datetime.datetime(2023, 1, 2) - datetime.datetime(2023, 1, 1))


if __name__ == '__main__':
    unittest.main()
