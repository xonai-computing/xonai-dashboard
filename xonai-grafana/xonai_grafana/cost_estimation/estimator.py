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

"""Module containing cost estimation functionality."""
import datetime
import json
import gzip
from enum import Enum
from os import path
from typing import Tuple, Dict, List, Iterator, Self
from botocore.client import BaseClient
from retrying import retry
from xonai_grafana.schemata.cloud_objects import InstanceResGroup, Ec2Instance
from xonai_grafana.utils.logging import LoggerUtils

logger = LoggerUtils.create_logger('estimator')
resource_path = path.join(path.dirname(path.abspath(__file__)), 'resources')

"""Type aliases."""
InstanceInfo = Dict[str, Dict[str, str]]
SpotPriceHistory = Dict[datetime, float]
CostMap = Dict[str, float]
CostCache = Dict[str, CostMap]


def is_error_retrieable(exception) -> bool:
    """Used for :func:`get_cluster_cost`, called when AWS API issues like throttling occur."""
    try:
        return exception.response['Error']['Code'].startswith("5")
    except AttributeError:
        return False


class DbxClusterType(Enum):
    """Constants for Databricks runtimes, relevant for cost estimations."""
    JOB_BASIC = 1
    JOB_PHOTON = 2
    JOB_LIGHT = 3
    ALL_PURPOSE_BASIC = 4
    ALL_PURPOSE_PHOTON = 5

    def __str__(self) -> str:
        if self.value == 1:
            return "Jobs Compute"
        if self.value == 2:
            return "Jobs Compute Photon"
        if self.value == 3:
            return "Jobs Light Compute"
        if self.value == 4:
            return "All-Purpose Compute"
        return "All-Purpose Compute Photon"

    @classmethod
    def determine_cluster_type(cls, is_job: str, spark_version: str) -> Self:
        """Determine Databricks cluster type, important for cost estimations."""
        is_job_norm = is_job.strip().lower()
        if is_job_norm == 'true':
            if 'photon' in spark_version:
                return DbxClusterType.JOB_PHOTON
            if 'light' in spark_version:
                return DbxClusterType.JOB_LIGHT
            return DbxClusterType.JOB_BASIC
        if is_job_norm == 'false':
            if 'photon' in spark_version:
                return DbxClusterType.ALL_PURPOSE_PHOTON
            return DbxClusterType.ALL_PURPOSE_BASIC
        raise ValueError(f'Unsupported Dbx runtime {is_job} {spark_version}')

    @classmethod
    def parse_cluster_type(cls, string: str) -> Self:
        """Parse resource file strings and return a Dbx cluster type."""
        normalized = string.strip().lower()
        if normalized == 'jobs compute':
            return DbxClusterType.JOB_BASIC
        if normalized == 'jobs compute photon':
            return DbxClusterType.JOB_PHOTON
        if normalized == 'jobs light compute':
            return DbxClusterType.JOB_LIGHT
        if normalized == 'all-purpose compute':
            return DbxClusterType.ALL_PURPOSE_BASIC
        if normalized == 'all-purpose compute photon':
            return DbxClusterType.ALL_PURPOSE_PHOTON
        else:
            raise ValueError(f'Unsupported Dbx cluster type {string}')


class EstimationUtils:
    """Class for general cost estimation functionality."""
    @classmethod
    def get_normalized_cost(cls, seconds_passed: int, hourly_price: float) -> float:
        """Calculate costs based on hourly prices."""
        return float(seconds_passed) * hourly_price / 3600.0


