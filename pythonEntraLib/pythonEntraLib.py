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
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from azure.identity import AzureCliCredential

from .pythonEntraLib_users import Users
from .pythonEntraLib_applications import Applications
from .pythonEntraLib_groups import Groups
from .pythonEntraLib_passwordSSO import PasswordSSO

class EntraClient:
    def __init__(self, tenant_id, client_id=None, client_secret=None, required_scopes=None, graph_api_url=None, cache_dir=None, FLUSH=False):
        ## make sure that other modules are calling with same logger name
        self.logger          = logging.getLogger('__COMMONLOGGER__')
        self.tenant_id       = tenant_id
        self.client_id       = client_id
        self.client_secret   = client_secret
        self.required_scopes = required_scopes if required_scopes else ["https://graph.microsoft.com/.default"]
        self.graph_api_url   = graph_api_url if graph_api_url else "https://graph.microsoft.com"
        self.cache_dir = f"{cache_dir}/{tenant_id}" if cache_dir else None

        if FLUSH:
            self.flush()

        ## subclasses
        self.Users           = Users(self)
        self.Applications    = Applications(self)
        self.Groups          = Groups(self)
        self.PasswordSSO     = PasswordSSO(self)
        self.authenticate()

    def authenticate(self):
        ## 
        ## If your loops are very long you will eventually get a token that expires and we don't reliably check for that
        ##  elsewhere in this module to refetch a new token. Probably should add that but for now just call authentiate() every
        ##  so often
        ##
        self.logger.info("Authenticating with MS_GRAPH and getting valid token")
        
        # Try service principal authentication first if client_secret is provided
        if self.client_secret and self.client_id:
            try:
                self.logger.info("Attempting service principal authentication")
                app = msal.ConfidentialClientApplication(
                    self.client_id,
                    authority=f"https://login.microsoftonline.com/{self.tenant_id}",
                    client_credential=self.client_secret,
                )
                result = app.acquire_token_for_client(scopes=self.required_scopes)
                if "access_token" in result:
                    self.access_token = result["access_token"]
                    self.headers = {
                        "Authorization": f"Bearer {result['access_token']}",
                        "Content-Type": "application/json",
                    }
                    self.logger.info("Service principal authentication successful")
                    return
                else:
                    self.logger.warning(f"Service principal authentication failed: {result.get('error_description')}")
            except Exception as e:
                self.logger.warning(f"Service principal authentication failed with exception: {str(e)}")
        
        # Fall back to Azure CLI authentication
        try:
            self.logger.info("Attempting Azure CLI authentication")
            credential = AzureCliCredential()
            token = credential.get_token("https://graph.microsoft.com/.default")
            self.access_token = token.token
            self.headers = {
                "Authorization": f"Bearer {token.token}",
                "Content-Type": "application/json",
            }
            self.logger.info("Azure CLI authentication successful")
            return
        except Exception as e:
            self.logger.critical(f"Azure CLI authentication failed: {str(e)}")
        
        # If both methods fail, raise an exception
        self.logger.critical("All authentication methods failed")
        raise Exception("Failed to acquire token using either service principal or Azure CLI authentication")

    def flush(self):
        self.logger.info(f"FLUSHING ENTRA CACHE in ({self.cache_dir})")
        os.system(f"rm -rf {self.cache_dir}/entra*")

    def get_log_file(self, script_name):
        if self.cache_dir is None: return None
        if not os.path.exists(f"{self.cache_dir}/logs"):
            os.makedirs(f"{self.cache_dir}/logs")
        return f"{self.cache_dir}/logs/{script_name}.{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

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
            ## if change here - change in bulk below
            query["$select"] = 'businessPhones,displayName,givenName,jobTitle,mail,mobilePhone,officeLocation,preferredLanguage,surname,userPrincipalName,id,proxyAddresses,mailNickname,accountEnabled,signInActivity,lastPasswordChangeDateTime'
            
        response = requests.get(next_uri, headers=self.headers, params=query)
        if response.status_code != 200:
            self.logger.debug(f"{self.__class__.__name__}.{self.__caller_info__()}({my_request}) Failed to retrieve {my_type} ({response.json()})")
            return None

        my_response = response.json().get('value', [])
        if len(my_response) == 0:
            my_cache[my_request] = None   # we still cache but just in memory
            self.logger.debug(f"{self.__class__.__name__}.{self.__caller_info__()}({my_request}) not found")
            return None
        
        my_item = my_response[0]
        if my_cache_dir is not None:
            id_filename  = f"{my_cache_dir}/{urllib.parse.quote(my_item['id'], safe='').lower()}.json"
            self.__write_to_cache__(id_filename, my_item)

        my_cache[my_item['id']]   = my_item
        if my_type == "users":
            my_cache[my_item[my_key].lower()] = my_item
        else:
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
                        self.logger.debug(f"STOP_LIMIT reached for {my_type} ({my_limit})")
                        break
                    count += 1
                    data = self.__load_json_file__(json_file)
                    my_list.append(data)
                    my_cache[data['id']]   = data
                    if my_type == "users":
                        my_cache[data[my_key].lower()] = data
                    else:
                        my_cache[data[my_key]] = data
                return my_list
            
        ## TODO: implement stoplimit properly
        next_uri = f"{self.graph_api_url}/v1.0/{my_type}"
        query = {}
        if my_type == "users":
            ## if change here - change in single above
            query["$select"] = 'businessPhones,displayName,givenName,jobTitle,mail,mobilePhone,officeLocation,preferredLanguage,surname,userPrincipalName,id,proxyAddresses,mailNickname,accountEnabled,signInActivity,lastPasswordChangeDateTime'
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
