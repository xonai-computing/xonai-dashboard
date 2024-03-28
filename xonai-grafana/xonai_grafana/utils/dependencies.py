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

"""Module containing dependency injection functionality."""
import boto3
from typing import Tuple
from os import environ
from databricks.sdk import WorkspaceClient
from xonai_grafana.cost_estimation.estimator import EmrCostEstimator, DbxPricing, CostCache
from xonai_grafana.schemata.cloud_objects import SupportedPlatforms, AllClusters, ClusterCache
from xonai_grafana.utils.logging import LoggerUtils
from xonai_grafana.utils.tsdb import TsdbUtils


logger = LoggerUtils.create_logger('dependencies')


def get_cloud_env() -> Tuple[str, SupportedPlatforms]:
    """Gets called before the app starts, returns the configured region and platform from env variables."""
    configured_platform = environ.get('ACTIVE_PLATFORM')
    activated_platform = SupportedPlatforms.AWS_EMR  # EMR as default if ACTIVE_PLATFORM variable not set
    if configured_platform == SupportedPlatforms.AWS_DBX.name:
        activated_platform = SupportedPlatforms.AWS_DBX
    supplied_regions = environ.get('AWS_REGIONS')
    active_region = 'us-east-1'  # default if AWS_REGIONS variable not set
    if supplied_regions is not None and supplied_regions != '':
        first_region = supplied_regions.split(',')[0]
        if first_region not in AllClusters.aws_regions:
            logger.warning('Supplied first region in %s is unknown, ignoring', supplied_regions)
        else:
            active_region = first_region
    return active_region, activated_platform


class Inject:
    """Class for dependency injection, holds cloud clients and cluster caches."""
    def __init__(self, region: str, platform: SupportedPlatforms):
        self.current_region = region
        self.platform = platform
        self.tsdb_client = TsdbUtils()
        if self.platform is SupportedPlatforms.AWS_EMR:
            self.cluster_cache: ClusterCache = {}  # cache for cluster descriptions of terminated clusters
            self.cost_cache: CostCache = {}  # cache for cluster costs of terminated clusters
            self.client_emr = boto3.client('emr', region_name=self.current_region)
            self.client_ec2 = boto3.client('ec2', region_name=self.current_region)
            self.calc = EmrCostEstimator(emr_client=self.client_emr, ec2_client=self.client_ec2, region=self.current_region)
        elif self.platform is SupportedPlatforms.AWS_DBX:
            self.client_dbx = WorkspaceClient()
            self.calc = DbxPricing(self.current_region)

    def reinitialize(self, selected_region) -> None:
        """Gets called when a user changes the region variable in a dashboard."""
        if selected_region == self.current_region:
            logger.warning('Initiation attempted but selected region %s has not changed', selected_region)
            return
        logger.info('Initiating a region change from %s to %s', self.current_region, selected_region)
        self.close_aws_clients()
        self.current_region = selected_region
        if self.platform is SupportedPlatforms.AWS_EMR:
            self.client_emr = boto3.client('emr', region_name=self.current_region)
            self.client_ec2 = boto3.client('ec2', region_name=self.current_region)
            self.calc = EmrCostEstimator(emr_client=self.client_emr, ec2_client=self.client_ec2, region=self.current_region)
        elif self.platform is SupportedPlatforms.AWS_DBX:
            self.calc = DbxPricing(self.current_region)

    def close_aws_clients(self) -> None:
        """Close AWS clients after a region change occurred."""
        logger.debug('Closing clients')
        if self.platform is SupportedPlatforms.AWS_EMR:
            self.client_emr.close()
            self.client_ec2.close()
            self.calc.close_clients()
