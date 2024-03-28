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

"""Module containing cloud platform domain objects."""
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, Optional, List, Tuple, Self
from databricks.sdk.service.compute import ClusterDetails, ClientsTypes
from pydantic import BaseModel


class SupportedPlatforms(Enum):
    """All platforms for which this backend can be activated."""
    AWS_EMR = 1
    AWS_DBX = 2
    # ToDo: Add support for additional platforms


"""Cloud cluster entities from here until the end of the file."""


class AllClusters:
    """
        General fields relevant for different cluster types. Some placed here to prevent circular imports.
        AWS regions are based on https://docs.aws.amazon.com/general/latest/gr/emr.html.
    """
    aws_regions = {'us-east-2', 'us-east-1', 'us-west-1', 'us-west-2', 'af-south-1', 'ap-east-1', 'ap-south-2', 'ap-southeast-3', 'ap-southeast-4',
                   'ap-south-1', 'ap-northeast-3', 'ap-northeast-2', 'ap-southeast-1', 'ap-southeast-2', 'ap-northeast-1', 'ca-central-1',
                   'eu-central-1', 'eu-west-1', 'eu-west-2', 'eu-south-1', 'eu-west-3', 'eu-south-2', 'eu-north-1', 'eu-central-2', 'il-central-1',
                   'me-south-1', 'me-central-1', 'sa-east-1'}

    @classmethod
    def get_redirect_ms(cls, time: int, start: bool = True, offset: int = 60000) -> int:  # ms offset for cluster/instance redirects
        """Calculates the millisecond offset for cluster and instance redirections."""
        if time is None:  # active clusters => current time as end time for redirects
            return int(datetime.now().strftime('%s')) * 1000
        if time <= 0:
            return time
        if start:  # offset start point to the left, bootstrapping phase isn't scraped so smaller offset than cluster end
            return time - offset
        return time + offset  # offset end to the right for redirects


class Ec2Instance:
    """Represents an EC2 instance, used for cost calculations."""
    def __init__(self, creation_ts, termination_ts, instance_type, market_type, ebs_volumes):
        self.creation_ts = creation_ts  # EMR instance group param, correlates to EC2 instance startup time
        self.termination_ts = termination_ts
        self.instance_type = instance_type
        self.market_type = market_type
        self.ebs_volumes = ebs_volumes


class InstanceResGroup:
    """Represents an individual EMR instance group or fleet, used for cost calculations."""
    def __init__(self, group_id: str, instance_type: str, group_type: str, ebs_block_devices: List[Dict] = []):
        self.group_id = group_id
        self.instance_type = instance_type
        self.group_type = group_type
        self.ebs_block_devices = ebs_block_devices


"""
    Boto3 domain objects for EMR.
    See https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/emr.html#EMR.Client.describe_cluster
"""


class ClusterTimeline(BaseModel):
    CreationDateTime: datetime
    EndDateTime: Optional[datetime]


class ClusterStatus(BaseModel):
    State: str
    Timeline: ClusterTimeline


class ListedCluster(BaseModel):
    """Domain object for list_clusters AWS API calls."""
    Id: str
    Name: str
    Status: ClusterStatus
    NormalizedInstanceHours: int

    @classmethod
    def create_listed_cluster(cls, api_resp: Dict) -> Self:
        """Creates a domain object from a list_clusters response."""
        if 'EndDateTime' not in api_resp['Status']['Timeline']:  # Active clusters
            api_resp['Status']['Timeline']['EndDateTime'] = None
        return ListedCluster(**api_resp)


