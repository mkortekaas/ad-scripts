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

import msal
import logging
import json
import requests
import uuid
import re
import time
import urllib
import os
import glob
import inspect
from concurrent.futures import ThreadPoolExecutor

class EntraClient:
    def __init__(self, tenant_id, client_id, client_secret, required_scopes, graph_api_url, cache_dir=None, FLUSH=False):
        ## make sure that other modules are calling with same logger name
        self.logger          = logging.getLogger('__COMMONLOGGER__')
        self.tenant_id       = tenant_id
        self.client_id       = client_id
        self.client_secret   = client_secret
        self.required_scopes = required_scopes
        self.graph_api_url   = graph_api_url
        self.cache_dir       = cache_dir

        if FLUSH:
            self.flush()

        ## subclasses
        self.Users           = self.Users(self)
        self.Applications    = self.Applications(self)
        self.Groups          = self.Groups(self)
        self.PasswordSSO     = self.PasswordSSO(self)
        self.authenticate()

    def authenticate(self):
        ## 
        ## If your loops are very long you will eventually get a token that expires and we don't reliably check for that
        ##  elsewhere in this module to refetch a new token. Probably should add that but for now just call authentiate() every
        ##  so often
        ##
        self.logger.info("Authenticating with MS_GRAPH and getting valid token")
        app = msal.ConfidentialClientApplication(
            self.client_id,
            authority=f"https://login.microsoftonline.com/{self.tenant_id}",
            client_credential=self.client_secret,
        )
        result = app.acquire_token_for_client(scopes=self.required_scopes)
        if "access_token" not in result:
            self.logger.critical("Failed to acquire token")
            self.logger.error("Failed to acquire token")
            self.logger.debug(result.get("error"))
            self.logger.debug(result.get("error_description"))
            raise Exception("Failed to acquire token")
        self.access_token = result["access_token"]
        self.headers = {
            "Authorization": f"Bearer {result['access_token']}",
            "Content-Type": "application/json",
        }

    def flush(self):
        self.logger.info(f"FLUSHING ENTRA CACHE in ({self.cache_dir})")
        os.system(f"rm -rf {self.cache_dir}/entra*")

    def __mkdir_p__(self, path):
        os.makedirs(path, exist_ok=True)
        return path
    
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Cleanup if needed
        pass

    def __is_valid_uuid__(self, input):
        try:
            uuid_obj = uuid.UUID(input, version=4)
        except ValueError:
            return False
        return str(uuid_obj) == input

    def names_create(self, input_app_name, new_app_prefix, new_group_prefix, input_groups):
        if input_app_name is None:
            self.logger.warning("names_create() INPUT_APP_NAME required")
            return None, None, None
        if new_app_prefix is None:
            new_app_prefix = ""
        if new_group_prefix is None:
            new_group_prefix = ""
        
        ## need to remove these characters from the app name to pass downstream tests
        clean_app_name = re.sub(r"[<>&;%']", "", input_app_name)
        new_app_name = f"{new_app_prefix}{clean_app_name}"
        new_group_name = f"{new_group_prefix}{clean_app_name}"

        EN_DASH = "\u2013"  # Unicode code point for "EN DASH"
        new_app_name   = new_app_name.replace(EN_DASH, "-")
        new_group_name = new_group_name.replace(EN_DASH, "-")

        EM_DASH = "\u2014"  # Unicode code point for "EN DASH"
        new_app_name   = new_app_name.replace(EM_DASH, "-")
        new_group_name = new_group_name.replace(EM_DASH, "-")

        return new_app_name, new_group_name, input_groups
    
    def __clean_email_addrs__(self, group_name):
        # Define the allowed characters (ASCII 0-127 excluding specified characters)
        allowed_chars = re.compile(r'[^a-zA-Z0-9._-]')
        cleaned_name = allowed_chars.sub('', group_name)
        cleaned_name = cleaned_name[:64]
        cleaned_name = cleaned_name.lower()
        return cleaned_name
    
    def get_graph_scopes(self):
        graph_app_id = "00000003-0000-0000-c000-000000000000"
        response = requests.get(
            f"{self.graph_api_url}/v1.0/servicePrincipals?$filter=appId eq '{graph_app_id}'",
            headers=self.headers
        )
        if response.status_code == 200:
            service_principals = response.json()["value"]
            if service_principals:
                graph_sp = service_principals[0]
                scopes = graph_sp.get("oauth2PermissionScopes", [])
            else:
                self.logger.info("Microsoft Graph service principal not found.")
                return []
        else:
            self.logger.warning(f"entraGetGraphScopes() Failed to get service principal: {response.text}")
            return []
        self.logger.info("Available OAuth2 Permission Scopes for Microsoft Graph:")
        for scope in scopes:
            self.logger.info(f"ID: {scope['id']}, Value: {scope['value']}, Admin Consent: {scope['adminConsentDisplayName']}")
        return scopes
    
    def http_get(self, url):
        response = requests.get(url, headers=self.headers)
        if response.status_code == 200:
            return response.json()
        self.logger.warning(f"HTTP GET failed: {response.status_code}")
        return None
    
    def __read_from_cache__(self, cache_file):
        with open(cache_file, "r") as f:
            data = json.load(f)
            return data
        
    def __write_to_cache__(self, cache_file, data):
        if self.cache_dir is None: return
        self.logger.debug(f"-e-e-e- Writing into disk cache: {cache_file}")
        with open(cache_file, "w") as f:
            json.dump(data, f)

    def __load_json_file__(self, file_path):
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError, IOError) as e:
            self.logger.warning(f"Failed to load JSON from {file_path}: {e}")
            data = {}
        return data
    
    def __get_details__(self, my_request, my_type, my_cache, my_cache_dir, my_key, FORCE_NEW=False):
        if my_request is None: return None

        # is it in memory already?
        if not FORCE_NEW and my_request in my_cache:
            return my_cache[my_request]
        
        if my_cache_dir is not None and self.__is_valid_uuid__(my_request):
            my_filename = f"{my_cache_dir}/{urllib.parse.quote(my_request, safe='')}.json"
            if not FORCE_NEW:
                if os.path.exists(my_filename):
                    data = self.__read_from_cache__(my_filename)
                    my_cache[data['id']]   = data
                    my_cache[data[my_key]] = data
                    return data

        next_uri = f"{self.graph_api_url}/v1.0/{my_type}"
        if self.__is_valid_uuid__(my_request):
            ## if we call it using the ID then the search for app name will not match format wise - thus do both as filter search
            query = { "$filter": f"id eq '{my_request}'" }            
        else:
            query = { "$filter": f"{my_key} eq '{my_request}'" }

        if my_type == "users":
            query["$select"] = 'businessPhones,displayName,givenName,jobTitle,mail,mobilePhone,officeLocation,preferredLanguage,surname,userPrincipalName,id,proxyAddresses,mailNickname,accountEnabled'
            
        response = requests.get(next_uri, headers=self.headers, params=query)
        if response.status_code != 200:
            self.logger.debug(f"{self.__class__.__name__}.{self.__caller_info__()}({my_request}) Failed to retrieve {my_type}")
            return None

        my_response = response.json().get('value', [])
        if len(my_response) == 0:
            self.logger.debug(f"{self.__class__.__name__}.{self.__caller_info__()}({my_request}) not found")
            return None
        
        my_item = my_response[0]
        if my_cache_dir is not None:
            id_filename  = f"{my_cache_dir}/{urllib.parse.quote(my_item['id'], safe='').lower()}.json"
            self.__write_to_cache__(id_filename, my_item)

        my_cache[my_item['id']]   = my_item
        my_cache[my_item[my_key]] = my_item
        return my_item
    
    def __get_all__(self, my_type, my_cache, my_cache_dir, my_key, STOP_LIMIT=None):
        count      = 0
        my_list    = []
        my_limit   = 100000
        if STOP_LIMIT is not None: my_limit = STOP_LIMIT
        if my_cache_dir is not None:
            json_files = glob.glob(os.path.join(my_cache_dir, "*.json"))
            if (len(json_files) > 0):
                self.logger.debug(f"USING CACHED FILES ({my_type}): {len(json_files)}")
                for json_file in json_files:
                    if count >= my_limit:
                        break
                    data = self.__load_json_file__(json_file)
                    my_list.append(data)
                    my_cache[data['id']]   = data
                    my_cache[data[my_key]] = data
                return my_list
            
        ## TODO: implement stoplimit properly
        next_uri = f"{self.graph_api_url}/v1.0/{my_type}"
        query = {}
        if my_type == "users":
            ## for users we want to get more data
            query["$select"] = 'businessPhones,displayName,givenName,jobTitle,mail,mobilePhone,officeLocation,preferredLanguage,surname,userPrincipalName,id,proxyAddresses,mailNickname,accountEnabled'
        while next_uri:
            self.logger.debug(f"Getting {my_type} from {next_uri}")
            response = requests.get(next_uri, headers=self.headers, params=query)
            if response.status_code != 200:
                self.logger.warning(f"{self.__class__.__name__}.{self.__caller_info__()}() Failed to retrieve all {my_type} ({response.json()})")
                return None
            data = response.json()
            my_list.extend(data.get('value', []))
            next_uri = data.get('@odata.nextLink')
            query = {}  # we only need the params on the first request - fails if we keep it set
        for data in my_list:
            my_cache[data['id']]   = data
            my_cache[data[my_key]] = data
            if my_cache_dir is not None:
                self.__write_to_cache__(f"{my_cache_dir}/{urllib.parse.quote(data['id'], safe='').lower()}.json", data)
        return my_list
    
    def __caller_info__(self):
        # Dynamically fetch the class and method names
        method_name = inspect.currentframe().f_back.f_code.co_name
        return method_name
    
    ###########################################################################################
    #################################### USERS ################################################
    ###########################################################################################
    class Users:
        ## this class exists to cache the user OIDs to avoid repeated calls to the graph API
        ##   you still create a new list of users each time you call get_oids, 
        ##   but it will only call the graph API for new users and pull from the cache otherwise
        ##   This -will- cache None values, so if you get a None value, it will not try again on invalid email
        def __init__(self, client, user_emails=None):
            self.client          = client
            self.cache           = {}
            self.users_cache_dir = None
            if (self.client.cache_dir is not None):
                self.users_cache_dir = self.client.__mkdir_p__(f'{self.client.cache_dir}/entra_users')
            if user_emails is not None:
                if not isinstance(user_emails, list):
                    user_emails = [user_emails]
                user_emails = list(set(user_emails))  # Remove duplicates
                user_emails = [email.lower() for email in user_emails]  # Lowercase all email addresses
                for email in user_emails:
                    self.get_oid(email)

        def get_details(self, email, FORCE_NEW=False):
            return self.client.__get_details__(email.lower(), "users", self.cache, self.users_cache_dir, "userPrincipalName", FORCE_NEW)

        def get_oid(self, email):
            data = self.get_details(email)
            if data is not None:
                oid = data.get("id")
                return oid
            return None
        
        def get_oids(self, user_emails):
            if not isinstance(user_emails, list):
                user_emails = [user_emails]
            user_emails = list(set(user_emails))  # Remove duplicates
            user_emails = [email.lower() for email in user_emails]  # Lowercase all email addresses
            oids = []
            for email in user_emails:
                data = self.get_details(email)
                if data is not None:
                    oid = data.get("id")
                    oids.append(oid)
            return oids
        
        def get_all(self, STOP_LIMIT=None):
            return self.client.__get_all__("users", self.cache, self.users_cache_dir, 'userPrincipalName', STOP_LIMIT)
        
        def user_fields_lower_case(self, id):
            if id is None: return False     
            user_data       = self.get_details(id)
            if user_data is None: return False
            # self.client.logger.debug(f"Checking user ID: {id} / {user_data['userPrincipalName']}")

            # we get the extra data for the user(s) given the way we call the graph API -- see above query/params
            if 'accountEnabled' in user_data and user_data['accountEnabled'] is False:
                # self.client.logger.info(f"Skipping disabled user {id} / {user_data['userPrincipalName']}")
                return False

            data_before = {}
            data_after = {}
            FLIP=False
            if 'userPrincipalName' in user_data and user_data['userPrincipalName'] is not None:
                if any(char.isupper() for char in user_data['userPrincipalName']):
                    data_before['userPrincipalName']  = user_data['userPrincipalName']
                    data_after['userPrincipalName']   = user_data['userPrincipalName'].lower()
                    FLIP=True

            # mail thinks it can be changed but it doesn't take effect
            # if 'mail' in user_data and user_data['mail'] is not None:
            #     if any(char.isupper() for char in user_data['mail']):
            #         data_before["mail"]               = user_data['mail']
            #         data_after["mail"]                = user_data['mail'].lower()
            #         FLIP=True

            if 'mailNickname' in user_data and user_data['mailNickname'] is not None:
                if any(char.isupper() for char in user_data['mailNickname']):
                    data_before["mailNickname"]       = user_data['mailNickname']
                    data_after["mailNickname"]        = user_data['mailNickname'].lower()
                    FLIP=True

            # Error : "Property 'proxyAddresses' is read-only and cannot be set."
            # PROXY=False
            # if 'proxyAddresses' in user_data and user_data['proxyAddresses'] is not None:
            #     if len(user_data['proxyAddresses']) > 0:
            #         new_proxyaddresses = []
            #         for proxyaddress in user_data['proxyAddresses']:
            #             if not ":" in proxyaddress:
            #                 new_proxyaddresses.append(proxyaddress)
            #             else:
            #                 smtp  = proxyaddress.split(":")[0]
            #                 email = proxyaddress.split(":")[1]
            #                 if any(char.isupper() for char in email):
            #                     new_email = email.lower()
            #                     proxyaddress = f"{smtp}:{new_email}"
            #                     new_proxyaddresses.append(proxyaddress)
            #                     PROXY=True
            #                 else:
            #                     new_proxyaddresses.append(proxyaddress)
            #         if PROXY:
            #             ## only update if we have a change for proxyaddresses                    
            #             data_before["proxyAddresses"]     = user_data['proxyAddresses']
            #             data_after["proxyAddresses"]      = new_proxyaddresses
            #             FLIP=True

            if FLIP:
                next_uri = f"{self.client.graph_api_url}/v1.0/users/{id}"
                combined_dict = {
                    "next_url": next_uri,
                    "before": data_before,
                    "payload": data_after
                }
                self.client.logger.debug(json.dumps(combined_dict, indent=4))

                # actually update
                response = requests.patch(next_uri, headers=self.client.headers, json=data_after)
                if response.status_code != 204:
                    self.client.logger.warning(f"Failed to lowercase for user {id}: {response.status_code} - {response.text}")
                    return False

                # force update the cache
                user_data = self.get_details(id, True)
                if user_data is None: return False
                return True
            return False

        def __str__(self):
            return f"{self.cache}"

        def __repr__(self):
            return f"{self.__class__.__name__}.{self.client.__caller_info__()}(graph_api_url={self.client.graph_api_url!r}, headers={self.client.headers!r}, cache={self.cache!r})"
    ###########################################################################################
    #################################### USERS ################################################
    ###########################################################################################

    ###########################################################################################
    #################################### APPS #################################################
    ###########################################################################################
    class Applications:
        def __init__(self, client):
            self.client           = client
            self.cache            = {}
            self.sp_cache         = {}
            self.apps_cache_dir = None
            if (self.client.cache_dir is not None):
                self.apps_cache_dir = self.client.__mkdir_p__(f'{self.client.cache_dir}/entra_apps')
                self.sp_cache_dir   = self.client.__mkdir_p__(f'{self.client.cache_dir}/entra_service_principals')

        def get_details(self, app):
            return self.client.__get_details__(app, "applications", self.cache, self.apps_cache_dir, "displayName")
        
        def get_all(self, STOP_LIMIT=None):
            return self.client.__get_all__("applications", self.cache, self.apps_cache_dir, 'displayName', STOP_LIMIT)

        def get_service_principal_details(self, app):
            return self.client.__get_details__(app, "servicePrincipals", self.sp_cache, self.sp_cache_dir, "displayName")
            
        def get_all_service_principals(self, STOP_LIMIT=None):
            return self.client.__get_all__("servicePrincipals", self.sp_cache, self.sp_cache_dir, 'displayName', STOP_LIMIT)
        
        def get_id(self, app_name):
            app_info = self.get_details(app_name)
            if app_info is None:
                return None
            return app_info.get("id")
        
        def get_aid(self, app_name):
            app_info = self.get_details(app_name)
            if app_info is None:
                return None
            return app_info.get("appId")
                
        def get_service_principal_id(self, app_name):
            sp_info = self.get_service_principal_details(app_name)
            if sp_info is None:
                return None
            return sp_info["id"]
            
        def get_sso_type(self, app_name):
            sp_info = self.get_service_principal_details(app_name)
            if sp_info is None:
                return None
            return sp_info.get('preferredSingleSignOnMode')
        
        def disable_sso(self, service_principal_id):
            self.client.logger.info(f"Disabling SSO for service principal {service_principal_id}")
            next_uri = f"{self.client.graph_api_url}/v1.0/servicePrincipals/{service_principal_id}"
            payload = { "preferredSingleSignOnMode": "notSupported"  }
            response = requests.patch(next_uri, headers=self.client.headers, json=payload)
            if response.status_code != 204:
                self.client.logger.error("Failed to disable SSO")
                self.client.logger.error(f"URI: {next_uri}")
                self.client.logger.error(json.dumps(response.json(), indent=4))
                exit(1)
            self.client.logger.info(f"SSO disabled for service principal {service_principal_id}")

        def delete_group(self, service_principal_id, group_id):
            next_uri = f"{self.client.graph_api_url}/v1.0/servicePrincipals/{service_principal_id}/appRoleAssignedTo"
            response = requests.get(next_uri, headers=self.client.headers)
            if response.status_code != 200:
                self.client.logger.warning(f"{self.__class__.__name__}.{self.client.__caller_info__()}({service_principal_id})({group_id}) Error (1) deleting group from service principal response code: {response.status_code}")
                return False
            for value in response.json()['value']:
                if value['principalId'] == group_id:
                    next_uri = f"{self.client.graph_api_url}/v1.0/servicePrincipals/{service_principal_id}/appRoleAssignedTo/{value['id']}"
                    response = requests.delete(next_uri, headers=self.client.headers)
                    if response.status_code != 204:
                        self.client.logger.warning(f"{self.__class__.__name__}.{self.client.__caller_info__()}({service_principal_id})({group_id}) Error (2) deleting group from service principal response code: {response.status_code}")
                        return False
                    self.client.logger.info(f"{self.__class__.__name__}.{self.client.__caller_info__()}({service_principal_id})({group_id}) Group deleted from application")
                    return True
            self.client.logger.info(f"{self.__class__.__name__}.{self.client.__caller_info__()}({service_principal_id})({group_id}) Group not assigned to application")
            return False
        
        def get_users_groups(self, app_name, service_principal_id):
            self.client.logger.debug(f"{self.__class__.__name__}.{self.client.__caller_info__()}() Getting Users/Groups assigned to {app_name}")
            next_uri = f"{self.client.graph_api_url}/v1.0/servicePrincipals/{service_principal_id}/appRoleAssignedTo"
            response = requests.get(next_uri,headers=self.client.headers,)
            if response.status_code != 200:
                self.client.logger.info(f"{self.__class__.__name__}.{self.client.__caller_info__()}({app_name}) FAILURE_GROUP_APP Failed to retrieve users/groups assigned {response.status_code}")
                return None
            response_json = response.json()
            # logger.debug(json.dumps(response_json, indent=4))
            if "value" in response_json and len(response_json["value"]) > 0:
                return response_json["value"]
            self.client.logger.debug(f"{self.__class__.__name__}.{self.client.__caller_info__()}() No users/groups assigned to ({app_name}) ({service_principal_id})")
            return []
        
        def __add_role__(self, names, app_id, app_details): 
            ## you have to do this in bulk - otherwise you have to wait a long time between
            if app_details is not None:
                if "appRoles" in app_details:
                    new_app_details = app_details["appRoles"]
                else:
                    new_app_details = []

            for name in names:
                # Check if the name is already in the description field of any existing roles
                if any(name in role['description'] for role in new_app_details):
                    self.client.logger.debug(f"{self.__class__.__name__}.{self.client.__caller_info__()}({names}) - Role with description containing '{name}' already exists.")
                    continue

                appRoleUUID = str(uuid.uuid4())
                new_app_role = {
                    "id": appRoleUUID,  # Generate a unique GUID for this role
                    "allowedMemberTypes": ["User"],  # only works with User as option
                    "description": f"{name} EntraAppRole", 
                    "displayName": f"{name} EntraAppRole",  ## NOTE if you change here look for the same in self.add_group()
                    "isEnabled": True,
                    "value": f"{appRoleUUID}"  
                }
                new_app_details.append(new_app_role)
                self.client.logger.debug(f"{self.__class__.__name__}.{self.client.__caller_info__()}({names}) new_app_role: {new_app_role}")

            if new_app_details != app_details:
                next_uri = f"{self.client.graph_api_url}/v1.0/applications/{app_id}"
                response = requests.patch(next_uri,headers=self.client.headers,json={"appRoles": new_app_details})
                if response.status_code == 204:
                    self.client.logger.debug(f"{self.__class__.__name__}.{self.client.__caller_info__()}({names}) New appRole added {app_id}")
                    return new_app_details
                self.client.logger.warning(f"{self.__class__.__name__}.{self.client.__caller_info__()}({names}) FAILURE_GROUP_APPROLE to add new appRole(s)")
                return None
            return app_details
        
        def __add_group__(self, group_name, app_name, app_id, app_details):
            service_principal_id = self.get_service_principal_id(app_name)
            existing_assignments = self.get_users_groups(app_name, service_principal_id)
            self.client.logger.debug(f"{self.__class__.__name__}.{self.client.__caller_info__()}({group_name}) existing_assignments: {existing_assignments}")
            if existing_assignments is None:
                self.client.logger.warning(f"{self.__class__.__name__}.{self.client.__caller_info__()}({group_name}) FAILURE_GROUP_APP Failed to retrieve existing assignments - WHY?")
                return False           
            if not isinstance(group_name, list):
                groups = [group_name]
            else:
                groups = group_name
            appRoleResponse = self.__add_role__(groups, app_id, app_details)
            if appRoleResponse is None:
                self.client.logger.warning(f"{self.__class__.__name__}.{self.client.__caller_info__()}({group_name}) FAILURE_GROUP_APPROLE Failed to add to {app_name}")
                return False
            for my_group_name in groups:
                group_id = self.client.Groups.get_id(my_group_name)
                if group_id is None:
                    self.client.logger.warning(f"{self.__class__.__name__}.{self.client.__caller_info__()}({group_name})({my_group_name}) FAILURE_GROUP_APP not found")
                    continue
                if any(assignment["principalId"] == group_id for assignment in existing_assignments):
                    self.client.logger.debug(f"{self.__class__.__name__}.{self.client.__caller_info__()}({group_name})({my_group_name}) is already attached to application {app_name}")
                    continue
                self.client.logger.debug(f"{self.__class__.__name__}.{self.client.__caller_info__()}({group_name})({my_group_name}) found with ID {group_id}")
                # note if this changes in __add_role__ need to fix here
                for appRole in appRoleResponse:
                    if f"{my_group_name} EntraAppRole" == appRole['displayName']:
                        appRoleUUID = appRole['id']
                add_group_body = {
                    "principalId": group_id,
                    "resourceId": service_principal_id,  ## service principal ID
                    "appRoleId": appRoleUUID
                }
                next_uri = f"{self.client.graph_api_url}/v1.0/groups/{group_id}/appRoleAssignments"
                response = requests.post( next_uri,headers=self.client.headers,json=add_group_body)
                if response.status_code == 201:
                    self.client.logger.debug(f"{self.__class__.__name__}.{self.client.__caller_info__()}({group_name})({my_group_name}) Group added to {app_name}")
                else:
                    self.client.logger.warning(f"{self.__class__.__name__}.{self.client.__caller_info__()}({group_name})({my_group_name}) FAILURE_GROUP_APP Failed to add group to ({app_name}) - {response.status_code} - {add_group_body}")
                    return False
            return True

        def add_group(self, group_name, app_name, app_id, app_details):
            status = self.__add_group__(group_name, app_name, app_id, app_details)
            if not status:
                self.client.logger.warning(f"{self.__class__.__name__}.{self.client.__caller_info__()}({app_name}) FAILURE_GROUP_APP Failed to add group to - sleep for 15s and try again")
                time.sleep(15)
                status = self.__add_group__(group_name, app_name, app_id, app_details)
                if not status:
                    self.client.logger.warning(f"{self.__class__.__name__}.{self.client.__caller_info__()}({app_name}) FAILURE_GROUP_APP Failed to add group")
                    return False
            return True
        
        def get_with_prefix(self, app_prefix):
            limit = 250
            url = f"{self.client.graph_api_url}/v1.0/applications?$filter=startswith(displayName, '{app_prefix}')&$top={limit}"
            response = requests.get( url, headers=self.client.headers)
            if response.status_code == 200:
                return response.json()['value']
            return None

        def delete(self, app_name, app_id):
            url = f"{self.client.graph_api_url}/v1.0/applications/{app_id}"
            self.client.logger.info (f"{self.__class__.__name__}.{self.client.__caller_info__()}({app_name})({app_id})")
            response = requests.delete( url, headers=self.client.headers)
            if response.status_code != 204:
                self.client.logger.warning(f"{self.__class__.__name__}.{self.client.__caller_info__()}({app_name})({app_id}) Error deleting app response code: {response.status_code}")
                return False
            return True
        
        def __owners_fetch__(self, id, function):
            next_uri = f"{self.client.graph_api_url}/v1.0/{function}/{id}/owners"
            # print(f"FETCH next_uri: {next_uri}")
            response = requests.get(next_uri, headers=self.client.headers)
            if response.status_code != 200:
                return None
            owners= response.json().get('value', [])
            return owners
        def owners_fetch_appregistration(self, app_id):
            return self.__owners_fetch__(app_id, "applications")
        def owners_fetch(self, service_principal_id):
            return self.__owners_fetch__(service_principal_id, "servicePrincipals")
        def owners_fetch_oids(self, service_principal_id):
            owners = self.__owners_fetch__(service_principal_id, "servicePrincipals")
            if owners is None:
                return None
            return [owner['id'] for owner in owners]

        ###################################################################################
        ## For the avoidance of doubt: while the user interface talks about "Enterprise Applications" and "App Registrations",
        ## Under the hood:
        ## - Enterprise Applications are Service Principals
        ## - App Registrations are Applications
        ##    In our case, I've called these to match the UI, but the functions are for the underlying objects
        ###################################################################################

        def __owners_add__(self, id, function, user_oids):
            ### owners can only be users, groups not an option (ugh...)
            ### also while would be nice to add multiple owners at once, it's not an option
            ### https://learn.microsoft.com/en-us/graph/api/serviceprincipal-post-owners?view=graph-rest-1.0&tabs=http    
            status = True
            current_owners = self.__owners_fetch__(id, function)
            if current_owners is None:
                current_owners = []
            # print(f"current_owners: {current_owners}")
            for user_oid in user_oids:
                if any(owner['id'] == user_oid for owner in current_owners):
                    self.client.logger.debug(f"{self.__class__.__name__}.{self.client.__caller_info__()}({id})({function})({user_oid}) is already an owner")
                    continue
                next_uri = f"{self.client.graph_api_url}/v1.0/{function}/{id}/owners/$ref"
                payload = { "@odata.id" : f"https://graph.microsoft.com/v1.0/directoryObjects/{user_oid}" }
                # print(f"next_uri: {next_uri}")
                # print(f"payload: {payload}")
                response = requests.post(next_uri, headers=self.client.headers, json=payload)
                if response.status_code == 204:
                    self.client.logger.info(f"{self.__class__.__name__}.{self.client.__caller_info__()}({id})({user_oid}) added owner")
                else:
                    self.client.logger.warning(f"{self.__class__.__name__}.{self.client.__caller_info__()}({id})({user_oid}) Error adding owner")
                    status = False
            return status
        def owners_add_appregistration(self, app_id, user_oids):
            return self.__owners_add__(app_id, "applications", user_oids)
        def owners_add(self, service_principal_id, user_oids):
            return self.__owners_add__(service_principal_id, "servicePrincipals", user_oids)

        def __owners_remove__(self, id, function, user_oids):
            status = True
            current_owners = self.__owners_fetch__(id, function)
            if current_owners is None:
                return True    ## nothing to do if no owners
            for user_oid in user_oids:
                if any(owner['id'] == user_oid for owner in current_owners):
                    next_uri = f"{self.client.graph_api_url}/v1.0/{function}/{id}/owners/{user_oid}/$ref"
                    response = requests.delete(next_uri, headers=self.client.headers)
                    if response.status_code == 204:
                        self.client.logger.info(f"{self.__class__.__name__}.{self.client.__caller_info__()}({id})({function})({user_oid}) removed owner")
                    else:
                        self.client.logger.warning(f"{self.__class__.__name__}.{self.client.__caller_info__()}({id})({function})({user_oid}) Error removing owner")
                        status = False
            return status
        def owners_remove_appregistration(self, app_id, user_oids):
            return self.__owners_remove__(app_id, "applications", user_oids)
        def owners_remove(self, service_principal_id, user_oids):
            return self.__owners_remove__(service_principal_id, "servicePrincipals", user_oids)

        def __rename__(self, id, function, new_name):
            next_uri = f"{self.client.graph_api_url}/v1.0/{function}/{id}"
            payload = { "displayName": new_name }
            response = requests.patch(next_uri, headers=self.client.headers, json=payload)
            if response.status_code != 204:
                return False
            return True
        def rename_appregistration(self, app_id, new_name):
            return self.__rename__(app_id, "applications", new_name)
        def rename(self, service_principal_id, new_name):
            return self.__rename__(service_principal_id, "servicePrincipals", new_name)
        
        def set_note(self, app, key, value):
            if self.client.__is_valid_uuid__(app):
                app_id = self.get_id(app)
            else:
                app_id = app
            if not app_id:
                self.client.logger.debug(f"{self.__class__.__name__}.{self.client.__caller_info__()}({app_id}) app_id required")
                return False
            
            # get the current notes field - this is a string value, we happen to put json into it
            next_uri = f"{self.client.graph_api_url}/v1.0/applications/{app_id}"
            response = requests.get(next_uri, headers=self.client.headers)
            if response.status_code != 200:
                self.client.logger.warning(f"{self.__class__.__name__}.{self.client.__caller_info__()}({app_id}) failed to get notes {response.status_code}/{response.json()}")
                return False
            current_info = response.json()
            current_notes_str = current_info.get("notes", "{}")

            if not current_notes_str:
                current_notes = {}
            else: 
                try:
                    current_notes = json.loads(current_notes_str)
                except json.JSONDecodeError:
                    current_notes = {"original_notes_string": current_notes_str}

            # (b) Update or add the key/value pair && convert back to a string
            current_notes[key] = value
            payload = {"notes": json.dumps(current_notes)}
            next_uri = f"{self.client.graph_api_url}/v1.0/applications/{app_id}"
            response = requests.patch(next_uri, headers=self.client.headers, json=payload)
            if response.status_code == 204:
                self.client.logger.debug(f"{self.__class__.__name__}.{self.client.__caller_info__()}({app_id}) note with ({key})/({value}) set")
            else:
                self.client.logger.warning(f"{self.__class__.__name__}.{self.client.__caller_info__()}({app_id}) note setting {response.status_code}/{response.json()}")
                return False
        
        def get_note(self, app):
            if self.client.__is_valid_uuid__(app):
                app_id = self.get_id(app)
            else:
                app_id = app
            self.client.logger.debug(f"{self.__class__.__name__}.{self.client.__caller_info__()}({app_id})")
            if not app_id:
                self.client.logger.debug(f"{self.__class__.__name__}.{self.client.__caller_info__()}({app_id}) app_id required")
                return None
            
            # get the current notes field - this is a string value, we happen to put json into it
            next_uri = f"{self.client.graph_api_url}/v1.0/applications/{app_id}"
            response = requests.get(next_uri, headers=self.client.headers)
            if response.status_code != 200:
                self.client.logger.warning(f"{self.__class__.__name__}.{self.client.__caller_info__()}({app_id}) failed to get notes {response.status_code}/{response.json()}")
                return None
            current_info = response.json()
            current_notes_str = current_info.get("notes", "{}")

            if not current_notes_str:
                current_notes = {}
            else: 
                try:
                    current_notes = json.loads(current_notes_str)
                except json.JSONDecodeError:
                    current_notes = {"original_notes_string": current_notes_str}
            return current_notes

        def confirm_note(self, app, key, value):
            if self.client.__is_valid_uuid__(app):
                app_id = self.get_id(app)
            else:
                app_id = app
            self.client.logger.debug(f"{self.__class__.__name__}.{self.client.__caller_info__()}({app_id}) {key} / {value}")
            current_notes = self.get_note(app_id)
            if current_notes is None:
                self.client.logger.debug(f"{self.__class__.__name__}.{self.client.__caller_info__()}({app_id}) no note found")
                return False
            if key in current_notes and current_notes[key] == value:
                self.client.logger.debug(f"{self.__class__.__name__}.{self.client.__caller_info__()}({app_id}) key/value matched")
                return True
            self.client.logger.debug(f"{self.__class__.__name__}.{self.client.__caller_info__()}({app_id}) key/value not matched")
            return False
    ###########################################################################################
    #################################### APPS #################################################
    ###########################################################################################

    ###########################################################################################
    #################################### GROUPS ###############################################
    ###########################################################################################
    class Groups:
        def __init__(self, client):
            self.client           = client
            self.cache            = {}
            self.groups_cache_dir = None
            self.groups_members_cache_dir = None
            if (self.client.cache_dir is not None):
                self.groups_cache_dir         = self.client.__mkdir_p__(f'{self.client.cache_dir}/entra_groups')
                self.groups_members_cache_dir = self.client.__mkdir_p__(f'{self.client.cache_dir}/entra_groups_members')

        def get_details(self, group):
            return self.client.__get_details__(group, "groups", self.cache, self.groups_cache_dir, "displayName")
        
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
        
        def get_id(self, group_name):
            group = self.get_details(group_name)
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
        
    ###########################################################################################
    #################################### GROUPS ###############################################
    ###########################################################################################
        
    ###########################################################################################
    #################################### PASSWWORD_SSO ########################################
    ###########################################################################################
    class PasswordSSO:
        ################################## PASSWORD_SSO FUNCTIONS #################################################
        # https://learn.microsoft.com/en-us/graph/api/user-getpasswordsinglesignoncredentials?view=graph-rest-beta&tabs=http
        # https://learn.microsoft.com/en-us/graph/api/group-getpasswordsinglesignoncredentials?view=graph-rest-beta&tabs=http
        ##
        ## NOTE: that the id returned from these if you have multiple credentials is the app_id
        ##
        def __init__(self, client):
            self.client = client

        def credential_get(self, oid, type):
            next_url = f"{self.client.graph_api_url}/beta/{type}/{oid}/getPasswordSingleSignOnCredentials"
            response = requests.post(next_url, headers=self.client.headers)
            if response.status_code != 200:
                self.client.logger.warning(f"Failed to get passwordless credentials for {type} {oid}")
                return None
            return response.json() 

        def credential_remove(self, credential_id, oid, type):
            next_url = f"{self.client.graph_api_url}/beta/{type}/{oid}/deletePasswordSingleSignOnCredentials"
            payload = { "id": credential_id }
            response = requests.post(next_url, headers=self.client.headers, json=payload)
            if response.status_code != 204:
                self.client.logger.warning(f"Failed to remove passwordless credentials for {type} {oid}")
                return False
            return True
    ###########################################################################################
    #################################### PASSWWORD_SSO ########################################
    ###########################################################################################

    ###########################################################################################
    #################################### DYNAMIC GROUPS #######################################
    ###########################################################################################
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
