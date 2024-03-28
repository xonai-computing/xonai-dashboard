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

"""Module containing functionality related to cloud entities."""
from datetime import datetime
from dateutil.parser import parse
from typing import Dict, List, Iterator, Tuple, Optional, Set
from databricks.sdk.service.compute import ClusterDetails, State
from xonai_grafana.cost_estimation.estimator import DbxClusterType, CostMap
from xonai_grafana.schemata.cloud_objects import ListedCluster, DescribedEmrCluster, EmrCluster, DbxCluster, SupportedPlatforms
from xonai_grafana.utils.dependencies import Inject
from xonai_grafana.utils.logging import LoggerUtils
from xonai_grafana.utils.tsdb import TsdbUtils, TsdbQuery, IdPair

logger = LoggerUtils.create_logger('cloud utils')


class ClusterUtils:
    """Class for general functionality relating to cloud platforms."""
    @classmethod
    def get_variable_values(cls, cluster_var: str) -> Set[str]:
        """Breaks up a multi-value Grafana variable."""
        if '|' in cluster_var:  # e.g., multiple cluster IDs selected in Grafana variable
            return set(cluster_var[1:-1].split('|'))
        return {cluster_var}

    @classmethod
    def add_costs(cls, cluster_costs: List[CostMap]) -> CostMap:
        """Helper function to add up costs of multiple clusters."""
        total_costs: CostMap = {}
        for cluster_cost in cluster_costs:
            for key, value in cluster_cost.items():
                if key not in total_costs:  # should not happen
                    total_costs[key] = value
                else:
                    total_costs[key] += value
        return total_costs

    @classmethod
    def get_total_utilization(cls, cluster_ids: Set[str], start: int, end: int, inj: Inject) -> Tuple[float, int]:
        """Determines total utilization of tracked clusters of known apps. Used for compute utilization panel."""
        cpu_utils = 0.0
        considered_clusters = 0
        for relevant_id in cluster_ids:
            if inj.platform is SupportedPlatforms.AWS_EMR:
                cluster_desc: DescribedEmrCluster = EmrUtils.check_cluster_cache(relevant_id, inj)
                (cpu_util, _) = inj.tsdb_client.get_cluster_utilizations(cluster_desc)
                if cpu_util[1] is not None:
                    cpu_utils += cpu_util[1]
                    considered_clusters += 1
            elif inj.platform is SupportedPlatforms.AWS_DBX:
                cluster_first, cluster_last = inj.tsdb_client._get_cluster_times(relevant_id, start, end, SupportedPlatforms.AWS_DBX)
                dummy_cluster: DbxCluster = DbxCluster.create_dummy(relevant_id, cluster_first * 1000, cluster_last * 1000)
                (cpu_util, _) = inj.tsdb_client.get_cluster_utilizations(dummy_cluster)
                if cpu_util[1] is not None:
                    cpu_utils += cpu_util[1]
                    considered_clusters += 1
        total_util = cpu_utils / considered_clusters if considered_clusters > 0 else 0
        return total_util, considered_clusters

    @classmethod
    def get_active_resources(cls, inj: Inject, start: int) -> Tuple[int, int, int, int]:
        """Fetches # active nodes, # CPUs, total RAM, and total disk from the DB. Used for active resources panel."""
        active_ids: Set[str] = set()
        if inj.platform == SupportedPlatforms.AWS_EMR:
            active_ids = EmrUtils.get_active_cluster_ids(inj.client_emr)
        if inj.platform == SupportedPlatforms.AWS_DBX:
            active_ids = DbxUtils.get_active_cluster_ids(inj.client_dbx)
        concatenated_ids = '|'.join(active_ids)  # multi variable values in Grafana
        now = int(datetime.now().strftime('%s'))
        return inj.tsdb_client.get_resources(concatenated_ids, start, now)


