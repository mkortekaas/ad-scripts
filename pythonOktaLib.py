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

from collections import deque
from datetime import datetime, timedelta
import time
import logging
import requests
import json
import os
import sys
import math
import glob
import re
import gzip

###################################################################################
class OktaInfo:
    def __init__ (self, CACHE_DIR, OKTA_DOMAIN=None, OKTA_TOKEN=None, GLOBAL_RATE_LIMIT=250, FLUSH=False):
        ## make sure that other modules are calling with same logger name
        self.logger                  = logging.getLogger('__COMMONLOGGER__')
        self.OKTA_DOMAIN             = OKTA_DOMAIN
        self.GLOBAL_RATE_LIMIT       = GLOBAL_RATE_LIMIT   # rate limits are fairly low anything from 50/min to 100/min per token
        self.total_apps_to_fetch     = 999999
        self.LIMIT_APPS              = 200
        self.LIMIT_USERS             = 500
        self.LIMIT_GROUPS            = 200
        self.CACHE_DIR               = CACHE_DIR
        self.cache_user              = {}
        self.cache_groups            = {}
        self.cache_groups_users      = {}
        self.cache_apps              = {}

        if FLUSH:
            self.flush()

        self.__mkdirs__()

        ## OKTA_TOKEN can come in a few ways depending how we are called
        self.last_api_index          = 0
        self.api_call_timestamps     = []
        if (type(OKTA_TOKEN) is str):
            self.OKTA_TOKEN          = [ OKTA_TOKEN ]
            self.api_call_timestamps.append(deque()) # Initialize a queue to track API call timestamps
        elif (type(OKTA_TOKEN) is list):
            self.OKTA_TOKEN          = OKTA_TOKEN
            for i in range(len(OKTA_TOKEN)):
                self.api_call_timestamps.append(deque()) # Initialize a queue to track API call timestamps
        else:
            self.OKTA_TOKEN          = None
            self.api_call_timestamps = None        

    def __mkdirs__(self):
        if self.CACHE_DIR is None:
            return
        self.dir_app_groups          = self.__mkdir_p__(f"{self.CACHE_DIR}/okta_app_groups")
        self.dir_app_info            = self.__mkdir_p__(f"{self.CACHE_DIR}/okta_app_info")
        self.dir_app_users           = self.__mkdir_p__(f"{self.CACHE_DIR}/okta_app_users")
        self.dir_groups              = self.__mkdir_p__(f"{self.CACHE_DIR}/okta_groups")
        self.dir_groups_users        = self.__mkdir_p__(f"{self.CACHE_DIR}/okta_groups_users")
        self.dir_users               = self.__mkdir_p__(f"{self.CACHE_DIR}/okta_users")
        self.dir_users_apps          = self.__mkdir_p__(f"{self.CACHE_DIR}/okta_users_apps")
        self.dir_syslogs             = self.__mkdir_p__(f"{self.CACHE_DIR}/okta_syslogs")

    def __mkdir_p__(self, path):
        if path is not None:
            os.makedirs(path, exist_ok=True)
        return path

    def flush(self):
        self.logger.info(f"FLUSHING OKTA CACHE in ({self.CACHE_DIR})")
        os.system(f"rm -rf {self.CACHE_DIR}/okta_*")

    def __get_headers__(self):
        ## This is called for getting headers and is a good place to check rate limits and wait here
        ##    If we have multiple tokens we will rotate through them here to speed up responses
        if self.api_call_timestamps is None:
            self.logger.error(f"API Token is not set - should not have gotten here. Exiting.")
            sys.exit(1)
        if len(self.api_call_timestamps) > 1:
            self.last_api_index = (self.last_api_index + 1) % len(self.api_call_timestamps)
        current_time = datetime.now()
        self.api_call_timestamps[self.last_api_index].append(current_time)  # Append current timestamp here
        while len(self.api_call_timestamps[self.last_api_index]) >= self.GLOBAL_RATE_LIMIT:
            current_time = datetime.now()
            self.logger.debug(f"RATE_LIMIT_PAUSE: {len(self.api_call_timestamps[self.last_api_index])} / {self.GLOBAL_RATE_LIMIT} / {self.last_api_index} in last minute")
            while self.api_call_timestamps[self.last_api_index] and self.api_call_timestamps[self.last_api_index][self.last_api_index] < current_time - timedelta(seconds=60):
                self.api_call_timestamps[self.last_api_index].popleft()  # Remove timestamps older than 1 minute
            time.sleep(2)

        headers = {
            'Authorization': f'SSWS {self.OKTA_TOKEN[self.last_api_index]}',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }
        return headers
    
    def get_headers(self):
        ## this is just if you want to call the api from outside this class directly you can use the header
        return self.__get_headers__()
       
    def __https_get__(self, url, params=None):
        while True:
            if params is None:
                response = requests.get(url, headers=self.__get_headers__())
            else:
                response = requests.get(url, headers=self.__get_headers__(), params=params)
            if response.status_code == 200:
                return response
            elif response.status_code == 429:
                ## in theory we take care of this with the __get_headers__ function but have found not always perfect
                reset_time = int(response.headers.get('X-Rate-Limit-Reset', time.time() + 60))
                wait_time = reset_time - int(time.time())
                self.logger.warning(f"RATE_LIMIT_EXCEEDED - Waiting for {wait_time} seconds before retrying.")
                time.sleep(wait_time)
            else:
                self.logger.error(f"Failed to retrieve {url}\tStatus code: {response.status_code} ({response.text})")
                return None

    def __fetch_to_cache__(self, url, filename, force=False):
        if os.path.exists(filename):
            if force is True:
                os.remove(filename)  ## this will force a refresh
            else:
                # self.logger.debug(f"-o-o-o- Reading from disk cache: {filename}")
                with open(filename, 'r') as f:
                    json_info = json.load(f)
                    return json_info
        response = self.__https_get__(url)
        if response is None:
            my_json = { "status": "NOT_FOUND" }
        else: 
            my_json = response.json()
        self.logger.debug(f"+o+o+o+ Writing into disk cache: {filename} ({url})")
        with open(filename, 'w') as f:
            json.dump(my_json, f)
        return my_json
        
    def __is_email_address__(self, id):
        # Define a regex pattern for validating email addresses
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return re.match(email_pattern, id) is not None
    
    def __get_user_id_by_email__(self, email):
        url = f'https://{self.OKTA_DOMAIN}/api/v1/users?q={email}'
        response = self.__https_get__(url)
        if response:
            users = response.json()
            if len(users) > 0 and 'id' in users[0]:
                return users[0]['id']
        return None

    def user(self, id, FORCE=False):
        # self.logger.debug(f"Getting user: {id}")
        if self.__is_email_address__(id):
            id = self.__get_user_id_by_email__(id)
            if id is None:
                return None
        if FORCE is False and id in self.cache_user:
            return self.cache_user[id]
        url = f'https://{self.OKTA_DOMAIN}/api/v1/users/{id}'
        filename = f"{self.dir_users}/{id}.json"
        user_info = self.__fetch_to_cache__(url, filename, FORCE)
        self.cache_user[id] = user_info
        return user_info
    # now that we have the id - we can get the apps for this user - for reference
    #   oktaUserGetData(OKTA_DOMAIN, OKTA_TOKEN, 'clients', json_user_data['id'])
    #   oktaUserGetData(OKTA_DOMAIN, OKTA_TOKEN, 'appLinks', json_user_data['id'])
    #   oktaUserGetData(OKTA_DOMAIN, OKTA_TOKEN, 'grants', json_user_data['id'])

    def user_add_to_group(self, user_id, group_id):
        url = f'https://{self.OKTA_DOMAIN}/api/v1/groups/{group_id}/users/{user_id}'
        response = requests.put(url, headers=self.__get_headers__())
        if response.status_code != 204:
            self.logger.warning(f"Failed to add user to group: {url} - response: {response.status_code} / {response.text}")
            return False
        return True
   
    def get_logs(self, id, days_back=15):
        filename = f"{self.dir_syslogs}/{id}.json.gz"
        if os.path.exists(filename):
            with gzip.open(filename, "rt") as f:
                log = json.load(f)
                return log
        now = datetime.now()
        start_date = now - timedelta(days=days_back)
        period = timedelta(days=15)
        all_logs = []
        while start_date < now:
            end_date = start_date + period
            if end_date > now:
                end_date = now
            iso8601_start = start_date.isoformat()
            iso8601_end   = end_date.isoformat()
            query = {
                "filter": f"actor.id eq \"{id}\"",
                "sortOrder": "DESCENDING",
                "since": iso8601_start,
                "until": iso8601_end,
                "limit": 1000
            }
            url = f'https://{self.OKTA_DOMAIN}/api/v1/logs'
            response = self.__hash__get__(url, query)   
            if response is None:
                return None
            logs = response.json()
            all_logs.extend(logs)
            start_date = end_date
        with gzip.open(filename, "wt") as f:
            f.write(json.dumps(all_logs))
        return all_logs
    
    def __fetch_all_sub__(self, my_function, my_cache, my_cache_dir, STOP_LIMIT, url, query, my_list, count):
        while True:
            if count >= STOP_LIMIT:
                break
            self.logger.info(f"========== Fetching {my_function}: {url} ==========")
            response = self.__https_get__(url, query)
            items = response.json()
            my_list.extend(items)
            for item in items:
                filename = f"{my_cache_dir}/{item.get('id')}.json"
                my_cache[item.get('id')] = item
                with open(filename, 'w') as f:
                    json.dump(item, f)

            count += len(items)
            if 'next' in response.links:
                self.logger.debug(f"                          {response.links['next']} ")
                url = response.links['next']['url']
                query = None
            else:
                break
        return my_list

    def __fetch_all__(self, my_function, my_cache, my_cache_dir, STOP_LIMIT):
        count     = 0
        my_list = []
        my_limit  = self.total_apps_to_fetch
        if STOP_LIMIT is not None:
            my_limit = STOP_LIMIT
        json_files = glob.glob(os.path.join(my_cache_dir, '*.json'))
        if (len(json_files) > 0):
            self.logger.debug(f"USING CACHED {my_function}: {len(json_files)}")
            for json_file in json_files:
                if count >= my_limit:
                    break
                with open(json_file, 'r') as f:
                    data = json.load(f)
                    my_list.append(data)
                    my_cache[data.get('id')] = data
                    count += 1
        else:
            url = f'https://{self.OKTA_DOMAIN}/api/v1/{my_function}'
            query = {
                "limit": my_limit
            }
            self.__fetch_all_sub__(my_function, my_cache, my_cache_dir, STOP_LIMIT, url, query, my_list, count)
            if my_function == "users":
                query = {
                    "limit": my_limit,
                    "filter": "status eq \"DEPROVISIONED\""   ## we need to get deprovisioned users as well
                }
                self.__fetch_all_sub__(my_function, my_cache, my_cache_dir, STOP_LIMIT, url, query, my_list, count)
            ## apps DELETED status seems to only return active/inactive apps anyway?
        return my_list
    
    def users_fetch_all(self, STOP_LIMIT=999999):
        return self.__fetch_all__("users", self.cache_user, self.dir_users, STOP_LIMIT)
    
    def user_login_lower_case(self, id):
        ## this is a special case where we are changing the login name to lower case
        ## we need to refetch from the API and then change and then a PUT
        self.logger.debug(f"Getting user: {id}")
        response_json = self.user(id)
        if response_json:
            if response_json['status'] == "DEPROVISIONED": 
                return False

            query = { "strict": "true" }
            payload = { "profile": {} }
            before = { "profile": {} }

            FLIP=False
            if 'profile' in response_json and 'login' in response_json['profile']:
                if any(char.isupper() for char in response_json['profile']['login']):
                    before["profile"]["login"]               = response_json['profile']['login']
                    payload["profile"]["login"]              = response_json['profile']['login'].lower()
                    response_json['profile']['login']        = response_json['profile']['login'].lower()
                    FLIP=True
                    
            if 'profile' in response_json and 'email' in response_json['profile']:
                if any(char.isupper() for char in response_json['profile']['email']):
                    before["profile"]["email"]               = response_json['profile']['email']
                    payload["profile"]["email"]              = response_json['profile']['email'].lower()
                    response_json['profile']['email']        = response_json['profile']['email'].lower()
                    FLIP=True

            if 'profile' in response_json and 'employeeNumber' in response_json['profile']:
                if len(response_json['profile']['employeeNumber']) > 0:
                    if any(char.isupper() for char in response_json['profile']['employeeNumber']):
                        before["profile"]["employeeNumber"]  = response_json['profile']['employeeNumber']
                        payload["profile"]["employeeNumber"] = response_json['profile']['employeeNumber'].lower()
                        response_json['profile']['employeeNumber'] = response_json['profile']['employeeNumber'].lower()
                        FLIP=True

            PROXY=False
            if 'profile' in response_json and 'proxyaddresses' in response_json['profile']:
                if len(response_json['profile']['proxyaddresses']) > 0:
                    new_proxyaddresses = []
                    for proxyaddress in response_json['profile']['proxyaddresses']:
                        if not ":" in proxyaddress:
                            new_proxyaddresses.append(proxyaddress)
                        else:
                            smtp  = proxyaddress.split(":")[0]
                            email = proxyaddress.split(":")[1]
                            if any(char.isupper() for char in email):
                                new_email = email.lower()
                                proxyaddress = f"{smtp}:{new_email}"
                                new_proxyaddresses.append(proxyaddress)
                                PROXY=True
                            else:
                                new_proxyaddresses.append(proxyaddress)
                    if PROXY:
                        ## only update if we have a change for proxyaddresses                    
                        before["profile"]["proxyaddresses"]        = response_json['profile']['proxyaddresses']
                        payload["profile"]["proxyaddresses"]       = new_proxyaddresses
                        response_json['profile']['proxyaddresses'] = new_proxyaddresses
                        FLIP=True

            if FLIP  :
                combined_dict = {
                    "query": query,
                    "before": before,
                    "payload": payload
                }
                self.logger.debug(json.dumps(combined_dict, indent=4))
                self.logger.debug("=-"*40)
                url = f'https://{self.OKTA_DOMAIN}/api/v1/users/{id}'
                response = requests.post(url, json=payload, headers=self.__get_headers__(), params=query)
                if response.status_code != 200:
                    self.logger.error(f"Failed to update ({url}) Status: {response.status_code} / {response.json()}")
                    return False
                       
                ## clear cache file && re-write so in local cache as updated
                self.user(id, True)

                # if PROXY: exit(0)
                return True
        return False
        
    def user_set_password(self, id, password):
        ## MIGHT want to instead use this endpoint: https://developer.okta.com/docs/reference/api/authn/#reset-password
        ##    which (should?) force a password reset on next time they login
        self.logger.debug(f"setting user: {id}")        
        url = f'https://{self.OKTA_DOMAIN}/api/v1/users/{id}'
        query = { "strict": "false" }
        payload = { 
            "credentials": {
                "password": 
                    { "value": password }
            } 
        }
        response = requests.post(url, json=payload, headers=self.__get_headers__(), params=query)
        if response.status_code != 200:
            self.logger.error(f"Failed to update ({url}) Status: {response.status_code} / {response.json()}")
            return False
        return True
                    
    def user_get_apps(self, id):
        ## this returns "official" apps assigned to the user - not private on-the-fly ones
        url = f'https://{self.OKTA_DOMAIN}/api/v1/users/{id}/appLinks'
        response = self.__https_get__(url)
        return response.json()
    
    def user_lifecycle_change(self, id, lifecycle):
        url = f'https://{self.OKTA_DOMAIN}/api/v1/users/{id}/lifecycle/{lifecycle}'
        while True:
            response = requests.post(url, headers=self.__get_headers__())
            if response.status_code == 200:
                self.logger.info(f"User status changed: {url} - response: {response.status_code} / {response.text}")
                return True
            elif response.status_code == 429:
                reset_time = int(response.headers.get('X-Rate-Limit-Reset', time.time() + 60))
                wait_time = reset_time - int(time.time())
                self.logger.warning(f"RATE_LIMIT_EXCEEDED - Waiting for {wait_time} seconds before retrying.")
                time.sleep(wait_time)
            else:
                self.logger.warning(f"Failed to flip user: {url} - response: {response.status_code} / {response.text}")
                return False

    def groups(self, id):
        if id in self.cache_groups:
            return self.cache_groups[id]
        url = f'https://{self.OKTA_DOMAIN}/api/v1/groups/{id}'
        filename = f"{self.dir_groups}/{id}.json"
        group_info = self.__fetch_to_cache__(url, filename)
        self.cache_groups[id] = group_info
        return group_info
       
    def group_id_by_name(self, name):
        # Check the cache first
        for group_id, group_info in self.cache_groups.items():
            if group_info.get('profile').get('name') == name:
                return group_id
    
        # If not found in cache, call the Okta API
        url = f'https://{self.OKTA_DOMAIN}/api/v1/groups?q={name}'
        response = self.__https_get__(url)
        if response:
            groups = response.json()
            for group in groups:
                if group.get('profile').get('name') == name:
                    self.cache_groups[group['id']] = group
                    return group['id']
        else:
            self.logger.warning(f"Failed to retrieve group by name: {name}. Status {response.status_code} / {response.text}")
        return None
    
    def groups_fetch_all(self, STOP_LIMIT=None):
        return self.__fetch_all__("groups", self.cache_groups, self.dir_groups, STOP_LIMIT)

    def groups_users(self, id):
        if id in self.cache_groups_users:
            return self.cache_groups_users[id]
        
        filename = f"{self.dir_groups_users}/{id}.json"
        if os.path.exists(filename):
            with open(filename, 'r') as f:
                group_users = json.load(f)
                self.cache_groups_users[id] = group_users
                return group_users     
        
        group_users = []
        url = f'https://{self.OKTA_DOMAIN}/api/v1/groups/{id}/users'
        while True:
            self.logger.debug(f"Fetching group_users from {url}")
            response = self.__https_get__(url)
            items = response.json()
            group_users.extend(items)
            if 'next' in response.links:
                url = response.links['next']['url']
            else:
                break

        with open(filename, 'w') as f:
            json.dump(group_users, f)
        self.cache_groups_users[id] = group_users
        return group_users
    
    def groups_users_fetch_all(self, STOP_LIMIT=None):
        count = 0
        for group_id in self.cache_groups:
            self.logger.info(f"Fetching group_users for: {group_id} {count}/{len(self.cache_groups)}")
            self.groups_users(group_id)
            count += 1
    
    def app(self, id, user_id=None, force=False):
        ### TODO - verify if other files start with the file in question....
        ###    if files were moved they will get called again and written 2nd version

        ## the logic on saving these under the user_id is if it is an on-the-fly private app
        ##    which are not able to be found except by walking the system log for each user
        ##    if you walk the logs and you have a target[0] record in the log
        ##    - and that has a displayName of "On The Fly App" then you can get the id
        ##    - then you can grab the app info from the api 
        if force is False and id in self.cache_apps:
            return self.cache_apps[id]
        url = f'https://{self.OKTA_DOMAIN}/api/v1/apps/{id}' ## GET
        if user_id is not None:
            self.__mkdir_p__(f"{self.dir_users_apps}/{user_id}")
            filename = f"{self.dir_users_apps}/{user_id}/{id}.json"
        else:
            filename = f"{self.dir_app_info}/{id}.json"
        app_info = self.__fetch_to_cache__(url, filename, force)
        self.cache_apps[id] = app_info
        return app_info

    def flip_status(self, id, activate):
        if activate:
            url = f'https://{self.OKTA_DOMAIN}/api/v1/apps/{id}/lifecycle/activate'   ## POST
        else:
            url =  f'https://{self.OKTA_DOMAIN}/api/v1/apps/{id}/lifecycle/deactivate' ## POST
        self.logger.debug(f"========== Flipping APP: {url} ==========")
        while True:
            response = requests.post(url, headers=self.__get_headers__())
            if response.status_code == 200:
                return True
            elif response.status_code == 429:
                reset_time = int(response.headers.get('X-Rate-Limit-Reset', time.time() + 60))
                wait_time = reset_time - int(time.time())
                self.logger.warning(f"RATE_LIMIT_EXCEEDED - Waiting for {wait_time} seconds before retrying.")
                time.sleep(wait_time)
            else:
                self.logger.warning(f"with change: {url} - response: {response}")
                return False
    
    def app_allow_reveal(self, id):
        url = f'https://{self.OKTA_DOMAIN}/api/v1/apps/{id}'
        headers = self.__get_headers__()
        
        # Get the current app settings
        response = self.__https_get__(url)
        if response is None:
            return False
        app_settings = response.json()
        
        # Update the credentials object to allow password reveal
        app_settings['credentials']['revealPassword'] = True
        
        # Send the update request
        response = requests.put(url, headers=headers, json=app_settings)
        if response.status_code != 200:
            self.logger.warning(f"Failed to update app settings: {url} - response: {response}")
            return False
        
        self.logger.info(f"Successfully updated app settings to allow password reveal: {url}")
        self.app(id, True)  ## force cache update post change
        return True

    def apps_fetch(self, STOP_LIMIT=999999):
        return self.__fetch_all__("apps", self.cache_apps, self.dir_app_info, STOP_LIMIT)

    # Function to get users for a given app ID
    def app_get_users(self, id):
        users     = []
        filename = f"{self.dir_app_users}/{id}.json.gz"
        if os.path.exists(filename):
            with gzip.open(filename, 'rt') as f:
                users = json.load(f)
        else:
            url = f'https://{self.OKTA_DOMAIN}/api/v1/apps/{id}/users?limit={self.LIMIT_USERS}'       
            while url:
                self.logger.info(f"      Fetching {id} USERS:  {url} ")
                response = self.__https_get__(url)
                users.extend(response.json())
                link_header = response.headers.get('Link')   # Okta uses Link headers for pagination. Extract the next page URL if present.
                next_link = None
                if link_header:
                    links = link_header.split(', ')
                    for link in links:
                        if 'rel="next"' in link:
                            next_link = link[link.find('<')+1:link.find('>')]
                            break
                    url = next_link
                else:
                    self.logger.warning(f"Failed to retrieve users for app {id}. Status code: {response.status_code}")
                    break
            with gzip.open(filename, 'wt') as f:
                json.dump(users, f)
        return users

    def app_get_groups(self, id):
        groups    = []
        filename = f"{self.dir_app_groups}/{id}.json"
        if os.path.exists(filename):
            with open(filename, 'r') as f:
                groups = json.load(f)
        else:
            url = f'https://{self.OKTA_DOMAIN}/api/v1/apps/{id}/groups?limit={self.LIMIT_GROUPS}'
            while url:
                self.logger.info(f"      Fetching {id} GROUPS: {url} ")
                response = self.__https_get__(url)
                groups.extend(response.json())
                link_header = response.headers.get('Link')   # Okta uses Link headers for pagination. Extract the next page URL if present.
                next_link = None
                if link_header:
                    links = link_header.split(', ')
                    for link in links:
                        if 'rel="next"' in link:
                            next_link = link[link.find('<')+1:link.find('>')]
                            break
                    url = next_link
                else:
                    self.logger.warning(f"Failed to retrieve groups for app {id}. Status code: {response.status_code}")
                    url = None
                    break
            with open(filename, 'w') as f:
                json.dump(groups, f)
        return groups

    def app_get_group_names(self, id):
        groups = self.app_get_groups(id)
        if groups is None:
            return None
        if len(groups) == 0:
            return None
        ret_groups = []
        for group in groups:
            group_info = self.groups(group.get('id'))
            group_name = group_info.get('profile').get('name')
            ret_groups.append(group_name)
        return ret_groups
    
    def app_cache_rename(self, id, new_extension):
        filename = f"{self.dir_app_info}/{id}.json"
        if os.path.exists(filename):
            new_filename = f"{filename}_{new_extension}"
            os.rename(filename, new_filename)
            self.logger.info(f"renamed {filename} {new_filename}")

