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
from os import environ
from xonai_grafana.schemata.cloud_objects import SupportedPlatforms
from xonai_grafana.utils.dependencies import get_cloud_env


class InjectionTestCase(unittest.TestCase):
    def test_env(self):
        active_region, activated_platform = get_cloud_env()
        self.assertEqual(active_region, 'us-east-1')  # default
        self.assertEqual(activated_platform, SupportedPlatforms.AWS_EMR)  # default
        environ['ACTIVE_PLATFORM'] = 'AWS_DBX'
        active_region, activated_platform = get_cloud_env()
        self.assertEqual(active_region, 'us-east-1')  # default
        self.assertEqual(activated_platform, SupportedPlatforms.AWS_DBX)
        environ['AWS_REGIONS'] = 'us-west-2'
        active_region, activated_platform = get_cloud_env()
        self.assertEqual(active_region, 'us-west-2')
        self.assertEqual(activated_platform, SupportedPlatforms.AWS_DBX)
        environ['AWS_REGIONS'] = 'us-east-2, us-east-1'
        active_region, activated_platform = get_cloud_env()
        self.assertEqual(active_region, 'us-east-2')
        self.assertEqual(activated_platform, SupportedPlatforms.AWS_DBX)


if __name__ == '__main__':
    unittest.main()
