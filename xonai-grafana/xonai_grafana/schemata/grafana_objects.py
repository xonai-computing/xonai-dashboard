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

"""Module containing Grafana domain objects."""
from enum import StrEnum
from typing import Dict, List, Tuple, Optional
from pydantic import BaseModel
from xonai_grafana.cost_estimation.estimator import CostMap
from xonai_grafana.schemata.cloud_objects import DbxCluster, DescribedEmrCluster
from xonai_grafana.utils.logging import LoggerUtils
from xonai_grafana.utils.tsdb import MaxAvg, IdPair, IdPairTimes

logger = LoggerUtils.create_logger('grafana objs')

"""Grafana query and response entities."""


class ClusterData(BaseModel):
    cluster_id: str
    region: str


class Target(BaseModel):
    datasource: Dict[str, str]
    payload: Dict[str, str]
    refId: str
    target: str


class Query(BaseModel):
    """Domain object for Grafana query payloads, used in main loop."""
    panelId: int
    range: dict
    rangeRaw: dict
    interval: str
    intervalMs: int
    maxDataPoints: Optional[int] = None
    targets: list[Target]
    adhocFilters: list

    def get_plan(self) -> str:
        """Returns workspace plan for Dbx panels."""
        return str(self.targets[0].payload["plan"]).lower()

    def get_cluster_var(self) -> str:
        """Returns the cluster ID variable value."""
        return self.targets[0].payload["cluster_id"]


class VariableQuery(BaseModel):
    payload: dict
    range: dict


class PanelType(StrEnum):
    """Constants for metric choices in Grafana panels."""
    APPCOST = 'AppCost'  # Spark board
    APPLIST = 'AppList'  # general overview
    INSTLIST = 'InstanceList'  # cluster overview
    INSTANCEINFO = 'InstanceInfo'  # Instance Type board
    CLUSTERLIST = 'ClusterList'
    CLUSTERLISTDBX = 'ClusterListDbx'
    CLUSTERTYPE = 'ClusterType'  # Dbx clister overview
    BREAKDOWN = 'Breakdown'  # costs
    DBXCOST = 'DbxCost'  # costs
    ACTIVE = 'ActiveResources'  # general overview
    COMPCOSTS = 'ComputeCosts'  # general overview
    COMPUTIL = 'ComputeUtil'  # general overview


class TableResponse(BaseModel):
    """
        Response of main loop, a table structure that can be parsed by Grafana.
        Used as return type in public methods of :class:`GrafanaTables`.
    """
    rows: List
    columns: List[Dict[str, str]]
    type: str = 'table'

    def __int__(self, rows: List, columns:  List[Dict[str, str]]):
        self.rows = rows
        self.columns = columns


