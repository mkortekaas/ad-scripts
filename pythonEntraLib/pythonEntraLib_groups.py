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

import requests
import urllib
import os
from concurrent.futures import ThreadPoolExecutor

class Groups:
    def __init__(self, client):
        self.client           = client
        self.cache            = {}
        self.groups_cache_dir = None
        self.groups_members_cache_dir = None
        if (self.client.cache_dir is not None):
            self.groups_cache_dir         = self.client.__mkdir_p__(f'{self.client.cache_dir}/entra_groups')
            self.groups_members_cache_dir = self.client.__mkdir_p__(f'{self.client.cache_dir}/entra_groups_members')

    def get_details(self, group, FORCE_NEW=False):
        return self.client.__get_details__(group, "groups", self.cache, self.groups_cache_dir, "displayName", FORCE_NEW)
    
    def get_all(self, STOP_LIMIT=None):
        return self.client.__get_all__("groups", self.cache, self.groups_cache_dir, 'displayName', STOP_LIMIT)
    
    def get_all_members(self, STOP_LIMIT=None):
        if self.groups_cache_dir is None:
            self.logger.warning(f"{self.__class__.__name__}.{self.client.__caller_info__()}() requires cache to be set - otherwise no point")
            return False

        self.client.logger.debug(f"{self.__class__.__name__}.{self.client.__caller_info__()}() loading all groups")
        groups = self.get_all(STOP_LIMIT)
        if groups is None:
            return None
        # do this in parallel instead of a "for group in groups" 1 by 1
        group_ids = [group['id'] for group in groups]
        with ThreadPoolExecutor(max_workers=5) as executor:
            list(executor.map(self.get_members, group_ids))
        return True
    
    def get_id(self, group_name, FORCE_NEW=False):
        group = self.get_details(group_name, FORCE_NEW)
        if group:
            return group['id']
        return None
    
    def is_user_in_group(self, group, user_oid):
        if group is None:
            return False
        if self.client.__is_valid_uuid__(group):
            group_id = group
        else:
            group_id = self.get_id(group)
        if group_id is None:
            return False
        members = self.get_members(group_id)
        if members is None:
            return False
        return user_oid in members
    
    def get_members(self, group, FORCE_NEW=False):
        if group is None:
            return None
        if self.client.__is_valid_uuid__(group):
            group_id = group
        else:
            group_id = self.get_id(group)
        members = []
        if self.groups_cache_dir is not None:
            group_members_filename = f"{self.groups_members_cache_dir}/{urllib.parse.quote(group_id, safe='')}.json"
            if os.path.exists(group_members_filename):
                if not FORCE_NEW:
                    return self.client.__read_from_cache__(group_members_filename)
                os.remove(group_members_filename)
        next_uri = f"{self.client.graph_api_url}/v1.0/groups/{group_id}/members"
        while next_uri:
            response = requests.get(next_uri, headers=self.client.headers)
            if response.status_code == 200:
                data = response.json()
                members.extend([member['id'] for member in data.get('value', [])])
                next_uri = data.get('@odata.nextLink')
            else:
                self.client.logger.warning(f"{self.__class__.__name__}.{self.client.__caller_info__()}() Failed to get members for group '{group_id}': {response.text}")
                return []
        if self.groups_cache_dir is not None:
            self.client.__write_to_cache__(group_members_filename, members)
        return members
    
    def __add_users__(self, group_id, membership_list):
        def chunks(lst, n):
            """Yield successive n-sized chunks from lst."""
            for i in range(0, len(lst), n):
                yield lst[i:i + n]

        if membership_list:
            total_added = 0
            for chunk in chunks(membership_list, 19):
                next_uri = f"{self.client.graph_api_url}/v1.0/groups/{group_id}"
                payload = {"members@odata.bind": chunk}
                response = requests.patch(next_uri, headers=self.client.headers, json=payload)
                if response.status_code == 204:
                    self.client.logger.debug(f"{self.__class__.__name__}.{self.client.__caller_info__()}({group_id}) added {len(chunk)} users successfully.")
                    total_added += len(chunk)
                else:
                    # logger but keep going)
                    self.client.logger.warning(f"{self.__class__.__name__}.{self.client.__caller_info__()}({group_id}) FAILURE_GROUP_USER failed to add {len(chunk)} users: {response.text}")
            return total_added
        return 0
    
    def add_users(self, group_id, user_oids, current_members=None):
        if current_members is None:
            current_members = self.get_members(group_id)
            if current_members is None:
                current_members = []
        if isinstance(user_oids, str):
            user_oids = [user_oids]
        membership_list = []
        for user_oid in user_oids:
            if user_oid not in current_members:
                membership_list.append(f"{self.client.graph_api_url}/v1.0/directoryObjects/{user_oid}")
        if len(membership_list) > 0:
            return self.__add_users__(group_id, membership_list)
        else:
            self.client.logger.debug(f"{self.__class__.__name__}.{self.client.__caller_info__()}({group_id}) No new users to add to group")
        return 0
    
    def remove_users(self, group_id, user_oids):
        ## this works differently than the add - you can only remove one at a time
        current_members = self.get_members(group_id)
        removed_users   = False
        for user_oid in user_oids:
            if user_oid in current_members:
                next_uri = f"{self.client.graph_api_url}/v1.0/groups/{group_id}/members/{user_oid}/$ref"
                response = requests.delete(next_uri, headers=self.client.headers)
                if response.status_code == 204:
                    self.client.logger.debug(f"{self.__class__.__name__}.{self.client.__caller_info__()}({group_id}) removed {user_oid} user successfully")
                    removed_users = True
                else:
                    self.client.logger.warning(f"{self.__class__.__name__}.{self.client.__caller_info__()}({group_id}) FAILURE_GROUP_USER failed to remove {user_oid} user: {response.text}")
        if not removed_users:
            self.client.logger.debug(f"{self.__class__.__name__}.{self.client.__caller_info__()}({group_id}) No users to remove")
        return True
    
    def owners_fetch(self, group_id):
        url = f"{self.client.graph_api_url}/v1.0/groups/{group_id}/owners"
        response = requests.get(url, headers=self.client.headers)
        if response.status_code != 200:
            self.client.logger.info(f"{self.__class__.__name__}.{self.client.__caller_info__()}({group_id}) No group owners")
            return None
        return response.json()
    def owners_fetch_oids(self, group_id):
        owners = self.owners_fetch(group_id)
        if owners is None:
            return None
        return [owner['id'] for owner in owners['value']]
    
    def owners_add(self, group_id, user_oids):
        group_owners = self.owners_fetch(group_id)
        if user_oids:
            for user_oid in user_oids:
                if any(owner['id'] == user_oid for owner in group_owners['value']):
                    self.client.logger.debug(f"{self.__class__.__name__}.{self.client.__caller_info__()}({group_id}) {user_oid} is already an owner")
                    continue
                url = f"{self.client.graph_api_url}/v1.0/groups/{group_id}/owners/$ref"
                payload = { "@odata.id": f"{self.client.graph_api_url}/v1.0/users/{user_oid}" }
                response = requests.post(url, headers=self.client.headers, json=payload)
                if response.status_code != 204:
                    self.client.logger.warning(f"{self.__class__.__name__}.{self.client.__caller_info__()}({group_id}) {user_oid} Error adding owner to group")
                else:
                    self.client.logger.info(f"{self.__class__.__name__}.{self.client.__caller_info__()}({group_id}) {user_oid} is now a group owner")
        return True
    
    def owners_remove(self, group_id, user_oids):
        group_owners = self.owners_fetch(group_id)
        if user_oids:
            for user_oid in user_oids:
                if any(owner['id'] == user_oid for owner in group_owners['value']):
                    # DELETE https://graph.microsoft.com/v1.0/groups/{id}/owners/{id}/$ref 
                    url = f"{self.client.graph_api_url}/v1.0/groups/{group_id}/owners/{user_oid}/$ref"
                    response = requests.delete(url, headers=self.client.headers)
                    if response.status_code != 204: 
                        self.client.logger.warning(f"{self.__class__.__name__}.{self.client.__caller_info__()}({group_id}) {user_oid} Error removing owner from group")
                    else:
                        self.client.logger.info(f"{self.__class__.__name__}.{self.client.__caller_info__()}({group_id}) {user_oid} removed as group owner")
        return True
    
    def update_name(self, group_id, modified_group_name):
        url = f"{self.client.graph_api_url}/v1.0/groups/{group_id}"
        payload = { "displayName": modified_group_name }
        response = requests.patch(url, headers=self.client.headers, json=payload)
        if response.status_code != 204:
            self.client.logger.warning(f"{self.__class__.__name__}.{self.client.__caller_info__()}({group_id})({modified_group_name}) Error updating group name response: ({response.text})")
            return False
        self.client.logger.info(f"{self.__class__.__name__}.{self.client.__caller_info__()}({group_id})({modified_group_name}) Updated group name)")
        return True

    def get_prefix(self, groups_prefix):
        limit = 250
        url = f"{self.client.graph_api_url}/v1.0/groups?$filter=startswith(displayName, '{groups_prefix}')&$top={limit}"
        response = requests.get( url, headers=self.client.headers)
        if response.status_code == 200:
            return  response.json()['value']
        return None
                    
    def delete(self, group_name, group_id):
        url = f"{self.client.graph_api_url}/v1.0/groups/{group_id}"
        self.client.logger.info (f"Deleting group ({group_name}) ({group_id})")
        response = requests.delete( url, headers=self.client.headers)
        if response.status_code != 204:
            self.client.logger.warning(f"Error deleting group ({group_name}) ({group_id}) response code: {response.status_code}")
            return False    
        return True
    
    def __create__(self, group_name):
        next_uri = f"{self.client.graph_api_url}/v1.0/groups"
        encoded_group_name = urllib.parse.quote(group_name)
        check_uri = f"{next_uri}?$filter=displayName eq '{encoded_group_name}'"
        response = requests.get(check_uri, headers=self.client.headers)

        if response.status_code == 200:
            groups = response.json().get('value', [])
            if groups:
                self.client.logger.debug(f"{self.__class__.__name__}.{self.client.__caller_info__()}({group_name}) already exists.")
                return groups[0]  # Return the existing group
            else:
                self.client.logger.debug(f"{self.__class__.__name__}.{self.client.__caller_info__()}({group_name}) Creating new group.")
                # Create the group
                payload = {
                    "displayName": group_name,
                    "mailEnabled": False,
                    "mailNickname": self.client.__clean_email_addrs__(group_name),
                    "securityEnabled": True,
                    # "group_types": []   ## this could be "Unified" - but not sure what we need here
                }
                create_response = requests.post(next_uri, headers=self.client.headers, json=payload)
                if create_response.status_code == 201:
                    self.client.logger.debug(f"{self.__class__.__name__}.{self.client.__caller_info__()}({group_name}) created successfully.")
                    return create_response.json()
                else:
                    self.client.logger.warning(f"{self.__class__.__name__}.{self.client.__caller_info__()}({group_name}) FAILURE_GROUP_CREATE {create_response.text}")
                    return None
        else:
            self.client.logger.warning(f"{self.__class__.__name__}.{self.client.__caller_info__()}({group_name}) FAILURE_GROUP_CREATE Failed to check if group exists: {response.text}")
            return None
        
    def create(self, group_name):
        entra_group_info = self.get_details(group_name)
        if entra_group_info is None:
            self.client.logger.info(f"{self.__class__.__name__}.{self.client.__caller_info__()}({group_name}) Creating entra group")
            if not self.__create__(group_name):
                self.client.logger.warning(f"{self.__class__.__name__}.{self.client.__caller_info__()}({group_name}) FAILURE_GROUP_CREATE")
                return None
        else:
            self.client.logger.debug(f"{self.__class__.__name__}.{self.client.__caller_info__()}({group_name}) Entra group exists")
        return group_name
    
