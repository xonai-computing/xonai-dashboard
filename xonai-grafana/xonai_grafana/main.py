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

"""Module containing the Grafana query endpoints."""
from typing import List, Dict, Tuple, Set, Iterator
from fastapi import FastAPI, status, Depends
from dateutil.parser import parse
from starlette.middleware.cors import CORSMiddleware
from databricks.sdk.service.compute import ClusterDetails
from xonai_grafana.cost_estimation.estimator import DbxClusterType
from xonai_grafana.schemata.cloud_objects import DescribedEmrCluster, SupportedPlatforms, DbxCluster
from xonai_grafana.schemata.grafana_objects import GrafanaTables, PanelType, TableResponse, Query, Target, ClusterData, VariableQuery
from xonai_grafana.utils.dependencies import Inject, get_cloud_env
from xonai_grafana.utils.logging import LoggerUtils
from xonai_grafana.utils.tsdb import TsdbUtils, QueryType, MaxAvg, IdPair
from xonai_grafana.utils.cloud import DbxUtils, EmrUtils, CostMap, ClusterUtils

logger = LoggerUtils.create_logger(__name__)
active_region, activated_platform = get_cloud_env()  # active_region is global, used and maybe reset in main loop
logger.info('Launching UI server for %s with initial region %s', activated_platform, active_region)
app = FastAPI()  # main application object
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # default Grafana port
    allow_credentials=True,
    allow_headers=["*"],
    allow_methods=["*"],
)
injection = Inject(active_region, activated_platform)  # embeds caches and cloud/database clients


def get_dependencies() -> Inject:
    """Dependency injection of clients and caches into main and variable loop."""
    yield injection


"""
    Obligatory simpod endpoints.
    See https://grafana.com/grafana/plugins/simpod-json-datasource
"""


@app.get("/", status_code=status.HTTP_200_OK)
def test_connection():
    """Endpoint for Grafana data source tests."""
    return "200"


@app.post("/metrics", status_code=status.HTTP_200_OK)
def return_available_metrics():
    """Endpoint for Grafana panel metric drop-downs."""
    return [panel.value for panel in PanelType]


@app.post("/metric-payload-options", status_code=status.HTTP_200_OK)
def return_payload_options():
    """Endpoint for Grafana panel metric payloads."""
    return []