class DbxPricing:
    """Class for Databricks cost estimations, parses and holds EC2 and DBU cost info located under resources/."""
    def __init__(self, region: str, res_path: str = resource_path):
        self.region = region
        # EC2 prices:
        ec2_pricing = {'products': {}}
        ec2_file = path.join(res_path, 'ec2', region + '.json.gz')
        if path.exists(ec2_file):
            with gzip.open(ec2_file, mode="rt") as f:
                region_content = f.read()
                ec2_pricing = json.loads(region_content)
        else:
            logger.warning('EC2 file for region %s at %s missing, please install it with the setup script', region, ec2_file)
        ec2_sku_to_instance_type = {}
        self.instance_type_info: InstanceInfo = {}
        for sku in ec2_pricing['products']:
            try:
                attr = ec2_pricing['products'][sku]['attributes']
                if attr['tenancy'] == 'Shared' and attr['operatingSystem'] == 'Linux' and attr['operation'] == 'RunInstances' \
                        and attr['capacitystatus'] == 'Used':
                    ec2_sku_to_instance_type[sku] = attr['instanceType']
                    if 'instanceType' in attr:
                        self.instance_type_info[attr['instanceType']] = attr
            except KeyError:
                pass
        self.ec2_prices: CostMap = {}
        for sku, instance_type in ec2_sku_to_instance_type.items():
            sku_info = ec2_pricing['terms']['OnDemand'][sku]
            if len(sku_info) > 1:
                logger.warning('More than one SKU for %s in %s', sku_info, ec2_file)
                continue
            _, sku_info_value = sku_info.popitem()
            price_dimensions = sku_info_value['priceDimensions']
            if len(sku_info) > 1:
                logger.warning('More than price dimension for %s in %s', price_dimensions, ec2_file)
                continue
            _, price_dimensions_value = price_dimensions.popitem()
            price = float(price_dimensions_value['pricePerUnit']['USD'])
            if self.available_ec2_price(instance_type):
                logger.warning('Instance type info for %s already added', instance_type)
                continue
            self.ec2_prices[instance_type] = price
        # DBU info:
        cost_per_dbu: Dict[Tuple[DbxClusterType, str], float] = {}
        with gzip.open(path.join(resource_path, 'dbx', 'cost_per_dbu_aws.tsv.gz', ), mode="rt") as f:
            for line in f:
                fields = line.split('\t')  # Jobs Compute	Standard	0.1
                cluster_type: DbxClusterType = DbxClusterType.parse_cluster_type(fields[0])
                plan = fields[1].lower()
                official_dbu_cost = float(fields[2])
                if (cluster_type, plan) in cost_per_dbu:
                    raise ValueError(f'Duplicate DBU info for {cluster_type} and {plan}')
                cost_per_dbu[(cluster_type, plan)] = official_dbu_cost
        self.dbu_info: Dict[str, Dict[Tuple[DbxClusterType, str], Tuple[float, float]]] = {}
        with gzip.open(path.join(resource_path, 'dbx', 'dbu_info.tsv.gz', ), mode="rt") as f:
            for line in f:
                fields = line.split('\t')  # c3.2xlarge	Jobs Compute	premium	1.000
                instance_type = fields[0]
                runtime_cluster_type = fields[1]
                cluster_type: DbxClusterType = DbxClusterType.parse_cluster_type(runtime_cluster_type)
                plan = fields[2]
                dbus: float = float(fields[3])
                dbu_cost: float = cost_per_dbu[(cluster_type, plan)] * dbus
                if instance_type in self.dbu_info:
                    instance_info = self.dbu_info[instance_type]
                    if (cluster_type, plan) in instance_info:
                        logger.warning('Duplicate DBU info: %s', line)
                        continue
                    instance_info[(cluster_type, plan)] = (dbus, dbu_cost)
                else:
                    instance_info = {(cluster_type, plan): (dbus, dbu_cost)}
                    self.dbu_info[instance_type] = instance_info

    def available_ec2_price(self, instance_type) -> bool:
        """Check whether EC2 costs are available for instance type."""
        return instance_type in self.ec2_prices

    def available_dbu_price(self, instance_type: str, cluster_type: DbxClusterType, plan: str) -> bool:
        """Check whether DBU costs are available for instance type."""
        return instance_type in self.dbu_info and (cluster_type, plan) in self.dbu_info[instance_type]

    def get_ec2_price(self, instance_type) -> float:
        """Return EC2 list price for the instance."""
        if self.available_ec2_price(instance_type):
            return self.ec2_prices[instance_type]
        logger.warning('No EC2 price present for %s in %s', instance_type, self.region)
        return 0

    def get_dbu_info(self, instance_type: str, cluster_type: DbxClusterType, plan: str) -> Tuple[float, float]:
        """Return DBU info for the instance."""
        if self.available_dbu_price(instance_type, cluster_type, plan):
            return self.dbu_info[instance_type][(cluster_type, plan)]
        logger.warning('No DBU info present for %s on %s/%s', instance_type, cluster_type, plan)
        return 0, 0

    def calculate_ec2_cost(self, instance_type: str, runtime_sec: int) -> float:
        """Calculate EC2 costs for instance type."""
        ec2_price = self.get_ec2_price(instance_type)
        return ec2_price * (runtime_sec / 3600)

    def calculate_dbus_costs(self, instance_type: str, runtime_sec: int, cluster_type: DbxClusterType, plan: str) -> Tuple[float, float]:
        """Calculate DBUs and DBU costs for instance type."""
        (dbus, dbu_cost) = self.dbu_info[instance_type][(cluster_type, plan)]
        return dbus * (runtime_sec / 3600), dbu_cost * (runtime_sec / 3600)

    def get_instance_info(self, instance_type: str) -> Dict[str, str]:
        """Return hardware specs for the instance."""
        if instance_type in self.instance_type_info:
            return self.instance_type_info[instance_type]
        return {}


