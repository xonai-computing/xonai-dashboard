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

"""Standalone script for installation."""
import os
from os import path, environ
import json
import gzip
from typing import Set
import argparse
import requests

ACTIVATED_PLATFORM = 'AWS_EMR'
configured_platform = environ.get('ACTIVE_PLATFORM')
if configured_platform == 'AWS_DBX':
    ACTIVATED_PLATFORM = 'AWS_DBX'
resource_dir = path.join(path.dirname(path.abspath(__file__)), 'resources')
URL_BASE = 'https://pricing.us-east-1.amazonaws.com'  # see https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/using-ppslong.html
AWS_REGIONS = {'us-east-2', 'us-east-1', 'us-west-1', 'us-west-2', 'af-south-1', 'ap-east-1', 'ap-south-2', 'ap-southeast-3', 'ap-southeast-4',
               'ap-south-1', 'ap-northeast-3', 'ap-northeast-2', 'ap-southeast-1', 'ap-southeast-2', 'ap-northeast-1', 'ca-central-1', 'eu-central-1',
               'eu-west-1', 'eu-west-2', 'eu-south-1', 'eu-west-3', 'eu-south-2', 'eu-north-1', 'eu-central-2', 'il-central-1', 'me-south-1',
               'me-central-1', 'sa-east-1'}
# based on https://docs.aws.amazon.com/general/latest/gr/emr.html


def fetch_resources(regions: Set[str] = AWS_REGIONS) -> None:
    """Method for calling APIs and writing their cost records to the local disks."""
    region_index = requests.get(URL_BASE + '/offers/v1.0/aws/index.json').json()
    aws_regions_response = requests.get(URL_BASE + region_index['offers']['ElasticMapReduce']['currentRegionIndexUrl']).json()
    aws_region_urls_json = aws_regions_response['regions']
    ec2_regions_response = requests.get(URL_BASE + region_index['offers']['AmazonEC2']['currentRegionIndexUrl']).json()
    ec2_region_urls_json = ec2_regions_response['regions']
    ec2_dir = os.path.join(resource_dir, 'ec2')
    emr_dir = os.path.join(resource_dir, 'emr')
    for aws_region in regions:
        print(f'--------------- {aws_region}')
        if ACTIVATED_PLATFORM == 'AWS_EMR':
            print(f'Writing EMR resource file for region {aws_region}')
            emr_region_url = URL_BASE + aws_region_urls_json[aws_region]['currentVersionUrl']
            region_info_emr = json.dumps(requests.get(emr_region_url).json())
            emr_file = os.path.join(emr_dir, aws_region + '.json.gz')
            with gzip.open(emr_file, "wb") as f:
                f.write(region_info_emr.encode())
            print(f'Completed writing EMR file for region {aws_region} to {emr_file}')
        print(f'Writing EC2 resource file for region {aws_region} (more time-consuming than its EMR counterpart)')
        ec2_region_url = URL_BASE + ec2_region_urls_json[aws_region]['currentVersionUrl']
        region_info_ec2 = json.dumps(requests.get(ec2_region_url).json())
        ec2_file = os.path.join(ec2_dir, aws_region + '.json.gz')
        with gzip.open(ec2_file, 'wb') as f:
            f.write(region_info_ec2.encode())
        print(f'Completed writing EC2 file for region {aws_region} to {ec2_file}')
        print('---------------')


def main() -> None:
    parser = argparse.ArgumentParser(description="Standalone script for fetching cost info")
    parser.add_argument("regions", nargs='?', help="comma separated list of AWS regions", default='*')
    args = parser.parse_args()
    region_arg: str = args.regions.strip()
    relevant_regions: Set[str] = set()
    if region_arg in ('*', ''):  # traverse all regions by default
        relevant_regions = AWS_REGIONS
    else:
        supplied_strings = region_arg.split(',')
        for supplied_string in supplied_strings:
            if supplied_string in AWS_REGIONS:
                relevant_regions.add(supplied_string)
            else:
                print(f'Supplied region {supplied_string} not a known region, skipping')
    if len(relevant_regions) == 0:
        print(f'No valid region supplied ({region_arg}), exiting')
    print(f'Running fetch_cost_info.py for platform {ACTIVATED_PLATFORM}, downloading resources for regions {relevant_regions}')
    fetch_resources(relevant_regions)
    print(f'Finished downloading resources for the following regions: {relevant_regions}')


# standalone script, independent of other module functionality
if __name__ == '__main__':
    main()
