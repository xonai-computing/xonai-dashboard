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

"""Module containing time series database functionality."""
from datetime import datetime
from dateutil.tz import tzutc, tzlocal
from enum import StrEnum
from math import ceil
from typing import Dict, List, Tuple, Optional, Set
from prometheus_api_client import PrometheusConnect
from xonai_grafana.schemata.cloud_objects import DescribedEmrCluster, SupportedPlatforms, AllClusters, DbxCluster
from xonai_grafana.utils.logging import LoggerUtils

logger = LoggerUtils.create_logger('tsdb utils')

"""Type aliases."""
MaxAvg = Tuple[Optional[float], Optional[float]]
IdPair = Tuple[str, str]
IdPairTimes = Tuple[str, str, int, int, int, int]


class QueryType(StrEnum):
    """Wrapper class for similar time consumption queries, used as argument to :func:`get_consumed_time`."""
    APP = 'sum(last_over_time(spark_jvmCpuTime{app_id="%s"}[%s]))'
    TASKTIME = 'sum(last_over_time(spark_runTime_count{app_id="%s"}[%s]))'
    CPUTIME = 'sum(last_over_time(spark_cpuTime_count{app_id="%s"}[%s]))'
    CLUSTER = 'sum(last_over_time(node_cpu_seconds_total{cluster_id="%s"}[%s]))'


class TsdbQuery:
    """Holds constants for database queries."""
    cpu_util = '1 - (avg by (cluster_id) (irate(node_cpu_seconds_total{cluster_id="%s", mode="idle"}%s)))'
    mem_util = '1 - (sum(node_memory_MemAvailable_bytes {cluster_id=~"%s"}) by (cluster_id)) / (sum(node_memory_MemTotal_bytes {cluster_id=~"%s"}) by (cluster_id))'
    app_cluster_id_query = 'last_over_time(spark_jvmCpuTime{app_id="%s", agent="driver"}[%s])'
    # Timestamp queries for nodes and clusters
    node_first = 'tfirst_over_time(up{job="node_scraper", cluster_id=~"%s", instance=~"%s"}[%s])'
    node_last = 'tlast_over_time(up{job="node_scraper", cluster_id=~"%s", instance=~"%s"}[%s])'
    cluster_first = 'tfirst_over_time(up{job="node_scraper", cluster_id=~"%s", %s}[%s])'  # >1 results without infix label
    cluster_last = 'tlast_over_time(up{job="node_scraper", cluster_id=~"%s", %s}[%s])'  # >1 result without infix label
    # Master labels
    emr_master_label = 'role="master"'
    dbx_master_label = 'on_driver="true"'
    # Label queries
    label_query = 'up{job="node_scraper", instance=~"%s"}'
    matcher_cluster = 'up{job="node_scraper"}'
    matcher_instances = 'up{job="node_scraper", cluster_id=~"%s"}'
    matcher_dbx = 'up{job="node_scraper", on_driver="true", cluster_id=~"%s"}'
    # Active resources
    nodes_up_query = 'count(last_over_time(up{job="node_scraper", cluster_id=~"%s"}[%s]))'
    cpu_cores_query = 'count(last_over_time(node_cpu_seconds_total{job="node_scraper", mode="idle", cluster_id=~"%s"}[%s]))'
    total_ram_query = 'sum(last_over_time(node_memory_MemTotal_bytes{job="node_scraper", cluster_id=~"%s"}[%s]))'
    total_disk_query = 'sum(last_over_time(node_filesystem_size_bytes{job="node_scraper", cluster_id=~"%s", fstype!="tmpfs", mountpoint!~".*tmp.*"}[%s]))'