@app.post("/query", response_model=List[TableResponse], status_code=status.HTTP_200_OK)
def main_loop(query: Query, inj: Inject = Depends(get_dependencies)):
    """
        Main loop, gets called whenever a Grafana panel that uses JSON data source is opened.
        Determines execution path by pattern matching the supplied panel target argument against :class:`PanelType`.
        Grafana query payloads are automatically parsed as :class:`Query`.
        Returns a single element list of JSON objects corresponding to :class:`TableResponse`.
    """
    response: List[TableResponse] = []
    if len(query.targets) == 0:
        return response
    target: Target = query.targets[0]
    global active_region
    try:
        target_panel = target.target
        start_string = query.range['from']  # e.g., 2024-02-02T13:12:52.121Z
        start_sec: int = TsdbUtils.convert_to_unixs(start_string)  # e.g., 1706879572
        end_string = query.range['to']
        end_sec: int = TsdbUtils.convert_to_unixs(end_string)
        if target_panel == PanelType.CLUSTERLISTDBX:  # dbx cluster list panel, API does not specify region
            cluster_details: Iterator[ClusterDetails] = inj.client_dbx.clusters.list()
            relevant_details: List[DbxCluster] = DbxUtils.filter_clusters(cluster_details, start_sec, end_sec)
            inj.tsdb_client.fill_api_gaps(relevant_details, start_sec, end_sec, activated_platform)  # fill potential API gaps
            response.append(GrafanaTables.get_dbx_cinfo_table(relevant_details))
            return response
        if target_panel == PanelType.INSTLIST or target_panel == PanelType.CLUSTERTYPE:  # instance list panel
            cluster_var = query.get_cluster_var()
            if target_panel == PanelType.INSTLIST:
                (instance_times, type_role) = inj.tsdb_client.get_instance_list(cluster_var, start_sec, end_sec, activated_platform)
                response.append(GrafanaTables.get_inst_table(instance_times, type_role))
                return response
            if target_panel == PanelType.CLUSTERTYPE:
                cluster_types: Set[str] = set()
                cluster_ids = ClusterUtils.get_variable_values(cluster_var)
                for cluster_id in cluster_ids:
                    cluster_type: DbxClusterType = DbxUtils.get_clustertype(inj.tsdb_client, start_sec, end_sec, cluster_id)
                    cluster_types.add(str(cluster_type))
                response.append(TableResponse(rows=[[', '.join(cluster_types)]], columns=[{"text": " ", "type": "string"}]))
            return response
        selected_region = target.payload['region']  # region relevant for all panels below
        if active_region != selected_region:  # region change via drop-down list
            logger.debug('Active region was %s, selected region is %s now', active_region, selected_region)
            active_region = selected_region
            inj.reinitialize(active_region)
        if target_panel == PanelType.INSTANCEINFO:  # ec2 instance type panel
            instance_type: str = target.payload["instance_type"]
            instance_type = instance_type.replace('\\', '')  # Sometimes flaky dot encoding by Grafana
            if inj.platform is SupportedPlatforms.AWS_EMR:
                instance_info: Dict[str, str] = inj.calc.ec2_emr_pricing.get_instance_info(instance_type)
                ec2_cost: float = inj.calc.ec2_emr_pricing.get_ec2_price(instance_type)
                emr_cost: float = inj.calc.ec2_emr_pricing.get_emr_price(instance_type)
                response.append(GrafanaTables.get_emr_inst_info_table(instance_info, ec2_cost, emr_cost))
            elif inj.platform is SupportedPlatforms.AWS_DBX:
                instance_info: Dict[str, str] = inj.calc.get_instance_info(instance_type)
                dbu_basic: Tuple[float, float] = inj.calc.get_dbu_info(instance_type, DbxClusterType.JOB_BASIC, query.get_plan())
                dbu_photon: Tuple[float, float] = inj.calc.get_dbu_info(instance_type, DbxClusterType.JOB_PHOTON, query.get_plan())
                ec2_cost: float = inj.calc.get_ec2_price(instance_type)
                response.append(GrafanaTables.get_dbu_inst_info_table(instance_info, ec2_cost, dbu_basic, dbu_photon))
            return response
        if target_panel == PanelType.ACTIVE:  # active resources panel
            (nodes_up, cpu_cores, total_ram, total_disk) = ClusterUtils.get_active_resources(inj, start_sec)
            response.append(GrafanaTables.get_resource_table(nodes_up, cpu_cores, total_ram, total_disk))
            return response
        if target_panel == PanelType.DBXCOST:  # dbx cluster cost panel
            cost_items = DbxUtils.estimate_costs(start_sec, end_sec, query.get_cluster_var(), query.get_plan(), inj)
            response.append(GrafanaTables.get_cost_table(cost_items))
            return response
        if target_panel == PanelType.CLUSTERLIST:  # cluster list panels
            cost_list: List[CostMap] = []
            utilization_list: List[Tuple[MaxAvg, MaxAvg]] = []
            if activated_platform is SupportedPlatforms.AWS_EMR:
                cluster_list: List[DescribedEmrCluster] = list(EmrUtils.get_cluster_descriptions(inj, start_string, end_string))
                inj.tsdb_client.fill_api_gaps(cluster_list, start_sec, end_sec, activated_platform)  # fill potential API gaps
                for cluster in cluster_list:
                    if 'skip_costs' not in target.payload:
                        cluster_cost = EmrUtils.check_cost_cache(cluster.Id, inj)
                        cost_list.append(cluster_cost)
                    utilizations: Tuple[MaxAvg, MaxAvg] = inj.tsdb_client.get_cluster_utilizations(cluster)
                    utilization_list.append(utilizations)
                if 'skip_costs' not in target.payload:
                    response.append(GrafanaTables.get_emr_clist_table(cluster_list, utilization_list, cost_list))
                else:
                    response.append(GrafanaTables.get_emr_clist_table(cluster_list, utilization_list))
            elif activated_platform is SupportedPlatforms.AWS_DBX:
                cluster_details: Iterator[ClusterDetails] = inj.client_dbx.clusters.list()
                relevant_details: List[DbxCluster] = DbxUtils.filter_clusters(cluster_details, start_sec, end_sec)
                inj.tsdb_client.fill_api_gaps(relevant_details, start_sec, end_sec, activated_platform)  # fill potential API gaps
                for cluster_detail in relevant_details:
                    cost_list.append(DbxUtils.estimate_costs(start_sec, end_sec, cluster_detail.Id, query.get_plan(), inj))
                    utilization_list.append(inj.tsdb_client.get_cluster_utilizations(cluster_detail))
                response.append(GrafanaTables.get_dbx_clist_table(relevant_details, cost_list, utilization_list))
            return response
        if target_panel in (PanelType.APPLIST, PanelType.COMPCOSTS, PanelType.COMPUTIL):  # general overview boards
            app_cluster_ids: List[IdPair] = inj.tsdb_client.get_app_cluster_ids(start_sec, end_sec)
            rel_cluster_ids: Set[str] = {pair[1] for pair in app_cluster_ids}
            if target_panel == PanelType.COMPCOSTS:  # overall compute costs panel
                if activated_platform is SupportedPlatforms.AWS_EMR:
                    response.append(GrafanaTables.get_cost_table(EmrUtils.get_clusters_costs(rel_cluster_ids, inj)))
                else:
                    response.append(GrafanaTables.get_cost_table(DbxUtils.estimate_set_costs(start_sec, end_sec, rel_cluster_ids, query.get_plan(), inj)))
                return response
            if target_panel == PanelType.COMPUTIL:  # overall compute utilization panel
                total_util, tracked_clusters = ClusterUtils.get_total_utilization(rel_cluster_ids, start_sec, end_sec, inj)
                response.append(GrafanaTables.get_totalutil_table(total_util, tracked_clusters))
                return response
            # app list panel
            if activated_platform is SupportedPlatforms.AWS_EMR:
                cluster_descs, app_times, calculated_prices = EmrUtils.get_app_list(app_cluster_ids, start_sec, end_sec, inj)
                response.append(GrafanaTables.get_app_overview(app_cluster_ids, calculated_prices, cluster_descs, app_times))
            else:
                job_clusters: List[IdPair] = []
                for pair in app_cluster_ids:
                    if DbxUtils.get_dbx_cluster_info(inj.tsdb_client, start_sec, end_sec, pair[1], 'job_cluster') == 'true':
                        job_clusters.append(pair)
                cluster_descs, app_times, calculated_prices = DbxUtils.get_app_list(job_clusters, start_sec, end_sec, query.get_plan(), inj)
                response.append(GrafanaTables.get_app_overview(job_clusters, calculated_prices, cluster_descs, app_times, True))
            return response
        # cluster-specific panels
        cluster_data: ClusterData = ClusterData(**target.payload)
        cluster_id = cluster_data.cluster_id
        if cluster_id == '':
            return response
        if target_panel in (PanelType.BREAKDOWN, PanelType.APPCOST):  # relevant for Dbx & EMR
            calc_prices: CostMap = {}
            if activated_platform == SupportedPlatforms.AWS_DBX:
                calc_prices = DbxUtils.estimate_costs(start_sec, end_sec, cluster_id, query.get_plan(), inj)
            elif activated_platform == SupportedPlatforms.AWS_EMR:
                calc_prices = EmrUtils.get_cluster_costs(cluster_id, inj)
            if target_panel == PanelType.BREAKDOWN:  # cluster cost panel
                response.append(GrafanaTables.get_cost_table(calc_prices))
            elif target_panel == PanelType.APPCOST:  # application cost panel
                app_id = target.payload['app_id']
                cluster_sec = inj.tsdb_client.get_consumed_time(cluster_id, start_sec, end_sec, QueryType.CLUSTER)
                app_ms = inj.tsdb_client.get_consumed_time(app_id, start_sec, end_sec, QueryType.APP)
                response.append(GrafanaTables.get_app_table([(app_id, cluster_id)], [calc_prices], [cluster_sec], [app_ms]))
            return response
    except Exception:  # all uncaught exceptions (client errors) in helper methods
        logger.exception('Uncaught exception in main loop occurred')
    return response


