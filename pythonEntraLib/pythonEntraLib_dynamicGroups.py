"""
MIT License

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

import json
import requests
import re
import urllib

###########################################################################################
## THIS IS NOT IN USE

class DynamicGroups:
    ## Notes: these haven't been fully tested 
    ##     2: there is a limit of 500 dynamic groups in entra :-(
    def __init__(self, client):
        self.client = client

    def __create__(self, dyn_group_name, app_group_id, additional_group_names):
        next_uri = f"{self.client.graph_api_url}/v1.0/groups"
        encoded_dyn_group_name = urllib.parse.quote(dyn_group_name)
        check_uri = f"{next_uri}?$filter=displayName eq '{encoded_dyn_group_name}'"
        response = requests.get(check_uri, headers=self.client.headers)
        if response.status_code == 200:
            groups = response.json().get('value', [])
            if groups:
                self.client.logger.debug(f"{self.__class__.__name__}.{self.client.__caller_info__()}({dyn_group_name}) already exists.")
                return groups[0]  # Return the existing group
            else:
                group_ids_list = [ app_group_id]
                for additional_group_name in additional_group_names:
                    additional_group_id = self.client.Groups.get_id(additional_group_name)
                    if additional_group_id:
                        group_ids_list.append(additional_group_id)
                group_ids_str = ', '.join([f"'{gid}'" for gid in group_ids_list])
                updated_membership_rule = f"user.memberOf -any (group.objectId -in [{group_ids_str}])"
                self.client.logger.debug(f"{self.__class__.__name__}.{self.client.__caller_info__()}({dyn_group_name}) Creating new group.")
                payload = {
                    "displayName": dyn_group_name,
                    "mailEnabled": False,
                    "mailNickname": self.__clean_email_addrs__(dyn_group_name),
                    "securityEnabled": True,
                    "groupTypes": ["DynamicMembership"],
                    "membershipRule": updated_membership_rule,
                    "membershipRuleProcessingState": "On"
                }
                # print(payload)
                create_response = requests.post(next_uri, headers=self.client.headers, json=payload)
                if create_response.status_code == 201:
                    self.client.logger.debug(f"{self.__class__.__name__}.{self.client.__caller_info__()}({dyn_group_name}) SUCCESS_GROUP_DYNAMIC_CREATE")
                    return create_response.json()
                else:
                    self.client.logger.warning(f"{self.__class__.__name__}.{self.client.__caller_info__()}({dyn_group_name}) FAILURE_GROUP_DYNAMIC_CREATE {create_response.text}")
                    return None
        else:
            self.client.logger.warning(f"{self.__class__.__name__}.{self.client.__caller_info__()}({dyn_group_name}) FAILURE_GROUP_DYNAMIC_CREATE Failed to check if group exists: {response.text}")
            return None

    def create(self, dyn_group_name, app_group_name, additional_group_names):
        app_group_info = self.client.Groups.get_id(app_group_name)
        if app_group_info is None:
            self.client.logger.warning(f"{self.__class__.__name__}.{self.client.__caller_info__()}({dyn_group_name}) FAILURE_GROUP_DYNAMIC_CREATE app_group_name must exist prior")
            return None
        entra_group_info = self.client.Groups.get_info(dyn_group_name)
        if entra_group_info is None:
            self.client.logger.info(f"{self.__class__.__name__}.{self.client.__caller_info__()}({dyn_group_name}) Creating dynamic entra group")
            if not self.__create__(dyn_group_name, app_group_info['id'], additional_group_names):
                self.client.logger.warning(f"{self.__class__.__name__}.{self.client.__caller_info__()}({dyn_group_name}) FAILURE_GROUP_DYNAMIC_CREATE")
                return None
        else:
            self.client.logger.debug(f"{self.__class__.__name__}.{self.client.__caller_info__()}({dyn_group_name}) Entra dynamic group exists")
        return dyn_group_name

    def add_group(self, dyn_group_id, group_id):
        # Step 1: Get the current group details
        group_details_url = f"{self.client.graph_api_url}/v1.0/groups/{dyn_group_id}"
        response = requests.get(group_details_url, headers=self.client.headers)
        if response.status_code != 200:
            self.client.logger.warning(f"{self.__class__.__name__}.{self.client.__caller_info__()}({dyn_group_id}) FAILURE_GET_GROUP_DETAILS {response.text}")
            return None
        group_info = response.json()
        current_membership_rule = group_info.get("membershipRule", "")
        # Step 2: Extract the current list of group IDs from the membership rule
        group_ids = re.findall(r"group\.objectId -in \[(.*?)\]", current_membership_rule)
        if group_ids:
            group_ids_list = group_ids[0].replace("'", "").split(", ")
        else:
            group_ids_list = []
        # Step 3: Add the new group_id to the list if it's not already present
        if group_id in group_ids_list:
            self.client.logger.debug(f"{self.__class__.__name__}.{self.client.__caller_info__()}({dyn_group_id}) Group {group_id} already present in membership rule")
            return True
        else:
            group_ids_list.append(group_id)
        # Step 4: Construct the updated membership rule
        group_ids_str = ', '.join([f"'{gid}'" for gid in group_ids_list])
        updated_membership_rule = f"user.memberOf -any (group.objectId -in [{group_ids_str}])"
        payload = { "membershipRule": updated_membership_rule, }
        update_url = f"{self.client.graph_api_url}/v1.0/groups/{dyn_group_id}"
        update_response = requests.patch(update_url, headers=self.client.headers, data=json.dumps(payload))
        if update_response.status_code != 204:
            self.client.logger.warning(f"{self.__class__.__name__}.{self.client.__caller_info__()}({dyn_group_id}) FAILURE_UPDATE_MEMBERSHIP_RULE {update_response.text}")
            return None
        self.client.logger.debug(f"{self.__class__.__name__}.{self.client.__caller_info__()}({dyn_group_id}) SUCCESS_UPDATE_MEMBERSHIP_RULE")
        return True
###########################################################################################
#################################### DYNAMIC GROUPS #######################################
###########################################################################################