class TsdbUtils:
    """Utility class for time-series databases, mostly contains helper methods."""

    def __init__(self):
        self.prom_client = PrometheusConnect(url="http://localhost:8428", disable_ssl=True)
        self.window_size = "[40s]"  # for utilization queries, scrape interval = 10s
        self.range_step = "10s"

    def _get_clusters_from_db(self, start: int, end: int) -> List[str]:
        """Returns cluster IDs fetched from the DB. Used when a tracked cluster from a longer time ago isn't covered by AWS APIs anymore."""
        params_cluster = {'end': end, 'start': start, 'match[]': TsdbQuery.matcher_cluster}
        clusters = self.prom_client.get_label_values('cluster_id', params_cluster)
        return clusters

    def _get_node_times(self, cluster_id: str, instance_id: str, start: int, eval_time: int) -> Tuple[float, float]:
        """Returns instance start/end times fetched from the DB in epoch seconds. Used for cluster instance panel."""
        lookback = self.get_lookback(start, eval_time)
        params = {'time': eval_time}
        first_query = TsdbQuery.node_first % (cluster_id, instance_id, lookback)
        last_query = TsdbQuery.node_last % (cluster_id, instance_id, lookback)
        node_first = self.extract_value(self.prom_client.custom_query(first_query, params))
        node_last = self.extract_value(self.prom_client.custom_query(last_query, params))
        return node_first, node_last

    def _get_node_starts_ends(self, instance_id: str, cluster_id: str, start: int, end: int) -> Tuple[int, int, int, int]:
        """Returns instance start/end/redirection times in epoch ms. Used for cluster instance panel."""
        node_start = 0
        node_end = 0
        try:
            raw_start, raw_end = self._get_node_times(cluster_id, instance_id, start, end)
            node_start = round(float(raw_start)) * 1000
            node_end = round(float(raw_end)) * 1000
        except Exception as e:
            logger.warning('Instance %s end time %s malformed', instance_id, end, exc_info=e)
        start_offset = AllClusters.get_redirect_ms(node_start)
        end_offset = AllClusters.get_redirect_ms(node_end, False)
        return node_start, start_offset, node_end, end_offset

    def _get_instance_and_cluster(self, cluster_var: str, start: int, end: int) -> List[IdPair]:  # relevant for EMR & DBx
        """Returns list of instances/clusters for a cluster id which might contain globs. Used for cluster instance panel."""
        instance_ids = self.get_instances_of_cluster(cluster_var, start, end)
        instance_cluster: List[IdPair] = []
        for instance_id in instance_ids:  # get cluster ids for retrieving redirection starts/ends
            matcher_cluster = TsdbQuery.label_query % instance_id
            params_cluster = {'end': end, 'start': start, 'match[]': matcher_cluster}
            cluster_res = self.prom_client.get_label_values('cluster_id', params_cluster)
            if len(cluster_res) != 1:
                logger.warning('Not a single cluster id %s for instance %s', cluster_res, instance_id)
                continue
            instance_cluster.append((instance_id, cluster_res[0]))
        return instance_cluster

    def _summarize_stats(self, pairs: List[Tuple[int, str]]) -> Tuple[float, float]:
        """Returns max and average value for timeseries samples. Used for utilization calculations."""
        count = len(pairs)
        running_sum = 0.0
        max_val = 0.0
        for pair in pairs:
            try:
                value = float(pair[1])
                running_sum += value
                max_val = value if value > max_val else max_val
            except Exception as e:
                logger.warning('Metrics to summarize malformed: %s', pairs, exc_info=e)
                running_sum = 0.0
                count = 0
                break
        mean = running_sum / count if count > 0 else 0.0
        return max_val, mean

    def _get_cluster_utilization(self, cluster_info: DescribedEmrCluster | DbxCluster, query: str) -> MaxAvg:
        """Returns CPU or memory utilization (max & average) for a terminated EMR or DBx cluster."""
        start_time: datetime = datetime.min
        end_time: datetime = start_time
        if isinstance(cluster_info, DescribedEmrCluster):
            if 'TERMINATED' not in cluster_info.Status.State.upper():
                return None, None
            start_time = cluster_info.Status.Timeline.CreationDateTime
            end_time = cluster_info.Status.Timeline.EndDateTime
        elif isinstance(cluster_info, DbxCluster):
            if 'TERMINATED' not in cluster_info.state.upper():
                return None, None
            start_time = datetime.fromtimestamp(cluster_info.start / 1000.0, tzutc())
            end_time = datetime.fromtimestamp(cluster_info.end / 1000.0, tzutc())
        else:
            logger.warning('Unknown cluster type: %s', cluster_info)
        metric_data = self.prom_client.custom_query_range(query, start_time=start_time, end_time=end_time, step=self.range_step)
        if len(metric_data) < 1:  # cluster without an agent installed
            return None, None
        if len(metric_data) > 1:  # something went wrong in the DB
            logger.warning('More than one utilization series found for %s', cluster_info)
            return None, None
        (max_val, mean) = self._summarize_stats(metric_data[0]['values'])
        return max_val, mean

    def get_cluster_times(self, cluster_id: str, start: int, eval_time: int, platform: SupportedPlatforms) -> Tuple[int, int]:
        """
            Returns cluster start/end times (via master node) in epoch ms.
            Used when a tracked cluster from a longer time ago isn't covered by AWS APIs anymore.
        """
        lookback = self.get_lookback(start, eval_time)
        cluster_start = 0
        cluster_end = 0
        params = {'time': eval_time}
        master_label = ''  # >1 result without `master` label
        if platform is SupportedPlatforms.AWS_EMR:
            master_label = TsdbQuery.emr_master_label
        elif platform is SupportedPlatforms.AWS_DBX:
            master_label = TsdbQuery.dbx_master_label
        try:
            first_query = TsdbQuery.cluster_first % (cluster_id, master_label, lookback)
            last_query = TsdbQuery.cluster_last % (cluster_id, master_label, lookback)  # multi values for interactive clusters possible
            cluster_first = self.extract_multi_value(self.prom_client.custom_query(first_query, params))  # e.g., 1708704315.792
            cluster_last = self.extract_multi_value(self.prom_client.custom_query(last_query, params), False)  # e.g., 1708704395.792
            cluster_start = round(float(cluster_first))
            cluster_end = round(float(cluster_last))
        except Exception as e:
            logger.warning('Cluster start or end for %s malformed', cluster_id, exc_info=e)
        return cluster_start, cluster_end

    @classmethod
    def get_lookback(cls, start: int, end: int) -> str:
        """Returns a normalized time duration, required for certain tsdb queries."""
        if start > end:
            logger.warning('Start time %s not smaller than end time %s', start, end)
            return '1w'
        diff = end - start
        if diff <= 3600:  # one hour
            return '1h'
        hours = ceil(diff / 3600)
        return f'{hours}h'

    @classmethod
    def convert_to_unixs(cls, timestring: str) -> int:
        """Converts the provided timestamp string into unix seconds."""
        try:
            parsed = datetime.fromisoformat(timestring)
            return int(parsed.timestamp())
        except Exception as e:
            logger.warning('Problems when parsing timestamp %s', timestring, exc_info=e)
            return 0

    @classmethod
    def extract_value(cls, response: List[Dict]):
        """Extracts the metric value from a TSDB response."""
        if len(response) == 0:
            return 0.0
        if len(response) != 1 or 'value' not in response[0]:
            logger.warning('TSDB response malformed: %s', response)
            return 0.0
        returned_value = response[0]['value']
        if len(returned_value) != 2:
            logger.warning('TSDB response value malformed: %s', response)
            return 0.0
        return returned_value[1]

    @classmethod
    def extract_multi_value(cls, responses: List[Dict], mini: bool = True):
        """Extracts the metric value from a TSDB response, supports multiple responses."""
        if len(responses) == 0 or 'value' not in responses[0]:
            logger.warning('TSDB response (multi) malformed: %s', responses)
            return 0.0
        if len(responses) == 1:
            return TsdbUtils.extract_value(responses)
        extracted_vals = []
        for response in responses:
            returned_value = response['value']
            if len(returned_value) != 2:
                logger.warning('TSDB multi response value malformed: %s', response)
                continue
            extracted_vals.append(returned_value[1])
        if mini:
            return min(extracted_vals)
        return max(extracted_vals)

    def get_nodes_starts_ends(self, cluster_var: str, start: int, end: int) -> List[IdPairTimes]:
        """Returns instance's cluster ID and start/end/redir times fetched from the DB in epoch seconds. Used for cluster instance panel."""
        instance_times: List[IdPairTimes] = []
        instance_cluster: List[IdPair] = self._get_instance_and_cluster(cluster_var, start, end)
        for instance_id, cluster_id in instance_cluster:
            node_start, start_offset, node_end, end_offset = self._get_node_starts_ends(instance_id, cluster_id, start, end)
            instance_times.append((instance_id, cluster_id, node_start, node_end, start_offset, end_offset))
        return instance_times

    def get_resources(self, cluster_ids: str, start: int, eval_time: int) -> Tuple[int, int, int, int]:
        """Fetches # active nodes, # CPUs, total RAM, and total disk from the DB. Used for active resources panel."""
        if cluster_ids == '':
            return 0, 0, 0, 0
        lookback = self.get_lookback(start, eval_time)
        params = {'time': eval_time}
        nodes_query = TsdbQuery.nodes_up_query % (cluster_ids, lookback)
        nodes_up_res = self.prom_client.custom_query(nodes_query, params)
        nodes_up = self.extract_value(nodes_up_res)
        cpu_query = TsdbQuery.cpu_cores_query % (cluster_ids, lookback)
        cpu_cores_res = self.prom_client.custom_query(cpu_query, params)
        cpu_cores = self.extract_value(cpu_cores_res)
        ram_query = TsdbQuery.total_ram_query % (cluster_ids, lookback)
        total_ram_res = self.prom_client.custom_query(ram_query, params)
        total_ram = self.extract_value(total_ram_res)
        disk_query = TsdbQuery.total_disk_query % (cluster_ids, lookback)
        total_disk_res = self.prom_client.custom_query(disk_query, params)
        total_disk = self.extract_value(total_disk_res)
        return nodes_up, cpu_cores, total_ram, total_disk

    def get_consumed_time(self, entity_id: str, start: int, eval_time: int, query_type: QueryType) -> int:
        """Unified method for similar cpu/runtime queries, returns consumed milliseconds."""
        lookback = self.get_lookback(start, eval_time)
        time_ms = 0
        params = {'time': eval_time}
        query = query_type % (entity_id, lookback)
        if query_type == QueryType.APP or query_type == QueryType.CPUTIME:
            result_app: List[Dict] = self.prom_client.custom_query(query, params)
            try:
                extracted_value = self.extract_value(result_app)
                if isinstance(extracted_value, str) and '.' in extracted_value:  # potential issues with local apps & Spark's metrics system
                    time_ms = round(float(extracted_value)) / 1000000
                    logger.warning('Extracted consumed time %s not an integer', extracted_value)
                else:
                    time_ms = int(self.extract_value(result_app)) / 1000000
            except Exception as e:
                logger.warning('Result for DB query %s malformed %s', query, entity_id, exc_info=e)
        elif query_type == QueryType.TASKTIME or query_type == QueryType.CLUSTER:
            result_tasks: List[Dict] = self.prom_client.custom_query(query, params)
            try:
                if query_type == QueryType.CLUSTER:
                    time_ms = round(float(self.extract_value(result_tasks)))
                else:
                    time_ms = int(self.extract_value(result_tasks))
            except Exception as e:
                logger.warning('Result for DB query %s malformed %s', query, result_tasks, exc_info=e)
        return time_ms

    def get_task_cpu_time(self, app_id: str, start: int, end: int) -> Tuple[int, int]:
        """Unified method for similar cpu/runtime queries, returns consumed milliseconds."""
        task_time = self.get_consumed_time(app_id, start, end, QueryType.TASKTIME)
        cpu_time = self.get_consumed_time(app_id, start, end, QueryType.CPUTIME)
        if cpu_time > task_time:
            logger.warning('CPU time %s was greater than task time %s for %s', cpu_time, task_time, app_id)
        return task_time, cpu_time

    def fill_api_gaps(self, clusters: List[DescribedEmrCluster | DbxCluster], start_sec: int, end_sec: int, platform: SupportedPlatforms) -> None:
        """
            Appends (if missing) cluster core data fetched from DB to cluster list created from API results.
            Used in cluster list panels when a tracked cluster from a longer time ago isn't covered by AWS APIs anymore.
        """
        clusters_from_api: Set[str] = {cluster.Id for cluster in clusters}
        clusters_from_db: Set[str] = set(self._get_clusters_from_db(start_sec, end_sec))
        for id_db in clusters_from_db:
            if id_db not in clusters_from_api:
                cluster_first, cluster_last = self.get_cluster_times(id_db, start_sec, end_sec, platform)
                if cluster_first < start_sec or cluster_first > end_sec:  # preceding label values call not always precise => filter again
                    logger.warning('Skipping retrieved cluster %s with %s/%s, range was %s/%s', id_db, cluster_first, cluster_last, start_sec, end_sec)
                    continue
                if platform is SupportedPlatforms.AWS_EMR:
                    first_datetime = datetime.fromtimestamp(cluster_first, tzlocal())
                    last_datetime = datetime.fromtimestamp(cluster_last, tzlocal())
                    dummy_cluster = DescribedEmrCluster.create_dummy(id_db, first_datetime, last_datetime)
                    clusters.append(dummy_cluster)
                elif platform is SupportedPlatforms.AWS_DBX:
                    dummy_cluster = DbxCluster.create_dummy(id_db, cluster_first * 1000, cluster_last * 1000)
                    clusters.append(dummy_cluster)

    def get_cluster_utilizations(self, cluster_info: DescribedEmrCluster | DbxCluster) -> Tuple[MaxAvg, MaxAvg]:
        """Returns CPU and memory utilization (max & average) for a terminated EMR or DBx cluster."""
        cpu_util_query = TsdbQuery.cpu_util % (cluster_info.Id, self.window_size)
        cpu_utilization = self._get_cluster_utilization(cluster_info, cpu_util_query)
        mem_util_query = TsdbQuery.mem_util % (cluster_info.Id, cluster_info.Id)
        mem_utilization = self._get_cluster_utilization(cluster_info, mem_util_query)
        return cpu_utilization, mem_utilization

    def get_label_value(self, label: str, instance_id: str, start: int, end: int) -> Optional[str]:
        """Returns value for a provided label and instance from the database."""
        matcher_inst = TsdbQuery.label_query % instance_id
        params_inst = {'start': start, 'end': end, 'match[]': matcher_inst}
        result = self.prom_client.get_label_values(label, params_inst)
        if len(result) < 1:  # e.g., labels on Dbx worker nodes
            return None
        if len(result) > 1:
            logger.warning('Not a unique value for label %s of instance %s: %s', label, instance_id, result)
            return None
        return result[0]

    def get_instances_of_cluster(self, cluster_var: str, start: int, end: int) -> List[str]:
        """Returns instances for provided cluster (glob) from the database. Written by Philipp Schwab."""
        matcher_inst = TsdbQuery.matcher_instances % cluster_var
        params_inst = {'start': start, 'end': end, 'match[]': matcher_inst}
        return self.prom_client.get_label_values('instance', params_inst)

    def get_app_cluster_ids(self, start: int, end: int) -> List[IdPair]:
        """Returns applications with cluster IDs from the database, used in general overview dashboard."""
        app_cluster_ids: List[IdPair] = []
        app_ids = self.prom_client.get_label_values('app_id', {'end': end, 'start': start})
        for app_id in app_ids:
            query = TsdbQuery.app_cluster_id_query % (app_id, self.get_lookback(start, end))
            result = self.prom_client.custom_query(query, {'time': end})  # evaluation timestamp for instant query
            if len(result) > 0 and 'metric' in result[0] and 'cluster_id' in result[0]['metric']:
                cluster_id = result[0]['metric']['cluster_id']
                app_cluster_ids.append((app_id, cluster_id))
            else:  # possible in boundary cases, get_label_values less precise with time
                logger.warning('Problem with retrieving cluster id for app id %s, %s', app_id, result)
        return app_cluster_ids

    def get_instance_list(self, cluster_var: str, start: int, end: int, platform: SupportedPlatforms) -> Tuple[List[IdPairTimes], List[IdPair]]:
        """Returns core instance info for the given cluster ID(s)."""
        instance_times: List[IdPairTimes] = self.get_nodes_starts_ends(cluster_var, start, end)
        type_role: List[IdPair] = []
        for instance_time in instance_times:
            inst_type = self.get_label_value('instance_type', instance_time[0], start, end)
            node_role = ''
            if platform is SupportedPlatforms.AWS_EMR:
                node_role = self.get_label_value('role', instance_time[0], start, end)
            elif platform is SupportedPlatforms.AWS_DBX:
                role_value = self.get_label_value('on_driver', instance_time[0], start, end)
                node_role = 'driver' if role_value == 'true' else 'worker'
            type_role.append((inst_type, node_role))
        return instance_times, type_role
