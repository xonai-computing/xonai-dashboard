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
from typing import List, Dict
from xonai_grafana.schemata.grafana_objects import GrafanaTables, TableResponse


class GrafanaTableTestCase(unittest.TestCase):
    def test_helper_responses(self):
        ext_core_columns: List[Dict[str, str]] = GrafanaTables._get_cluster_ext_columns()
        self.assertIn({"text": "Name", "type": "string"}, ext_core_columns)
        self.assertIn({"text": "Cluster Id", "type": "string"}, ext_core_columns)
        self.assertIn({"text": "Status", "type": "string"}, ext_core_columns)
        self.assertIn({"text": "Creation Time", "type": "date"}, ext_core_columns)
        self.assertIn({"text": "Termination Time", "type": "date"}, ext_core_columns)
        self.assertIn({"text": "Creation Redirect", "type": "date"}, ext_core_columns)
        self.assertIn({"text": "Termination Redirect", "type": "date"}, ext_core_columns)

    def test_panel_responses(self):
        table: TableResponse = GrafanaTables.get_emr_clist_table([], [], [])
        self.assertEqual(table.type, 'table')
        self.assertIn({"text": "Norm. Inst. Hours", "type": "integer"}, table.columns)
        self.assertIn({"text": "Tags", "type": "list"}, table.columns)
        self.assertIn({"text": "Name", "type": "string"}, table.columns)
        self.assertIn({"text": "Cluster Id", "type": "string"}, table.columns)
        self.assertIn({"text": "Status", "type": "string"}, table.columns)
        self.assertIn({"text": "Creation Time", "type": "date"}, table.columns)
        self.assertIn({"text": "Termination Time", "type": "date"}, table.columns)
        self.assertIn({"text": "Creation Redirect", "type": "date"}, table.columns)
        self.assertIn({"text": "Termination Redirect", "type": "date"}, table.columns)


if __name__ == '__main__':
    unittest.main()