class Ec2EmrPricing:
    """
        Helper class that parses and holds EC2 and EMR cost info located under resources/.
        Needs to be recreated whenever the AWS region changes.
        See tests/utilities.py for file schemata.
    """
    def __init__(self, region: str, res_path: str):
        self.region = region
        # Populate EMR prices:
        emr_file = path.join(res_path, 'emr', region + '.json.gz')
        emr_pricing = {'products': {}}
        if path.exists(emr_file):
            with gzip.open(emr_file, mode="rt") as f:
                region_content = f.read()
                emr_pricing = json.loads(region_content)
        else:
            logger.warning('EMR file for region %s at %s missing, please install it with the setup script', region, emr_file)
        sku_map_emr = {}  # sku to instance type mappings
        for sku in emr_pricing['products']:
            if (('softwareType' in emr_pricing['products'][sku]['attributes'].keys()) and
                    (emr_pricing['products'][sku]['attributes']['softwareType'] == 'EMR')):
                sku_map_emr[sku] = emr_pricing['products'][sku]['attributes']['instanceType']
        self.emr_prices: CostMap = {}
        for sku, instance_type in sku_map_emr.items():
            sku_info = emr_pricing['terms']['OnDemand'][sku]
            if len(sku_info) > 1:
                logger.warning('More than one SKU for %s in %s', sku_info, emr_file)
                continue
            _, sku_info_value = sku_info.popitem()
            price_dimensions = sku_info_value['priceDimensions']
            if len(sku_info) > 1:
                logger.warning('More than one price dimension for %s in %s', price_dimensions, emr_file)
                continue
            _, price_dimensions_value = price_dimensions.popitem()
            price = float(price_dimensions_value['pricePerUnit']['USD'])
            self.emr_prices[instance_type] = price
        # Populate EC2 prices:
        ec2_pricing = {'products': {}}
        ec2_file = path.join(res_path, 'ec2', region + '.json.gz')
        if path.exists(ec2_file):
            with gzip.open(ec2_file, mode="rt") as f:
                region_content = f.read()
                ec2_pricing = json.loads(region_content)
        else:
            logger.warning('EC2 file for region %s at %s missing, please install it with the setup script', region, ec2_file)
        self.instance_type_info: InstanceInfo = {}  # for instance info panel
        sku_map_ec2 = {}  # sku to instance type mappings
        for sku in ec2_pricing['products']:
            try:
                attr = ec2_pricing['products'][sku]['attributes']
                if attr['tenancy'] == 'Shared' and attr['operatingSystem'] == 'Linux' and attr['operation'] == 'RunInstances' \
                        and attr['capacitystatus'] == 'Used':
                    sku_map_ec2[sku] = attr['instanceType']
                    if 'instanceType' in attr:
                        self.instance_type_info[attr['instanceType']] = attr
            except KeyError:
                pass
        self.ec2_prices: CostMap = {}
        for sku, instance_type in sku_map_ec2.items():
            sku_info = ec2_pricing['terms']['OnDemand'][sku]
            if len(sku_info) > 1:
                logger.warning('More than one SKU present in %s for %s', ec2_file, sku_info)
                continue
            _, sku_info_value = sku_info.popitem()
            price_dimensions = sku_info_value['priceDimensions']
            if len(sku_info) > 1:
                logger.warning('More than one price dimension present in %s for %s', ec2_file, price_dimensions)
                continue
            _, price_dimensions_value = price_dimensions.popitem()
            price = float(price_dimensions_value['pricePerUnit']['USD'])
            if self.available_ec2_price(instance_type):
                logger.warning('Instance price for %s from %s already added', instance_type, ec2_file)
                continue
            self.ec2_prices[instance_type] = price

    def available_ec2_price(self, instance_type) -> bool:
        """Check whether EC2 list price is available for the instance."""
        return instance_type in self.ec2_prices

    def get_emr_price(self, instance_type) -> float:
        """Return EMR list price for the instance."""
        if instance_type in self.emr_prices:
            return self.emr_prices[instance_type]
        logger.warning('No EMR price present for %s in %s', instance_type, self.region)
        return 0

    def get_ec2_price(self, instance_type) -> float:
        """Return EC2 list price for the instance."""
        if self.available_ec2_price(instance_type):
            return self.ec2_prices[instance_type]
        logger.warning('No EC2 price present for %s in %s', instance_type, self.region)
        return 0

    def get_listprice_direct(self, instance_type: str, runtime_sec: int) -> float:
        """Calculate EC2 costs for the instance."""
        ec2_price = self.get_ec2_price(instance_type)
        return ec2_price * (runtime_sec / 3600)

    def get_instance_info(self, instance_type: str) -> Dict[str, str]:
        """Return hardware specs for the instance."""
        if instance_type in self.instance_type_info:
            return self.instance_type_info[instance_type]
        return {}


