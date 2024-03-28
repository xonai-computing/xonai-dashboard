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
from datetime import datetime
from dateutil.tz import tzutc
from typing import Dict, Tuple
from xonai_grafana.cost_estimation.estimator import SpotPricing, SpotPriceHistory


class SpotEstimatorTestCase(unittest.TestCase):
    inst_type = 'c4.xlarge'
    avail_zone = 'us-east-1a'
    estimator = SpotPricing(None)

    def test_multi_segments(self):
        spot_price_sample: Dict[Tuple[str, str], SpotPriceHistory] = {
            (self.inst_type, self.avail_zone): {  # real API results
                datetime(2023, 12, 3, 11, 17, tzinfo=tzutc()): 0.0879, datetime(2023, 12, 3, 0, 17, 2, tzinfo=tzutc()): 0.0877,
                datetime(2023, 12, 2, 20, 17, 3, tzinfo=tzutc()): 0.0876, datetime(2023, 12, 2, 13, 17, 7, tzinfo=tzutc()): 0.0875,
                datetime(2023, 12, 2, 5, 47, 11, tzinfo=tzutc()): 0.0873, datetime(2023, 12, 2, 2, 2, 1, tzinfo=tzutc()): 0.0871,
                datetime(2023, 12, 1, 10, 16, 50, tzinfo=tzutc()): 0.087, datetime(2023, 11, 30, 22, 17, 22, tzinfo=tzutc()): 0.0867}}
        self.estimator.spot_prices = spot_price_sample
        start_time = datetime(2023, 12, 1, 10, 0, 0, tzinfo=tzutc())  # 2023-12-01T10:00:00
        end_time = datetime(2023, 12, 3, 13, 0, 0, tzinfo=tzutc())  # 2023-12-03T13:00:00
        estimated_price = self.estimator.estimate_price_for_period(self.inst_type, self.avail_zone, start_time, end_time)
        # Manual calculation
        spot_prices = spot_price_sample[(self.inst_type, self.avail_zone)]
        sorted_price_timestamps = sorted(spot_prices.keys())
        first = ((sorted_price_timestamps[1] - start_time).total_seconds() * spot_prices[sorted_price_timestamps[0]]) / 3600
        second = ((sorted_price_timestamps[2] - sorted_price_timestamps[1]).total_seconds() * spot_prices[sorted_price_timestamps[1]]) / 3600
        third = ((sorted_price_timestamps[3] - sorted_price_timestamps[2]).total_seconds() * spot_prices[sorted_price_timestamps[2]]) / 3600
        fourth = ((sorted_price_timestamps[4] - sorted_price_timestamps[3]).total_seconds() * spot_prices[sorted_price_timestamps[3]]) / 3600
        fifth = ((sorted_price_timestamps[5] - sorted_price_timestamps[4]).total_seconds() * spot_prices[sorted_price_timestamps[4]]) / 3600
        sixth = ((sorted_price_timestamps[6] - sorted_price_timestamps[5]).total_seconds() * spot_prices[sorted_price_timestamps[5]]) / 3600
        seventh = ((sorted_price_timestamps[7] - sorted_price_timestamps[6]).total_seconds() * spot_prices[sorted_price_timestamps[6]]) / 3600
        eight = ((end_time - sorted_price_timestamps[7]).total_seconds() * spot_prices[sorted_price_timestamps[7]]) / 3600
        theoretical_price = first + second + third + fourth + fifth + sixth + seventh + eight
        self.assertEqual(estimated_price, theoretical_price)
        # Appending price point past end date, shouldn't change estimation
        spot_price_sample: Dict[Tuple[str, str], SpotPriceHistory] = {
            (self.inst_type, self.avail_zone): {
                datetime(2023, 12, 3, 16, 17, 5, tzinfo=tzutc()): 0.088,  # added
                datetime(2023, 12, 3, 11, 17, tzinfo=tzutc()): 0.0879, datetime(2023, 12, 3, 0, 17, 2, tzinfo=tzutc()): 0.0877,
                datetime(2023, 12, 2, 20, 17, 3, tzinfo=tzutc()): 0.0876, datetime(2023, 12, 2, 13, 17, 7, tzinfo=tzutc()): 0.0875,
                datetime(2023, 12, 2, 5, 47, 11, tzinfo=tzutc()): 0.0873, datetime(2023, 12, 2, 2, 2, 1, tzinfo=tzutc()): 0.0871,
                datetime(2023, 12, 1, 10, 16, 50, tzinfo=tzutc()): 0.087, datetime(2023, 11, 30, 22, 17, 22, tzinfo=tzutc()): 0.0867}}
        self.estimator.spot_prices = spot_price_sample
        estimated_price = self.estimator.estimate_price_for_period(self.inst_type, self.avail_zone, start_time, end_time)
        self.assertEqual(estimated_price, theoretical_price)
        # Prepending price point before start date, shouldn't change estimation
        spot_price_sample: Dict[Tuple[str, str], SpotPriceHistory] = {
            (self.inst_type, self.avail_zone): {
                datetime(2023, 12, 3, 16, 17, 5, tzinfo=tzutc()): 0.088,
                datetime(2023, 12, 3, 11, 17, tzinfo=tzutc()): 0.0879, datetime(2023, 12, 3, 0, 17, 2, tzinfo=tzutc()): 0.0877,
                datetime(2023, 12, 2, 20, 17, 3, tzinfo=tzutc()): 0.0876, datetime(2023, 12, 2, 13, 17, 7, tzinfo=tzutc()): 0.0875,
                datetime(2023, 12, 2, 5, 47, 11, tzinfo=tzutc()): 0.0873, datetime(2023, 12, 2, 2, 2, 1, tzinfo=tzutc()): 0.0871,
                datetime(2023, 12, 1, 10, 16, 50, tzinfo=tzutc()): 0.087, datetime(2023, 11, 30, 22, 17, 22, tzinfo=tzutc()): 0.0867,
                datetime(2023, 11, 30, 15, 2, 21, tzinfo=tzutc()): 0.0865}  # added
        }
        self.estimator.spot_prices = spot_price_sample
        estimated_price = self.estimator.estimate_price_for_period(self.inst_type, self.avail_zone, start_time, end_time)
        self.assertEqual(estimated_price, theoretical_price)

    def test_short_running(self):
        spot_price_sample = {(self.inst_type, self.avail_zone): {datetime(2023, 11, 30, 22, 17, 22, tzinfo=tzutc()): 0.0867}}
        self.estimator.spot_prices = spot_price_sample
        # Start & end time within same pricing interval
        start_time = datetime(2023, 12, 1, 10, 0, 0, tzinfo=tzutc())
        end_time = datetime(2023, 12, 1, 10, 15, 0, tzinfo=tzutc())  # 900 seconds
        estimated_price = self.estimator.estimate_price_for_period(self.inst_type, self.avail_zone, start_time, end_time)
        theoretical_price = 900 * 0.0867 / 3600
        self.assertEqual(estimated_price, theoretical_price)
        # Adding more price points, shouldn't change calculations
        spot_price_sample: Dict[Tuple[str, str], SpotPriceHistory] = {
            (self.inst_type, self.avail_zone): {
                datetime(2023, 12, 3, 11, 17, tzinfo=tzutc()): 0.0879, datetime(2023, 12, 3, 0, 17, 2, tzinfo=tzutc()): 0.0877,
                datetime(2023, 12, 2, 20, 17, 3, tzinfo=tzutc()): 0.0876, datetime(2023, 12, 2, 13, 17, 7, tzinfo=tzutc()): 0.0875,
                datetime(2023, 12, 2, 5, 47, 11, tzinfo=tzutc()): 0.0873, datetime(2023, 12, 2, 2, 2, 1, tzinfo=tzutc()): 0.0871,
                datetime(2023, 12, 1, 10, 16, 50, tzinfo=tzutc()): 0.087, datetime(2023, 11, 30, 22, 17, 22, tzinfo=tzutc()): 0.0867}}
        self.estimator.spot_prices = spot_price_sample
        estimated_price = self.estimator.estimate_price_for_period(self.inst_type, self.avail_zone, start_time, end_time)
        self.assertEqual(estimated_price, theoretical_price)
        # Start & end times cross one pricing interval boundary
        start_time = datetime(2023, 12, 1, 10, 0, 0, tzinfo=tzutc())
        end_time = datetime(2023, 12, 1, 10, 20, 0, tzinfo=tzutc())
        spot_price_sample = {(self.inst_type, self.avail_zone): {
            datetime(2023, 12, 1, 10, 16, 50, tzinfo=tzutc()): 0.087, datetime(2023, 11, 30, 22, 17, 22, tzinfo=tzutc()): 0.0867}}
        self.estimator.spot_prices = spot_price_sample
        estimated_price = self.estimator.estimate_price_for_period(self.inst_type, self.avail_zone, start_time, end_time)
        theoretical_price = (1010 * 0.0867 / 3600) + (190 * 0.087 / 3600)  # 16min 50s & 0.867 + 3min 10s & 0.087
        self.assertEqual(estimated_price, theoretical_price)
        # Adding more price points, shouldn't change calculations
        spot_price_sample: Dict[Tuple[str, str], SpotPriceHistory] = {
            (self.inst_type, self.avail_zone): {
                datetime(2023, 12, 3, 11, 17, tzinfo=tzutc()): 0.0879, datetime(2023, 12, 3, 0, 17, 2, tzinfo=tzutc()): 0.0877,
                datetime(2023, 12, 2, 20, 17, 3, tzinfo=tzutc()): 0.0876, datetime(2023, 12, 2, 13, 17, 7, tzinfo=tzutc()): 0.0875,
                datetime(2023, 12, 2, 5, 47, 11, tzinfo=tzutc()): 0.0873, datetime(2023, 12, 2, 2, 2, 1, tzinfo=tzutc()): 0.0871,
                datetime(2023, 12, 1, 10, 16, 50, tzinfo=tzutc()): 0.087, datetime(2023, 11, 30, 22, 17, 22, tzinfo=tzutc()): 0.0867}}
        self.estimator.spot_prices = spot_price_sample
        estimated_price = self.estimator.estimate_price_for_period(self.inst_type, self.avail_zone, start_time, end_time)
        self.assertEqual(estimated_price, theoretical_price)

    def test_multi_cluster_select(self):
        actual_prices_1: SpotPriceHistory = {datetime(2024, 2, 23, 16, 2, 29, tzinfo=tzutc()): 0.2976, datetime(2024, 2, 23, 11, 1, 59, tzinfo=tzutc()): 0.2987}
        spot_prices = {('i3.2xlarge', self.avail_zone): actual_prices_1}
        self.estimator.spot_prices = spot_prices
        start_1 = datetime.fromisoformat('2024-02-23 14:57:59.494000+00:00')
        end_1 = datetime.fromisoformat('2024-02-23 16:06:52.064000+00:00')
        estimated_price = self.estimator.estimate_price_for_period('i3.2xlarge', self.avail_zone, start_1, end_1)
        theoretical_price_1 = 0.0
        pivot = datetime(2024, 2, 23, 16, 2, 29, tzinfo=tzutc())
        seconds_passed = (pivot - start_1).total_seconds()
        theoretical_price_1 += (float(seconds_passed) * 0.2987) / 3600.0
        seconds_passed = (end_1 - pivot).total_seconds()
        theoretical_price_1 += (float(seconds_passed) * 0.2976) / 3600.0
        self.assertEqual(estimated_price, theoretical_price_1)
        # second cluster
        actual_prices_2 = {datetime(2024, 2, 25, 11, 17, 1, tzinfo=tzutc()): 0.2983}
        spot_prices = {('i3.2xlarge', self.avail_zone): actual_prices_2}
        self.estimator.spot_prices = spot_prices
        start_2 = datetime.fromisoformat('2024-02-25 15:18:29.939000+00:00')
        end_2 = datetime.fromisoformat('2024-02-25 16:10:06.751000+00:00')
        estimated_price = self.estimator.estimate_price_for_period('i3.2xlarge', self.avail_zone, start_2, end_2)
        theoretical_price_2 = (float((end_2 - start_2).total_seconds()) * 0.2983) / 3600.0
        self.assertEqual(estimated_price, theoretical_price_2)
        # combination of spot prices when multiple clusters were selected
        combined_prices = actual_prices_1 | actual_prices_2
        spot_prices = {('i3.2xlarge', self.avail_zone): combined_prices}
        self.estimator.spot_prices = spot_prices
        estimated_price = self.estimator.estimate_price_for_period('i3.2xlarge', self.avail_zone, start_1, end_1)
        self.assertEqual(estimated_price, theoretical_price_1)
        estimated_price = self.estimator.estimate_price_for_period('i3.2xlarge', self.avail_zone, start_2, end_2)
        self.assertEqual(estimated_price, theoretical_price_2)


if __name__ == '__main__':
    unittest.main()
