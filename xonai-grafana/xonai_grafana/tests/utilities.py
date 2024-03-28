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

"""Module containing test functionality."""
from datetime import datetime
from dateutil.tz import tzlocal


class TestUtils:
    """Wrapper for literals that are needed across different test cases."""
    cost_info = {
        "TOTAL": 1.0,
        "CORE.EC2": 2.0,
        "CORE.EMR": 3.0,
        "MASTER.EC2": 4.0,
        "MASTER.EMR": 5.0,
        "MASTER.EBS": 6.0,
        "CORE.EBS": 7.0
    }

    query_result = [
        {
            "metric": {
                "agent": "driver",
                "app_id": "application_0001",
                "cluster_id": "j-_____________",
                "instance": "ip-xyz",
                "job": "spark_scraper",
                "ns": "JVMCPU"
            },
            "value": [
                1697879951.365,
                "1696431319000"
            ]
        }
    ]

    active_cluster = {
        "Id": "j-_____________",
        "Name": "Cluster Name)",
        "Status": {
            "State": "RUNNING",
            "StateChangeReason": {
                "Message": "Running step"
            },
            "Timeline": {
                "CreationDateTime": datetime(2023, 7, 27, 15, 58, 25, 798000, tzinfo=tzlocal()),
                "ReadyDateTime": datetime(2023, 7, 27, 16, 3, 23, 426000, tzinfo=tzlocal())
            }
        },
        "NormalizedInstanceHours": 0,
        "ClusterArn": "arn:aws:elasticmapreduce:..."
    }

    sku_info_emr = {
        "products": {
            "sku1": {
                "sku": "sku1",
                "attributes": {
                    "instanceType": "instance_1",
                    "softwareType": "EMR"
                }
            },
            "sku2": {
                "sku": "sku2",
                "attributes": {
                    "instanceType": "instance_2",
                    "softwareType": "EMR"
                }
            },
            "sku3": {
                "sku": "sku3",
                "attributes": {
                    "instanceType": "instance_3",
                    "softwareType": "EMR"
                }
            }
        },
        "terms": {
            "OnDemand": {
                "sku1": {
                    "sku1.sku1": {
                        "priceDimensions": {
                            "sku1.sku1.sku1": {
                                "pricePerUnit": {
                                    "USD": "0.1"
                                },
                            }
                        },
                    }
                },
                "sku2": {
                    "sku2.sku2": {
                        "priceDimensions": {
                            "sku2.sku2.sku2": {
                                "pricePerUnit": {
                                    "USD": "0.2"
                                },
                            }
                        },
                    }
                },
                "sku3": {
                    "sku3.sku3": {
                        "priceDimensions": {
                            "sku3.sku3.sku3": {
                                "pricePerUnit": {
                                    "USD": "0.3"
                                },
                            }
                        },
                    }
                }
            }
        }
    }

    sku_info_ec2 = {
        "products": {
            "sku1": {
                "sku": "sku1",
                "attributes": {
                    "instanceType": "instance_1",
                    "tenancy": "Shared",
                    "operatingSystem": "Linux",
                    "operation": "RunInstances",
                    "capacitystatus": "Used",
                }
            },
            "sku2": {
                "sku": "sku2",
                "attributes": {
                    "instanceType": "instance_2",
                    "tenancy": "Shared",
                    "operatingSystem": "Linux",
                    "operation": "RunInstances",
                    "capacitystatus": "Used",
                }
            },
        },
        "terms": {
            "OnDemand": {
                "sku1": {
                    "sku1.sku1": {
                        "priceDimensions": {
                            "sku1.sku1.sku1": {
                                "pricePerUnit": {
                                    "USD": "1.0"
                                },
                            }
                        },
                    }
                },
                "sku2": {
                    "sku2.sku2": {
                        "priceDimensions": {
                            "sku2.sku2.sku2": {
                                "pricePerUnit": {
                                    "USD": "2.0"
                                },
                            }
                        },
                    }
                }
            }
        }
    }