class EmrCostEstimator:
    """
        Class for estimating EMR on-demand and spot costs in instance fleets and groups.
        Holds an EMR client for calling ListInstanceGroups, ListInstanceFleets, ListInstances, and DescribeCluster.
        Holds a :class:`SpotPricing` object with an EC2 client for calling ec2:DescribeSpotPriceHistory.
        Inspired by https://github.com/memosstilvi/emr-cost-calculator.
    """
    def __init__(self, emr_client: BaseClient, ec2_client: BaseClient, region: str, res_path: str = resource_path):
        self.emr_client = emr_client
        try:
            self.spot_pricing = SpotPricing(ec2_client)
        except Exception as e:
            logger.warning('Could not connect to AWS EC2 API:', exc_info=e)
        self.ec2_emr_pricing = Ec2EmrPricing(region, res_path)

    def _get_ec2_cost(self, instance: Ec2Instance, avail_zone) -> float:
        """Return the on demand or spot estimation for the instance in given availability zone"""
        try:
            if instance.market_type == "SPOT":
                return self.spot_pricing.estimate_price_for_period(instance.instance_type, avail_zone, instance.creation_ts, instance.termination_ts)
            ec2_price = self.ec2_emr_pricing.get_ec2_price(instance.instance_type)
            return ec2_price * ((instance.termination_ts - instance.creation_ts).total_seconds() / 3600)
        except Exception as e:
            logger.warning('Problems with estimating costs for %s %s', instance.market_type, instance.instance_type, exc_info=e)
            return 0.0

    @classmethod
    def _estimate_root_volume_cost(cls, hours_run: float) -> float:
        """
            Estimates the root volume cost with several simplifying assumptions: By default, 15 GiB SSD (gp2) are attached to each cluster
            instance. 0.1$ per GB-month is used as the price which is multiplied by 0.931323 to get GiB-month. A month equals 720 hours in
            the calculation below.
        """
        return 15 * 0.1 * 0.931323 * hours_run / 720

    @classmethod
    def _estimate_ebs_storage_cost(cls, hours_run: float, vol_type: str, vol_size: int) -> float:
        """
            Estimates the storage cost with several simplifying assumptions: The us-east-1 prices from https://aws.amazon.com/ebs/pricing/
            are used which are multiplied by 0.931323 to get GiB-month. A month equals 720 hours in the calculation below.
        """
        if vol_type == 'gp2':
            vol_price = 0.1
        elif vol_type == 'gp3':
            vol_price = 0.08
        elif vol_type == 'io1' or vol_type == 'io2':
            vol_price = 0.125
        elif vol_type == 'standard':  # https://aws.amazon.com/ebs/previous-generation/, "magnetic" entry
            vol_price = 0.05
        elif vol_type == 'st1':
            vol_price = 0.045
        elif vol_type == 'sc1':
            vol_price = 0.015
        else:
            logger.warning('Volume type %s unknown', vol_type)
            return 0.0
        return vol_size * vol_price * 0.931323 * hours_run / 720

    @classmethod
    def _estimate_ebs_costs(cls, block_devices: List[Dict], hours_run: float) -> float:
        """Estimates an instance's EBS costs."""
        ebs_costs = EmrCostEstimator._estimate_root_volume_cost(hours_run)
        for block_device in block_devices:
            try:
                block_size = block_device['VolumeSpecification']['SizeInGB']
                volume_type = block_device['VolumeSpecification']['VolumeType']
                ebs_costs += EmrCostEstimator._estimate_ebs_storage_cost(hours_run, volume_type, block_size)
            except Exception as e:
                logger.warning('Problem while processing block device %s', block_device, exc_info=e)
                continue
        return ebs_costs

    def _get_instance_groups(self, cluster_id: str) -> List[InstanceResGroup]:
        """Fetch the cluster's instance groups via calls to elasticmapreduce:ListInstanceGroup."""
        groups = self.emr_client.list_instance_groups(ClusterId=cluster_id)['InstanceGroups']
        instance_groups: List[InstanceResGroup] = []
        for group in groups:
            inst_group = InstanceResGroup(group['Id'], group['InstanceType'], group['InstanceGroupType'], self._get_ebs_block_devices(group))
            instance_groups.append(inst_group)
        return instance_groups

    def _get_instance_fleets(self, cluster_id: str) -> List[InstanceResGroup]:
        """Fetch the cluster's instance fleets via calls to elasticmapreduce:ListInstanceFleets."""
        fleets = self.emr_client.list_instance_fleets(ClusterId=cluster_id)['InstanceFleets']
        instance_fleets: List[InstanceResGroup] = []
        for fleet in fleets:
            inst_fleet = InstanceResGroup(fleet['Id'], fleet['InstanceTypeSpecifications'][0]['InstanceType'], fleet['InstanceFleetType'],
                                          self._get_ebs_block_devices(fleet['InstanceTypeSpecifications'][0]))
            instance_fleets.append(inst_fleet)
        return instance_fleets

    def _get_instances(self, instance_group: InstanceResGroup, cluster_id: str, fleet=False) -> Iterator[Ec2Instance]:
        """Fetch and merges the cluster's instances via calls to elasticmapreduce:ListInstances."""
        instance_list = []
        list_instances_args = {'ClusterId': cluster_id, 'InstanceGroupId': instance_group.group_id}
        if fleet:
            list_instances_args = {'ClusterId': cluster_id, 'InstanceFleetId': instance_group.group_id}
        while True:
            batch = self.emr_client.list_instances(**list_instances_args)
            instance_list.extend(batch['Instances'])
            try:
                list_instances_args['Marker'] = batch['Marker']
            except KeyError:
                break
        for instance_info in instance_list:
            try:
                creation_time = instance_info['Status']['Timeline']['CreationDateTime']
                try:
                    end_date_time = instance_info['Status']['Timeline']['EndDateTime']
                except KeyError:
                    end_date_time = datetime.datetime.now(tz=creation_time.tzinfo)  # use same TZ as creation time, datetime.now() not tz-aware
                inst = Ec2Instance(instance_info['Status']['Timeline']['CreationDateTime'], end_date_time, instance_info['InstanceType'],
                                   instance_info['Market'], instance_info['EbsVolumes'])
                yield inst
            except AttributeError as e:
                logger.warning('Issue while computing instance cost for cluster %s', cluster_id, exc_info=e)

    @classmethod
    def _get_ebs_block_devices(cls, spec_map) -> List[Dict]:
        """Return EBS storage."""
        ebs_block_devices = []
        if 'EbsBlockDevices' in spec_map:
            ebs_block_devices = spec_map['EbsBlockDevices']
        return ebs_block_devices

    def _get_avail_zone(self, cluster_id) -> str:
        """Return availability zone of the cluster."""
        cluster_description = self.emr_client.describe_cluster(ClusterId=cluster_id)
        return cluster_description['Cluster']['Ec2InstanceAttributes']['Ec2AvailabilityZone']

    @retry(wait_exponential_multiplier=1000, wait_exponential_max=10000, retry_on_exception=is_error_retrieable)
    def estimate_cluster_cost(self, cluster_id) -> CostMap:
        """Merges cost info of different components / instance groups to get total costs."""
        cost_dict: CostMap = {}
        avail_zone = self._get_avail_zone(cluster_id)
        try:
            instance_groups: List[InstanceResGroup] = self._get_instance_groups(cluster_id)
            for instance_group in instance_groups:
                for instance in self._get_instances(instance_group, cluster_id):
                    ec2_cost: float = self._get_ec2_cost(instance, avail_zone)
                    if ec2_cost is None:
                        ec2_cost = 0
                    group_type = instance_group.group_type
                    cost_dict.setdefault(group_type + '.EC2', 0)
                    cost_dict[group_type + '.EC2'] += ec2_cost
                    cost_dict.setdefault(group_type + '.EMR', 0)
                    hours_run = (instance.termination_ts - instance.creation_ts).total_seconds() / 3600
                    emr_cost = self.ec2_emr_pricing.get_emr_price(instance.instance_type) * hours_run
                    cost_dict[group_type + '.EMR'] += emr_cost
                    cost_dict.setdefault(group_type + '.EBS', 0)
                    ebs_cost = self._estimate_ebs_costs(instance_group.ebs_block_devices, hours_run)
                    cost_dict[group_type + '.EBS'] += ebs_cost
                    cost_dict.setdefault('TOTAL', 0)
                    cost_dict['TOTAL'] += ec2_cost + emr_cost + ebs_cost
        except Exception:  # ListInstanceGroups op does not support clusters that use instance fleets => use ListInstanceFleets op
            instance_fleets: List[InstanceResGroup] = self._get_instance_fleets(cluster_id)
            for instance_fleet in instance_fleets:
                for instance in self._get_instances(instance_fleet, cluster_id, True):
                    ec2_cost: float = self._get_ec2_cost(instance, avail_zone)
                    if ec2_cost is None:
                        ec2_cost = 0
                    group_type = instance_fleet.group_type
                    cost_dict.setdefault(group_type + '.EC2', 0)
                    cost_dict[group_type + '.EC2'] += ec2_cost
                    cost_dict.setdefault(group_type + '.EMR', 0)
                    hours_run = (instance.termination_ts - instance.creation_ts).total_seconds() / 3600
                    emr_cost = self.ec2_emr_pricing.get_emr_price(instance.instance_type) * hours_run
                    cost_dict[group_type + '.EMR'] += emr_cost
                    cost_dict.setdefault(group_type + '.EBS', 0)
                    ebs_cost = self._estimate_ebs_costs(instance_fleet.ebs_block_devices, hours_run)
                    cost_dict[group_type + '.EBS'] += ebs_cost
                    cost_dict.setdefault('TOTAL', 0)
                    cost_dict['TOTAL'] += ec2_cost + emr_cost + ebs_cost
        return cost_dict

    def close_clients(self):
        """Close embedded clients."""
        self.emr_client.close()
        self.spot_pricing.ec2_client.close()