class EmrUtils:
    """Utility class for EMR clusters, mostly contains class methods."""
    active_state_args = {'ClusterStates': ['RUNNING', 'WAITING']}

    @classmethod
    def _empty_costmap(cls) -> CostMap:
        return {'TOTAL': 0.0, 'CORE.EC2': 0.0, 'CORE.EMR': 0.0, 'MASTER.EC2': 0.0, 'MASTER.EMR': 0.0, 'MASTER.EBS': 0.0, 'CORE.EBS': 0.0}

    @staticmethod
    def _get_cluster_info(emr_client, kwargs) -> Iterator[ListedCluster]:
        """Retrieve listed cluster from AWS API and parse result as domain object. Used for active resources panel."""
        while True:
            cluster_list: Dict = emr_client.list_clusters(**kwargs)
            for cluster in cluster_list['Clusters']:
                try:
                    yield ListedCluster.create_listed_cluster(cluster)
                except Exception as e:
                    logger.warning('Problems when creating a ListedCluster object for %s', cluster, exc_info=e)
                    continue
            try:
                kwargs['Marker'] = cluster_list['Marker']
            except KeyError:
                break

    @classmethod
    def get_active_cluster_ids(cls, emr_client) -> Set[str]:
        """Return IDs of active EMR clusters. Used for active resources panel."""
        cluster_list: List[ListedCluster] = list(cls._get_cluster_info(emr_client, cls.active_state_args))
        cluster_ids = {cluster.Id for cluster in cluster_list}
        return cluster_ids

    @classmethod
    def get_clusters_costs(cls, cluster_ids: Set[str], inj: Inject) -> CostMap:
        """Helper function fetch costs for multiple clusters."""
        calculated_prices: List[CostMap] = []
        for cluster_id in cluster_ids:
            calculated_price: CostMap = cls.check_cost_cache(cluster_id, inj)
            calculated_prices.append(calculated_price)
        total_costs = ClusterUtils.add_costs(calculated_prices)
        return total_costs

    @classmethod
    def get_cluster_costs(cls, cluster_string: str, inj: Inject) -> CostMap:
        """Helper function to fetch costs for one or more clusters."""
        if '|' in cluster_string:  # multi-value variable like (j-XXF79ZLHQ699|j-XX555NKMAIQ99)'
            clusters_string: Set[str] = set(cluster_string[1:-1].split('|'))
            return cls.get_clusters_costs(clusters_string, inj)
        return cls.check_cost_cache(cluster_string, inj)

    @classmethod
    def get_cluster_ids(cls, emr_client, kwargs) -> Iterator[str]:
        """Return IDs of EMR clusters, used not for main but variables loop."""
        while True:
            cluster_list = emr_client.list_clusters(**kwargs)
            for cluster in cluster_list['Clusters']:
                yield cluster['Id']
            try:
                kwargs['Marker'] = cluster_list['Marker']
            except KeyError:
                break

    @classmethod
    def check_cluster_cache(cls, cluster_id: str, inj: Inject) -> DescribedEmrCluster:
        """
            Check internal cache for given cluster ID and return info. If absent, query AWS API and put
            the description into cache if cluster has terminated.
        """
        if cluster_id in inj.cluster_cache:
            return inj.cluster_cache[cluster_id]
        response_desc = inj.client_emr.describe_cluster(ClusterId=cluster_id)
        if 'EndDateTime' not in response_desc['Cluster']['Status']['Timeline']:  # Active clusters
            response_desc['Cluster']['Status']['Timeline']['EndDateTime'] = None
        cluster_desc: DescribedEmrCluster = EmrCluster(**response_desc).Cluster
        if 'TERMINATED' in cluster_desc.Status.State:  # TERMINATED'|'TERMINATED_WITH_ERRORS'
            inj.cluster_cache[cluster_id] = cluster_desc
        return cluster_desc

    @classmethod
    def check_cost_cache(cls, cluster_id: str, inj: Inject) -> CostMap:
        """
            Check internal cost cache for given cluster ID and return cost info. If absent, query AWS APIs and put cost info into cache if cluster
            has terminated.
        """
        if cluster_id in inj.cost_cache:
            return inj.cost_cache[cluster_id]
        try:
            cluster_desc: DescribedEmrCluster = cls.check_cluster_cache(cluster_id, inj)
            if not any(cluster_desc):  # cluster immediately terminated
                return cls._empty_costmap()
            estimated_cost: CostMap = inj.calc.estimate_cluster_cost(cluster_id)
            if not any(estimated_cost):  # cluster immediately terminated
                return cls._empty_costmap()
            if 'TERMINATED' in cluster_desc.Status.State:  # TERMINATED'|'TERMINATED_WITH_ERRORS'
                inj.cost_cache[cluster_id] = estimated_cost
            return estimated_cost
        except Exception as e:  # e.g., cancelled clusters might have missing API info
            logger.warning('Problems when getting cluster cost for %s', cluster_id, exc_info=e)
            return cls._empty_costmap()

    @classmethod
    def get_cluster_descriptions(cls, inj: Inject, start: str, end: str) -> Iterator[DescribedEmrCluster]:
        """Transform a sequence of listed clusters into a sequence of described clusters."""
        kwargs = {'CreatedAfter': parse(start), 'CreatedBefore': parse(end)}
        while True:
            cluster_list = inj.client_emr.list_clusters(**kwargs)
            for cluster in cluster_list['Clusters']:
                if 'EndDateTime' not in cluster['Status']['Timeline']:  # Active clusters
                    cluster['Status']['Timeline']['EndDateTime'] = None
                listed_cluster: ListedCluster = ListedCluster(**cluster)
                yield cls.check_cluster_cache(listed_cluster.Id, inj)
            try:
                kwargs['Marker'] = cluster_list['Marker']
            except KeyError:
                break

    @classmethod
    def get_app_list(cls, app_cluster_ids: List[IdPair], start: int, end: int, inj: Inject) -> Tuple[List[DescribedEmrCluster], List[Tuple[int, int]], List[CostMap]]:
        """Fetches cluster descriptions, task/cpu time pairs, and cluster costs. Used in general overview panel."""
        cluster_descs: List[DescribedEmrCluster] = []
        app_times: List[Tuple[int, int]] = []  # application list panel
        calculated_prices: List[CostMap] = []
        for (app_id, cluster_id) in app_cluster_ids:
            calculated_prices.append(EmrUtils.check_cost_cache(cluster_id, inj))
            cluster_descs.append(EmrUtils.check_cluster_cache(cluster_id, inj))
            app_times.append(inj.tsdb_client.get_task_cpu_time(app_id, start, end))
        return cluster_descs, app_times, calculated_prices