"""
    Optional simpod endpoints.
    See https://grafana.com/grafana/plugins/simpod-json-datasource
"""


@app.post("/variable")
def return_variable(query: VariableQuery, inj: Inject = Depends(get_dependencies)):
    """Endpoint for variable call from Grafana, returns a list of cluster ids."""
    global active_region
    selected_region = query.payload['region']
    created_after = parse(query.range['from'])
    created_before = parse(query.range['to'])
    payload = []
    kwargs = {'CreatedAfter': created_after, 'CreatedBefore': created_before}
    if active_region != selected_region:  # region change via drop-down list
        logger.debug('Active region was %s, selected region is %s now', active_region, selected_region)
        active_region = selected_region
        inj.reinitialize(active_region)
    cluster_ids = EmrUtils.get_cluster_ids(inj.client_emr, kwargs)
    for cluster_id in cluster_ids:
        payload.append({"__text": cluster_id})
    return payload


@app.post("/tag-keys")
def return_tag_keys():
    """Endpoint for returning tag keys for ad hoc filters."""
    pass


@app.post("/tag-values")
def return_tag_values():
    """Endpoint for returning tag values for ad hoc filters."""
    pass


@app.post("/test", status_code=status.HTTP_200_OK)
def test_connection_expl(query_arg: Dict):
    """Custom test endpoint."""
    return query_arg
