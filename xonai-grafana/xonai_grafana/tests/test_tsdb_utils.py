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
from xonai_grafana.utils.tsdb import TsdbUtils


class TsdbUtilsTestCase(unittest.TestCase):
    metric_data = [{'metric': {'cluster_id': '123'}, 'values': [
        [1709134286, '0.0029774891159397576'], [1709134296, '0.02058002562493466'], [1709134306, '0.02426999374084826'], [1709134316, '0.05332316221171951'],
        [1709134326, '0.07179307334156992'], [1709134336, '0.09799208699403827'], [1709134346, '0.11706503389420564'], [1709134356, '0.1471056427969093'],
        [1709134366, '0.1557967528403148'], [1709134376, '0.1577096856696475'], [1709134386, '0.1825967594590001'], [1709134396, '0.18322686238364183'],
        [1709134406, '0.18410797486206987'], [1709134416, '0.18471637299314925'], [1709134426, '0.18533825363128853'], [1709134436, '0.18603816938604745'],
        [1709134446, '0.1866374770388819']]}]

    def test_stats_utils(self):
        tsdb_utils = TsdbUtils()
        (max_val, mean) = tsdb_utils._summarize_stats([])
        self.assertEqual(max_val, 0)
        self.assertEqual(mean, 0)
        (max_val, mean) = tsdb_utils._summarize_stats([(0, "0.0")])
        self.assertEqual(max_val, 0)
        self.assertEqual(mean, 0)
        (max_val, mean) = tsdb_utils._summarize_stats([(0, "0.0"), (0, "1.0"), (0, "3.0")])
        self.assertEqual(max_val, 3.0)  # max
        self.assertEqual(mean, 4 / 3)  # mean
        (max_val, mean) = tsdb_utils._summarize_stats([(0, "0.0"), (0, "1.5"), (0, "2.5"), (0, "5.4"), (0, "2.1"), (0, "0.5")])
        self.assertEqual(max_val, 5.4)  # max
        self.assertEqual(mean, 2)  # mean
        (max_val, mean) = tsdb_utils._summarize_stats(self.metric_data[0]['values'])
        metric_vals = [float(value[1]) for value in self.metric_data[0]['values']]
        self.assertEqual(max(metric_vals), max_val)
        self.assertEqual(sum(metric_vals) / len(metric_vals), mean)

    def test_lookbacks(self):
        start = 1697875200  # Saturday, 21 October 2023 09:00:00 GMT+01:00
        end = 1697877900  # Saturday, 21 October 2023 09:45:00 GMT+01:00
        lookback = TsdbUtils.get_lookback(start, end)
        self.assertEqual(lookback, '1h')  # range less than one hour
        start = 1688943600  # Monday, 10 July 2023 00:00:00 GMT+01:00
        end = 1689029999  # Monday, 10 July 2023 23:59:59 GMT+01:00
        lookback = TsdbUtils.get_lookback(start, end)
        self.assertEqual(lookback, '24h')  # range slightly less than one day
        start = 1697274000  # Saturday, 14 October 2023 10:00:00 GMT+01:00
        end = 1697877900  # Saturday, 21 October 2023 09:45:00 GMT+01:00
        lookback = TsdbUtils.get_lookback(start, end)
        self.assertEqual(lookback, '168h')  # range slightly less than one week
        start = 1697270400  # Saturday, 14 October 2023 09:00:00 GMT+01:00
        lookback = TsdbUtils.get_lookback(start, end)
        self.assertEqual(lookback, '169h')  # range slightly above a week

    def test_conversion(self):
        unix_s = TsdbUtils.convert_to_unixs('xyz')
        self.assertEqual(unix_s, 0)
        unix_s = TsdbUtils.convert_to_unixs('2024-02-23T14:56:49.000Z')
        self.assertEqual(unix_s, 1708700209)  # GMT: Friday, 23 February 2024 14:56:49

    def test_query_result_parsing(self):
        extracted_value = TsdbUtils.extract_value([])
        self.assertEqual(extracted_value, 0)
        extracted_value = TsdbUtils.extract_value(TestUtils.query_result)
        self.assertEqual(extracted_value, TestUtils.query_result[0]['value'][1])

    def test_value_extraction(self):
        cluster_first = [{'metric': {'cluster_id': 'cid', 'instance': 'iid', 'instance_type': 'i3.xlarge', 'job': 'node_scraper', 'job_cluster': 'false', 'on_driver': 'true', 'spark_version': '14.3.x-scala2.12'}, 'value': [1710334197, '1710172091.361']}, {'metric': {'cluster_id': 'cid', 'instance': 'iid', 'instance_type': 'i3.xlarge', 'job': 'node_scraper', 'job_cluster': 'false', 'on_driver': 'true', 'spark_version': '14.3.x-scala2.12'}, 'value': [1710334197, '1710167280.299']}]
        cluster_last = [{'metric': {'cluster_id': 'cid', 'instance': 'iid', 'instance_type': 'i3.xlarge', 'job': 'node_scraper', 'job_cluster': 'false', 'on_driver': 'true', 'spark_version': '14.3.x-scala2.12'}, 'value': [1710334197, '1710173301.361']}, {'metric': {'cluster_id': 'cid', 'instance': 'iid', 'instance_type': 'i3.xlarge', 'job': 'node_scraper', 'job_cluster': 'false', 'on_driver': 'true', 'spark_version': '14.3.x-scala2.12'}, 'value': [1710334197, '1710170720.299']}]
        start = TsdbUtils.extract_multi_value(cluster_first)
        end = TsdbUtils.extract_multi_value(cluster_last, False)
        self.assertEqual(start, '1710167280.299')
        self.assertEqual(end, '1710173301.361')


if __name__ == '__main__':
    unittest.main()