class GrafanaTables:
    empty_table = TableResponse(rows=[], columns=[])

    """Utility class for creating table responses for different Grafana panels."""
    @classmethod
    def _get_cluster_core_columns(cls) -> List[Dict[str, str]]:
        core_columns = [{"text": "Name", "type": "string"}, {"text": "Cluster Id", "type": "string"}, {"text": "Status", "type": "string"},
                        {"text": "Creation Time", "type": "date"}, {"text": "Termination Time", "type": "date"}]
        return core_columns

    @classmethod
    def _get_cluster_ext_columns(cls) -> List[Dict[str, str]]:
        cluster_ext_columns: List[Dict[str, str]] = cls._get_cluster_core_columns()
        cluster_ext_columns.append({"text": "Creation Redirect", "type": "date"})
        cluster_ext_columns.append({"text": "Termination Redirect", "type": "date"})
        return cluster_ext_columns

    @classmethod
    def _get_util_columns(cls) -> List[Dict[str, str]]:
        util_columns: List[Dict[str, str]] = [{"text": "Max CPU", "type": "number"}, {"text": "Avg CPU", "type": "number"},
                                              {"text": "Max Memory", "type": "number"}, {"text": "Avg Memory", "type": "number"}]
        return util_columns

    @classmethod
    def _get_instance_info(cls, instance_info: Dict[str, str]) -> Tuple[List[Dict[str, str]], List[Tuple]]:
        columns = [{"text": "Name", "type": "string"}, {"text": "Family", "type": "string"}, {"text": "Processor", "type": "string"},
                   {"text": "Arch", "type": "string"}, {"text": "vCPU", "type": "number"}, {"text": "Memory", "type": "string"},
                   {"text": "Storage", "type": "string"}, {"text": "Network", "type": "string"}, {"text": "EBS tp", "type": "string"}]
        rows = []
        name = instance_info['instanceType'] if 'instanceType' in instance_info else 'NA'
        family = instance_info['instanceFamily'] if 'instanceFamily' in instance_info else 'NA'
        processor = instance_info['physicalProcessor'] if 'physicalProcessor' in instance_info else 'NA'
        arch = instance_info['processorArchitecture'] if 'processorArchitecture' in instance_info else 'NA'
        vcpu = instance_info['vcpu'] if 'vcpu' in instance_info else '0'
        memory = instance_info['memory'] if 'memory' in instance_info else 'NA'
        storage = instance_info['storage'] if 'storage' in instance_info else 'NA'
        network = instance_info['networkPerformance'] if 'networkPerformance' in instance_info else 'NA'
        ebs = instance_info['dedicatedEbsThroughput'] if 'dedicatedEbsThroughput' in instance_info else 'NA'
        rows.append((name, family, processor, arch, vcpu, memory, storage, network, ebs))
        return columns, rows

    @classmethod
    def get_resource_table(cls, nodes_up: int, cpu_cores: int, total_ram: int, total_disk: int) -> TableResponse:
        columns = [{"text": "Nodes Up", "type": "integer"}, {"text": "CPU Cores", "type": "integer"}, {"text": "Total RAM", "type": "integer"},
                   {"text": "Total Disk", "type": "integer"}]
        rows = [[nodes_up, cpu_cores, total_ram, total_disk]]
        return TableResponse(rows=rows, columns=columns)

    @classmethod
    def get_cost_table(cls, cost_info: Dict) -> TableResponse:
        columns = []
        column_names = list(cost_info.keys())
        rows = []
        for column_name in column_names:
            columns.append({"text": column_name, "type": "number"})
            rows.append(cost_info[column_name])
        return TableResponse(rows=[rows], columns=columns)

    @classmethod
    def get_dbx_cinfo_table(cls, cluster_details: List[DbxCluster]) -> TableResponse:
        columns = cls._get_cluster_ext_columns()
        columns.append({"text": "Source", "type": "string"})
        columns.append({"text": "Is Job", "type": "string"})
        columns.append({"text": "Is Notebook", "type": "string"})
        rows = []
        for detail in cluster_details:
            elements_ext = detail.get_core_elems()
            elements_ext.extend([detail.is_jobs, detail.is_notebooks])
            rows.append(elements_ext)
        return TableResponse(rows=rows, columns=columns)

    @classmethod
    def get_totalutil_table(cls, total_util: float, clusters: int) -> TableResponse:
        columns = [{"text": "CPU Utilization", "type": "number"}, {"text": "Clusters", "type": "integer"}]
        rows = [(total_util, clusters)]
        return TableResponse(rows=rows, columns=columns)

    @classmethod
    def get_app_table(cls, app_cluster_ids: List[IdPair], cost_infos: List[Dict], cluster_secs: List[float], app_ms: List[float]) -> TableResponse:
        if not len(app_cluster_ids) == len(cost_infos) == len(cluster_secs) == len(app_ms):
            logger.warning('Invalid arguments for get_app_table: %s %s %s %s', app_cluster_ids, cost_infos, cluster_secs, app_ms)
            return GrafanaTables.empty_table
        columns = [{"text": "App ID", "type": "string"}, {"text": "Cluster ID", "type": "string"}, {"text": "Cluster CPU Time", "type": "number"},
                   {"text": "Cluster Cost", "type": "number"}, {"text": "App JVM CPU Time", "type": "number"}, {"text": "App Cost", "type": "number"}]
        rows = []
        for index, (app_id, cluster_id) in enumerate(app_cluster_ids):
            cost_info = cost_infos[index]
            cluster_sec = cluster_secs[index]
            current_app_ms = app_ms[index]
            proportion = 0.0
            if cluster_sec > 0 and current_app_ms > 0:
                cluster_ms = cluster_sec * 1000
                proportion = current_app_ms / cluster_ms
            rows.append([app_id, cluster_id, cluster_sec, cost_info["TOTAL"], current_app_ms, proportion * cost_info["TOTAL"]])
        return TableResponse(rows=rows, columns=columns)

    @classmethod
    def get_inst_table(cls, instance_redir: List[IdPairTimes], type_role: List[IdPair]) -> TableResponse:
        if not len(instance_redir) == len(type_role):
            logger.warning('Invalid arguments for get_inst_table: %s %s', instance_redir, type_role)
            return GrafanaTables.empty_table
        columns = [{"text": "Instance ID", "type": "string"}, {"text": "Node Role", "type": "string"}, {"text": "Instance Type", "type": "string"},
                   {"text": "Cluster ID", "type": "string"}, {"text": "Start", "type": "date"}, {"text": "End", "type": "date"},
                   {"text": "Start Red", "type": "date"}, {"text": "End Red", "type": "date"}]  # Hidden columns for redirection links
        rows = []
        for index, info in enumerate(instance_redir):
            rows.append([info[0], type_role[index][1], type_role[index][0], info[1], info[2], info[3], info[4], info[5]])
        return TableResponse(rows=rows, columns=columns)

    @classmethod
    def get_app_overview(cls, app_cluster_ids: List[IdPair], cost_infos: List[CostMap], cluster_descs: List[DescribedEmrCluster | DbxCluster], app_times: List[Tuple[int, int]],
                             short: bool = False) -> TableResponse:
        if not len(app_cluster_ids) == len(cost_infos) == len(cluster_descs) == len(app_times):
            logger.warning('Invalid arguments for get_app_overview: %s %s %s %s', app_cluster_ids, cost_infos, cluster_descs, app_times)
            return GrafanaTables.empty_table
        columns = [{"text": "App ID", "type": "string"}, {"text": "Cluster ID", "type": "string"}, {"text": "Cluster Cost", "type": "number"},
                   {"text": "Instance Hours", "type": "number"}, {"text": "CPU Time %", "type": "number"}, {"text": "Creation Red", "type": "date"}, {"text": "Termination Red", "type": "date"}]
        if short:
            columns = [{"text": "App ID", "type": "string"}, {"text": "Cluster ID", "type": "string"}, {"text": "Cluster Cost", "type": "number"},
                       {"text": "CPU Time %", "type": "number"}, {"text": "Creation Red", "type": "date"}, {"text": "Termination Red", "type": "date"}]
        rows = []
        for index, (app_id, cluster_id) in enumerate(app_cluster_ids):
            cost_info = cost_infos[index]["TOTAL"]
            cluster_desc = cluster_descs[index]
            (task_time, cpu_time) = app_times[index]
            cpu_per = 0.0
            if task_time == 0.0:
                logger.warning('Invalid CPU time %s, task time %s for %s', cpu_time, task_time, app_id)
            elif cpu_time > task_time:  # can happen in local applications
                cpu_per = 0.0
            else:
                cpu_per = cpu_time / task_time
            if short:
                (creation_ms, term_ms) = cluster_desc.start_redir, cluster_desc.end_redir
                rows.append([app_id, cluster_id, cost_info, cpu_per, creation_ms, term_ms])
            else:
                hours = cluster_desc.NormalizedInstanceHours
                (_, creation_ms, _, term_ms) = cluster_desc.get_start_end()
                rows.append([app_id, cluster_id, cost_info, hours, cpu_per, creation_ms, term_ms])
        return TableResponse(rows=rows, columns=columns)

    @classmethod
    def get_emr_clist_table(cls, clusters, util_info: List[Tuple[MaxAvg, MaxAvg]], costs=None) -> TableResponse:
        if not len(clusters) == len(util_info):
            logger.warning('Invalid arguments for get_emr_clist_table: %s %s', clusters, util_info)
            return GrafanaTables.empty_table
        columns = cls._get_cluster_ext_columns()
        columns.append({"text": "Norm. Inst. Hours", "type": "integer"})
        columns.append({"text": "Tags", "type": "list"})
        if costs is not None:
            columns.append({"text": "Total Cost", "type": "number"})
        columns = columns + cls._get_util_columns()
        rows = []
        for index, cluster in enumerate(clusters):
            cluster_ele: List = cluster.get_core_elems()
            if costs is not None:
                cluster_ele.append(costs[index]["TOTAL"])
            cluster_ele.extend(util_info[index][0])
            cluster_ele.extend(util_info[index][1])
            rows.append(cluster_ele)
        return TableResponse(columns=columns, rows=rows)

    @classmethod
    def get_dbx_clist_table(cls, clusters: List[DbxCluster], costs: List[CostMap], util_info: List[Tuple[MaxAvg, MaxAvg]]) -> TableResponse:
        if not len(clusters) == len(costs) == len(util_info):
            logger.warning('Invalid arguments for get_dbx_clist_table: %s %s %s', clusters, costs, util_info)
            return GrafanaTables.empty_table
        columns = cls._get_cluster_ext_columns()
        columns.append({"text": "Source", "type": "string"})
        columns.append({"text": "Total Cost", "type": "number"})
        columns = columns + cls._get_util_columns()
        rows = []
        for index, cluster in enumerate(clusters):
            cluster_ele: List = cluster.get_core_elems()
            cluster_ele.append(costs[index]["TOTAL"])
            cluster_ele.extend(util_info[index][0])
            cluster_ele.extend(util_info[index][1])
            rows.append(cluster_ele)
        return TableResponse(rows=rows, columns=columns)

    @classmethod
    def get_emr_inst_info_table(cls, instance_info: Dict[str, str], ec2_cost: float, emr_cost: float) -> TableResponse:
        columns, rows = cls._get_instance_info(instance_info)
        columns.append({"text": "EC2 Cost", "type": "number"})
        columns.append({"text": "EMR Cost", "type": "number"})
        extended_rows = [rows.pop() + (ec2_cost, emr_cost)]
        return TableResponse(rows=extended_rows, columns=columns)

    @classmethod
    def get_dbu_inst_info_table(cls, instance_info: Dict[str, str], ec2_cost: float, dbu: Tuple[float, float], dbu_photon: Tuple[float, float]) -> TableResponse:
        columns, rows = cls._get_instance_info(instance_info)
        columns.append({"text": "EC2 Cost", "type": "number"})
        columns.append({"text": "DBUs", "type": "number"})
        columns.append({"text": "DBU Cost", "type": "number"})
        columns.append({"text": "Photon DBUs", "type": "number"})
        columns.append({"text": "Photon DBU Cost", "type": "number"})
        dbu_entry = dbu[0] if dbu[0] > 0.0 else None
        dbu_cost_entry = dbu[1] if dbu[1] > 0.0 else None
        dbu_photon_entry = dbu_photon[0] if dbu_photon[0] > 0.0 else None
        dbu_photon_cost_entry = dbu_photon[1] if dbu_photon[1] > 0.0 else None
        extended_rows = [rows.pop() + (ec2_cost, dbu_entry, dbu_cost_entry, dbu_photon_entry, dbu_photon_cost_entry)]
        return TableResponse(rows=extended_rows, columns=columns)