########################################################################################
class AppTracker:
    def __init__(self, apptracker_url, apptracker_bearer):
        ## make sure that other modules are calling with same logger name
        self.logger                  = logging.getLogger('__COMMONLOGGER__')
        if apptracker_url is None:
            raise ValueError("apptracker_url is a required parameter")
        self.apptracker_url = apptracker_url
        if apptracker_bearer is None:
            raise ValueError("apptracker_bearer is a required parameter")
        self.apptracker_bearer = apptracker_bearer
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {apptracker_bearer}"
        }

    def __sanitize_json__(self, data):
        if isinstance(data, dict):
                return {k: self.__sanitize_json__(v) for k, v in data.items()}
        elif isinstance(data, list):
                return [self.__sanitize_json__(v) for v in data]
        elif isinstance(data, float) and (math.isnan(data) or math.isinf(data)):
                return None
        else:
                return data
           
    def write(self, okta_id, **kwargs):
        entra_app_info = kwargs.get('entra_app_info', None)
        entra_sp_info = kwargs.get('entra_sp_info', None)
        okta_info = kwargs.get('okta_info', None)
        sso_info = kwargs.get('sso_info', None)
        tenant_id = kwargs.get('tenant_id', None)

        json_data = { "okta_id": okta_id }
        if entra_app_info: json_data["entra_app_info"] = entra_app_info
        if entra_sp_info: json_data["entra_sp_info"] = entra_sp_info
        if okta_info: json_data["okta_info"] = self.__sanitize_json__(okta_info)
        if sso_info: json_data["sso_info"] = sso_info
        if tenant_id: json_data["tenant_id"] = tenant_id
        
        self.logger.debug(f"oktaAppTracker({okta_id}) Sending data to apptracker")
        response = requests.post(f"{self.apptracker_url}/v1/ingestMessage/{okta_id}", headers=self.headers, json=json_data)
        if response.status_code != 200:
            self.logger.error(f"oktaAppTracker({okta_id}) FAILURE_APP_TRACKER: {response.text}")
            return False
        return True

    def set_sso_info(self, okta_id, key, value):
        url = f"{self.apptracker_url}/v1/fetch/{okta_id}/sso_info"
        response = requests.get(url, headers=self.headers)
        if response.status_code != 200:
            self.logger.warning(f"set_sso_info({okta_id}) FAILURE_APP_TRACKER: {response.text}")
            return False
        json_data = response.json()
        sso_info = json_data.get("sso_info", {})
        if sso_info is None:
            sso_info = {}
        sso_info[key] = value
        return self.write(okta_id, sso_info=sso_info)

    def delete(self, okta_id):
        url = f"{self.apptracker_url}/v1/deleteMessage/{okta_id}"
        response = requests.delete(url, headers=self.headers)
        if response.status_code != 200:
            self.logger.warning(f"delete({okta_id}) FAILURE_APP_TRACKER: {response.text}")
            return False
        return True

    def cache_all(self, apptracker_json_path):
        if self.__check_file_newer_than__(apptracker_json_path, 1):
            self.logger.info(f"USING CACHED APPTRACKER INFO: {apptracker_json_path}")
            with open(apptracker_json_path, 'r') as f:
                apptracker_json_info = json.load(f)
        else:
            url = f"{self.apptracker_url}/v1/fetchAll"
            response = requests.get(url, headers=self.headers)
            if response.status_code != 200:
                self.logger.error(f"Failed to fetch app info from apptracker for all records")
                exit(1)
            apptracker_json_info = response.json()
            with open(apptracker_json_path, 'w') as output_file:
                json.dump(apptracker_json_info, output_file)
        return apptracker_json_info
  
    def __check_file_newer_than__(self, filename, hours):
        if os.path.exists(filename):
            file_mod_time = os.path.getmtime(filename)
            current_time = time.time()
            one_hour_ago = current_time - (hours * 60 * 60)  # 3600 seconds in an hour
            return file_mod_time > one_hour_ago
        return False