class SpotPricing:
    """
        Holds and returns spot price histories for particular instances, fetched via calls
        to ec2:DescribeSpotPriceHistory.
        Inspired by https://github.com/memosstilvi/emr-cost-calculator.
    """
    def __init__(self, ec2_client: BaseClient):
        self.ec2_client = ec2_client
        self.spot_prices: Dict[Tuple[str, str], SpotPriceHistory] = {}  # instance type/avail_zone as keys

    def _populate_missing_prices(self, inst_type: str, avail_zone: str, start_time: datetime, end_time: datetime) -> None:
        """
            Fetches spot prices per instance type and availability zone for given interval via EC2 API calls
            and populates internal history map.
        """
        if (inst_type, avail_zone) in self.spot_prices:
            prices = self.spot_prices[(inst_type, avail_zone)]
            sorted_keys = sorted(prices.keys())
            if end_time - sorted_keys[-1] < datetime.timedelta(days=1, hours=1) and sorted_keys[0] < start_time:
                return  # end time at most 25 hours after last entry and start time after first entry => relevant dates already present
        else:
            prices: SpotPriceHistory = {}
        previous_ts = None
        next_token = ""
        while True:
            # see https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2/client/describe_spot_price_history.html
            prices_response = self.ec2_client.describe_spot_price_history(
                InstanceTypes=[inst_type],
                ProductDescriptions=['Linux/UNIX (Amazon VPC)'],  # AWS API (sometimes?) normalizes to `Linux/UNIX`
                AvailabilityZone=avail_zone,
                StartTime=start_time,
                EndTime=end_time,
                NextToken=next_token
            )
            for price in prices_response['SpotPriceHistory']:
                if previous_ts is None:
                    previous_ts = price['Timestamp']
                if previous_ts - price['Timestamp'] > datetime.timedelta(days=1, hours=1):
                    logger.warning("Expect max of one day one hour diff between price entries, not %s minus %s", previous_ts, price['Timestamp'])
                prices[price['Timestamp']] = float(price['SpotPrice'])
                previous_ts = price['Timestamp']
            next_token = prices_response['NextToken']
            if next_token == "":
                break
        self.spot_prices[(inst_type, avail_zone)] = prices

    def estimate_price_for_period(self, inst_type: str, avail_zone: str, start_time: datetime, end_time: datetime) -> float:
        """Derive spot estimation by traversing through history and summing up interval costs."""
        self._populate_missing_prices(inst_type, avail_zone, start_time, end_time)
        prices: SpotPriceHistory = self.spot_prices[(inst_type, avail_zone)]
        if len(prices) < 1:
            return 0.0
        if len(prices) == 1:  # API returned just one price point
            relevant_price = next(iter(prices.values()))
            seconds_passed = (end_time - start_time).total_seconds()
            return EstimationUtils.get_normalized_cost(seconds_passed, relevant_price)
        summed_price = 0.0
        sorted_price_timestamps = sorted(prices.keys())
        summed_until_timestamp = start_time
        for key_id, price_timestamp in enumerate(sorted_price_timestamps):
            next_id = key_id + 1
            if next_id < len(sorted_price_timestamps) and price_timestamp < start_time <= sorted_price_timestamps[next_id]:  # active price right before instance start
                if end_time <= sorted_price_timestamps[next_id]:  # start and end times within one spot price interval
                    seconds_passed = (end_time - start_time).total_seconds()
                    return EstimationUtils.get_normalized_cost(seconds_passed, prices[price_timestamp])
                seconds_passed = (sorted_price_timestamps[next_id] - start_time).total_seconds()
                summed_price += EstimationUtils.get_normalized_cost(seconds_passed, prices[price_timestamp])
                summed_until_timestamp = sorted_price_timestamps[next_id]
            elif price_timestamp > start_time:  # intermediate segment
                seconds_passed = (price_timestamp - summed_until_timestamp).total_seconds()
                summed_price += EstimationUtils.get_normalized_cost(seconds_passed, prices[sorted_price_timestamps[key_id - 1]])
                summed_until_timestamp = price_timestamp
            if key_id == len(sorted_price_timestamps) - 1 or end_time < sorted_price_timestamps[next_id]:  # last or last relevant price point
                seconds_passed = (end_time - summed_until_timestamp).total_seconds()
                summed_price += EstimationUtils.get_normalized_cost(seconds_passed, prices[sorted_price_timestamps[key_id]])
                return summed_price
        logger.warning("Spot estimation incomplete for %s in %s at %s/%s", inst_type, avail_zone, start_time, end_time)
        return summed_price  # only reached if something unexpected happened