class DbxUtils:
    """Utility class for Databricks clusters, mostly contains class methods."""
    @classmethod
    def _get_node_runtime(cls, tsdb_client: TsdbUtils, cluster_id: str, instance_id: str, start: int, eval_time: int):
        """Determines runtime for an instance, not available via APIs."""
        lookback = TsdbUtils.get_lookback(start, eval_time)
        params = {'time': eval_time}
        first_query = TsdbQuery.node_first % (cluster_id, instance_id, lookback)
        last_query = TsdbQuery.node_last % (cluster_id, instance_id, lookback)
        diff_query = ' - '.join((last_query, first_query))
        node_time_response = tsdb_client.prom_client.custom_query(diff_query, params)
        return TsdbUtils.extract_value(node_time_response)

    @classmethod
    def _get_instance_times(cls, prom_client, start: int, end: int, cluster_id: str) -> Dict[str, int]:
        """Return runtimes per instance type for a particular Dbx cluster."""
        instance_times = {}
        instances: List[str] = TsdbUtils.get_instances_of_cluster(prom_client, cluster_id, start, end)
        if len(instances) < 1:
            logger.warning('No instances for cluster %s between %s %s found', cluster_id, start, end)
        for instance in instances:
            instance_type: Optional[str] = TsdbUtils.get_label_value(prom_client, 'instance_type', instance, start, end)
            try:
                node_time = int(cls._get_node_runtime(prom_client, cluster_id, instance, start, end))
                if instance_type is not None and node_time > 0:
                    if instance_type in instance_times:
                        instance_times[instance_type] += node_time
                    else:
                        instance_times[instance_type] = node_time
            except Exception as e:
                logger.warning('Problems when adding times of %s', instance, exc_info=e)
        if len(instance_times) == 0:
            logger.warning('No instance times found for cluster %s between %s and %s', cluster_id, start, end)
        return instance_times

    @classmethod
    def _get_cost_info(cls, start: int, end: int, cluster_id: str, plan: str, inj: Inject) -> Tuple[CostMap, CostMap, CostMap]:
        """Return EC2 costs, DBUs, and DBU costs of a Dbx cluster."""
        ec2_costs: CostMap = {}
        dbus: CostMap = {}
        dbu_costs: CostMap = {}
        instance_times: Dict[str, int] = cls._get_instance_times(inj.tsdb_client, start, end, cluster_id)
        for instance, time in instance_times.items():
            if not inj.calc.available_ec2_price(instance):
                logger.warning('Skipping EC2 costs for unknown instance %s of cluster %s', instance, cluster_id)
                continue
            instance_costs = inj.calc.calculate_ec2_cost(instance, time)
            ec2_costs[instance] = instance_costs
        # DBU calculation:
        cluster_type = cls.get_clustertype(inj.tsdb_client, start, end, cluster_id)
        if cluster_type is None:
            logger.warning('No cluster type identified for %s between %s and %s', cluster_id, start, end)
            return ec2_costs, dbus, dbu_costs
        for instance, time in instance_times.items():
            if not inj.calc.available_dbu_price(instance, cluster_type, plan):
                logger.warning('Skipping DBU info for unknown instance %s of cluster %s under %s and %s', instance, cluster_id, cluster_type, plan)
                continue
            current_dbus: Tuple[float, float] = inj.calc.calculate_dbus_costs(instance, time, cluster_type, plan)
            dbus[instance] = current_dbus[0]
            dbu_costs[instance] = current_dbus[1]
        return ec2_costs, dbus, dbu_costs

    @classmethod
    def _estimate_cost(cls, start: int, end: int, cluster_id: str, plan: str, inj: Inject) -> CostMap:
        """Merge EC2 costs, DBUs, and DBU costs of a Dbx cluster into one map and return it."""
        all_items = {}
        ec2_costs, dbus, dbu_costs = cls._get_cost_info(start, end, cluster_id, plan, inj)
        total = 0.0
        for (instance, cost) in ec2_costs.items():
            all_items[instance + '_COSTEC2'] = cost
            total += cost
        all_items['TOTAL_COSTEC2'] = total
        total = 0.0
        for (instance, cost) in dbu_costs.items():
            all_items[instance + '_COSTDBU'] = cost
            total += cost
        all_items['TOTAL_COSTDBU'] = total
        total = 0.0
        for (instance, cost) in dbus.items():
            all_items[instance + '_DBUS'] = cost
            total += cost
        all_items['TOTAL_DBUS'] = total
        total = all_items['TOTAL_COSTDBU'] + all_items['TOTAL_COSTEC2']
        all_items['TOTAL'] = total
        return all_items

    @classmethod
    def get_dbx_cluster_info(cls, tsdb_client: TsdbUtils, start: int, end: int, cluster_id: str, label: str) -> Optional[str]:
        """Return the value for a provided label from the database."""
        params_inst = {'start': start, 'end': end, 'match[]': TsdbQuery.matcher_dbx % cluster_id}
        result: List[str] = tsdb_client.prom_client.get_label_values(label, params_inst)
        if len(result) < 1:
            logger.warning('Could not find value for label %s of cluster %s between %s and %s', label, cluster_id, start, end)
            return None
        if len(result) > 1:
            logger.warning('Found more than one value of label %s of cluster %s between %s and %s', label, cluster_id, start, end)
        return result[0]

    @classmethod
    def get_clustertype(cls, tsdb_client: TsdbUtils, start: int, end: int, cluster_id: str) -> Optional[DbxClusterType]:
        """Determine Dbx cluster type based on its tag and Spark runtime."""
        is_job_cluster: Optional[str] = cls.get_dbx_cluster_info(tsdb_client, start, end, cluster_id, 'job_cluster')
        spark_version: Optional[str] = cls.get_dbx_cluster_info(tsdb_client, start, end, cluster_id, 'spark_version')
        if is_job_cluster is None or spark_version is None:
            logger.warning('Missing info for cluster %s from %s to %s, %s %s', cluster_id, start, end, is_job_cluster, spark_version)
            return None
        cluster_type = DbxClusterType.determine_cluster_type(is_job_cluster, spark_version)
        return cluster_type

    @classmethod
    def filter_clusters(cls, cluster_details: Iterator[ClusterDetails], start_sec: int, end_sec: int) -> List[DbxCluster]:
        relevant_details: List[DbxCluster] = []
        for detail in cluster_details:
            if start_sec * 1000 <= detail.start_time <= end_sec * 1000:
                relevant_details.append(DbxCluster.extract_core_details(detail))
        return relevant_details

    @classmethod
    def estimate_costs(cls, start: int, end: int, cluster_var: str, plan: str, inj: Inject) -> CostMap:
        """Merge EC2 costs, DBUs, and DBU costs of one or more Dbx clusters into one map and return it."""
        if '|' in cluster_var:  # multiple cluster IDs selected in Grafana variable
            clusters: Set[str] = ClusterUtils.get_variable_values(cluster_var)
            calculated_prices: List[CostMap] = []
            for cluster_id in clusters:
                current_cost = cls._estimate_cost(start, end, cluster_id, plan, inj)
                calculated_prices.append(current_cost)
            return ClusterUtils.add_costs(calculated_prices)
        return cls._estimate_cost(start, end, cluster_var, plan, inj)

    @classmethod
    def estimate_set_costs(cls, start: int, end: int, clusters: Set[str], plan: str, inj: Inject) -> CostMap:
        """Merge EC2 costs, DBUs, and DBU costs of one or more Dbx clusters into one map and return it."""
        calculated_prices: List[CostMap] = []
        for cluster_id in clusters:
            current_cost = cls._estimate_cost(start, end, cluster_id, plan, inj)
            calculated_prices.append(current_cost)
        return ClusterUtils.add_costs(calculated_prices)

    @classmethod
    def get_app_list(cls, app_cluster_ids: List[IdPair], start: int, end: int, plan: str, inj: Inject) -> Tuple[List[DbxCluster], List[Tuple[int, int]], List[CostMap]]:
        """Fetches cluster descriptions, task/cpu time pairs, and cluster costs. Used in general overview panel."""
        cluster_descs: List[DbxCluster] = []
        app_times: List[Tuple[int, int]] = []  # application list panel
        calculated_prices: List[CostMap] = []
        for (app_id, cluster_id) in app_cluster_ids:
            cluster_first, cluster_last = inj.tsdb_client.get_cluster_times(cluster_id, start, end, SupportedPlatforms.AWS_DBX)
            dummy_cluster: DbxCluster = DbxCluster.create_dummy(cluster_id, cluster_first * 1000, cluster_last * 1000)
            cluster_descs.append(dummy_cluster)
            calculated_prices.append(DbxUtils.estimate_costs(start, end, cluster_id, plan, inj))
            app_times.append(inj.tsdb_client.get_task_cpu_time(app_id, start, end))
        return cluster_descs, app_times, calculated_prices

    @classmethod
    def get_active_cluster_ids(cls, dbx_client) -> Set[str]:
        """Return IDs of active Dbx clusters. Used for active resources panel."""
        cluster_details: Iterator[ClusterDetails] = dbx_client.clusters.list()
        active_ids: Set[str] = set()
        for cluster in cluster_details:
            if cluster.state is State.RUNNING or cluster.state is State.RESIZING:
                active_ids.add(cluster.cluster_id)
        return active_ids