class DescribedEmrCluster(ListedCluster):
    """Domain object for describe_cluster AWS API calls."""
    ReleaseLabel: str
    Tags: List[Dict]

    def _flatten_tags(self) -> List[List[str]]:
        """Flatten cluster tags for display in dashboard table."""
        pairs: List[List[str]] = []
        for tag in self.Tags:
            pairs.append([tag['Key'], tag['Value']])
        return pairs

    def get_runtime(self) -> timedelta:
        """Return cluster runtime. Current time will be used as end time for active clusters."""
        creation: datetime = self.Status.Timeline.CreationDateTime.replace(microsecond=0)
        end: datetime = datetime.now()
        if self.Status.Timeline.EndDateTime is not None:
            end = self.Status.Timeline.EndDateTime.replace(microsecond=0)
        return end - creation

    def get_start_end(self) -> Tuple[datetime, int, Optional[datetime], int]:
        """Return cluster start/end/redirection times."""
        creation: datetime = self.Status.Timeline.CreationDateTime
        creation_ms: int = DescribedEmrCluster.get_redirect_ms(creation)  # for redirects
        termination: Optional[datetime] = self.Status.Timeline.EndDateTime
        termination_ms: int = DescribedEmrCluster.get_redirect_ms(termination, False)  # for redirects
        return creation, creation_ms, termination, termination_ms

    def get_core_elems(self) -> List:
        """Return core cluster metadata for cluster list panel."""
        (creation, creation_ms, term, term_ms) = self.get_start_end()
        return [self.Name, self.Id, self.Status.State, creation, term, creation_ms, term_ms, self.NormalizedInstanceHours, self._flatten_tags()]

    @classmethod
    def get_redirect_ms(cls, date_time: Optional[datetime], start: bool = True) -> int:
        """Calculates millisecond offset for cluster redirection columns."""
        if date_time is None:  # active clusters => current time as end time for redirects
            return int(datetime.now().strftime('%s')) * 1000
        if start:  # offset start point to the left, bootstrapping phase not scraped so smaller offset than cluster end
            return (int(date_time.strftime('%s')) * 1000) - 1 * 60000
        return (int(date_time.strftime('%s')) * 1000) + 4 * 60000  # offset end to the right for redirects

    @classmethod
    def create_dummy(cls, cluster_id: str, creation: datetime, termination: datetime):
        """Return a synthetic domain object to augment later, used for stuffing API gaps."""
        dummy_cluster = {'Id': cluster_id, 'Name': 'NA', 'Status': {}}
        dummy_cluster['Status']['State'] = 'TERMINATED'
        dummy_cluster['Status']['Timeline'] = {}
        dummy_cluster['Status']['Timeline']['CreationDateTime'] = creation
        dummy_cluster['Status']['Timeline']['EndDateTime'] = termination
        dummy_cluster['NormalizedInstanceHours'] = 0
        dummy_cluster['ReleaseLabel'] = ''
        dummy_cluster['Tags'] = []
        return DescribedEmrCluster(**dummy_cluster)


class EmrCluster(BaseModel):
    """Top level class for EMR domain objects."""
    Cluster: DescribedEmrCluster


"""
    Domain objects for Databricks.
    See https://docs.databricks.com/api/workspace/clusters/get
"""


class DbxCluster:
    """Utility class for creating table responses for different Grafana panels."""
    def __init__(self, fields: Tuple[str, str, str, int, int, int, int, str, str, str]):
        self.Id = fields[0]  # compatibility with EMR equivalents, common field
        self.name = fields[1]
        self.state = fields[2]
        self.start = fields[3]
        self.start_redir = fields[4]
        self.end = fields[5]
        self.end_redir = fields[6]
        self.source = fields[7]
        self.is_jobs = fields[8]
        self.is_notebooks = fields[9]

    def get_core_elems(self) -> List:
        """Return core metadata for cluster list panel."""
        return [self.name, self.Id, self.state, self.start, self.end, self.start_redir, self.end_redir, self.source]

    @classmethod
    def extract_core_details(cls, detail: ClusterDetails) -> Self:
        """Create a domain object from response of list cluster Dbx API call."""
        cluster_id = 'NA' if detail.cluster_id is None else detail.cluster_id
        name = 'NA' if detail.cluster_name is None else detail.cluster_name
        state = 'NA' if detail.state is None else detail.state.value
        start = detail.start_time
        start_redir = AllClusters.get_redirect_ms(start)
        end = detail.terminated_time
        end_redir = AllClusters.get_redirect_ms(end, False, offset=240000)
        source = 'NA' if detail.cluster_source is None else detail.cluster_source.value
        clients_type: Optional['ClientsTypes'] = None if detail.workload_type is None or detail.workload_type.clients is None else detail.workload_type.clients
        is_jobs = 'NA' if clients_type is None or clients_type.jobs is None else str(clients_type.jobs)
        is_notebooks = 'NA' if clients_type is None or clients_type.notebooks is None else str(clients_type.notebooks)
        return DbxCluster((cluster_id, name, state, start, start_redir, end, end_redir, source, is_jobs, is_notebooks))

    @classmethod
    def create_dummy(cls, cluster_id: str, first: int, last: int) -> Self:
        """Return a synthetic domain object to augment later, used for stuffing API gaps."""
        start_redir = AllClusters.get_redirect_ms(first)
        end_redir = AllClusters.get_redirect_ms(last, False, offset=240000)
        return DbxCluster((cluster_id, '', 'TERMINATED', first, start_redir, last, end_redir, 'NA', 'NA', 'NA'))


"""Type aliases."""
ClusterCache = Dict[str, DescribedEmrCluster]
