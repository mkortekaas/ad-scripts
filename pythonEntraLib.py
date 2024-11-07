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

class EntraClient:
    def __init__(self, tenant_id, client_id, client_secret, required_scopes, graph_api_url, cache_dir=None):
        ## make sure that other modules are calling with same logger name
        self.logger          = logging.getLogger('__COMMONLOGGER__')
        self.tenant_id       = tenant_id
        self.client_id       = client_id
        self.client_secret   = client_secret
        self.required_scopes = required_scopes
        self.graph_api_url   = graph_api_url
        self.cache_dir       = cache_dir

        ## subclasses
        self.Users           = self.Users(self)
        self.Applications    = self.Applications(self)
        self.Groups          = self.Groups(self)
        self.PasswordSSO     = self.PasswordSSO(self)

        ## Now sign in and get the access token
        app = msal.ConfidentialClientApplication(
            client_id,
            authority=f"https://login.microsoftonline.com/{tenant_id}",
            client_credential=client_secret,
        )
        result = app.acquire_token_for_client(scopes=required_scopes)
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
        self.logger.info(f"FLUSHING CACHE in ({self.cache_dir})")
        os.system(f"rm -f {self.cache_dir}/entra*")

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
            headers=self.client.headers
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

        def get_details(self, email):
            if email is None:
                return None
            email = email.lower()
            if self.users_cache_dir is not None:
                email_file_name = f"{self.users_cache_dir}/{urllib.parse.quote(email, safe='')}"            
                if os.path.exists(email_file_name):
                    with open(email_file_name, "r") as f:
                        data = json.load(f)
                        return data
                email_failed_file_name = f"{self.users_cache_dir}/{urllib.parse.quote(email, safe='')}.failed"
                if os.path.exists(email_failed_file_name):
                    return None
                    
            next_uri = f"{self.client.graph_api_url}/v1.0/users/{email}"
            response = requests.get(next_uri, headers=self.client.headers)  
            if response.status_code == 200:
                data = response.json()
            else:
                self.client.logger.warning(f"{self.__class__.__name__}({email}) Failed to retrieve user info")
                if self.users_cache_dir is not None:
                    with open(email_failed_file_name, "w") as f:
                        f.write("FAILED")
                return None
            
            if self.users_cache_dir is not None:
                self.client.logger.debug(f"-e-e-e- Writing into disk cache: ({email})")
                with open(email_file_name, "w") as f:
                    json.dump(data, f)
            return data

        def get_oid(self, email):
            email = email.lower()
            if email in self.cache:
                return self.cache[email]
            data = self.get_details(email)
            if data is not None:
                oid = data.get("id")
                self.cache[email] = oid
                return oid
            return None
        
        def get_oids(self, user_emails):
            if not isinstance(user_emails, list):
                user_emails = [user_emails]
            user_emails = list(set(user_emails))  # Remove duplicates
            user_emails = [email.lower() for email in user_emails]  # Lowercase all email addresses
            for email in user_emails:
                self.get_oid(email)
            ## Note this will not return if the email does not exist in the cache
            return [self.cache.get(email) for email in user_emails if self.cache.get(email) is not None]

        def __str__(self):
            return f"{self.cache}"

        def __repr__(self):
            return f"{self.__class__.__name__}(graph_api_url={self.client.graph_api_url!r}, headers={self.client.headers!r}, cache={self.cache!r})"
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
            self.apps_cache_dir = None
            if (self.client.cache_dir is not None):
                self.apps_cache_dir = self.client.__mkdir_p__(f'{self.client.cache_dir}/entra_apps')
            if (self.client.cache_dir is not None):
                self.sp_cache_dir = self.client.__mkdir_p__(f'{self.client.cache_dir}/entra_service_principals')

        def get_details(self, app):
            if app is None:
                return None
            
            encoded_app_name = urllib.parse.quote(app)
            if self.client.__is_valid_uuid__(app):
                ## if we call it using the ID then the search for app name will not match format wise - thus do both as filter search
                # next_uri = f"{self.client.graph_api_url}/v1.0/applications/{app}"
                next_uri = f"{self.client.graph_api_url}/v1.0/applications?$filter=id eq '{app}'"
            else:
                next_uri = f"{self.client.graph_api_url}/v1.0/applications?$filter=displayName eq '{encoded_app_name}'"

            if self.apps_cache_dir is not None:
                app_file_name = f"{self.apps_cache_dir}/{urllib.parse.quote(app, safe='')}"
                if os.path.exists(app_file_name):
                    with open(app_file_name, "r") as f:
                        data = json.load(f)
                        return data

            response = requests.get(next_uri, headers=self.client.headers)
            if response.status_code != 200:
                self.client.logger.debug(f"{self.__class__.__name__}({app}) Failed to retrieve application information")
                return None

            my_app_response = response.json().get('value', [])
            if len(my_app_response) == 0:
                self.client.logger.debug(f"{self.__class__.__name__}({app}) not found")
                ## for apps we don't write failed
                return None
            
            my_app = my_app_response[0]
            if self.apps_cache_dir is not None:
                self.client.logger.debug(f"-a-a-a- Writing into disk cache: ({app})")
                with open(app_file_name, "w") as f:
                    json.dump(my_app, f)
            return my_app
        
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
            
        def get_service_principal_details(self, app_name):
            encoded_app_name = urllib.parse.quote(app_name)
            service_principal_url = f"{self.client.graph_api_url}/v1.0/servicePrincipals?$filter=displayName eq '{encoded_app_name}'"
            if self.apps_cache_dir is not None:
                sp_file_name = f"{self.sp_cache_dir}/{urllib.parse.quote(app_name, safe='')}"
                if os.path.exists(sp_file_name):
                    with open(sp_file_name, "r") as f:
                        data = json.load(f)
                        return data
            response = requests.get(service_principal_url, headers=self.client.headers)
            if response.status_code != 200:
                self.client.logger.debug(f"{self.__class__.__name__}({app_name}) Failed to retrieve service principal information")
                return None
            service_principal_info = response.json()
            if not service_principal_info["value"]:
                self.client.logger.debug(f"{self.__class__.__name__}({app_name}) Service principal not found")
                return None
            service_principal_id = service_principal_info["value"][0]["id"]
            self.client.logger.debug(f"{self.__class__.__name__}({app_name}) Service principal ID is {service_principal_id}")
            if self.apps_cache_dir is not None:
                self.client.logger.debug(f"-a-a-a- Writing into disk cache: ({app_name})")
                with open(sp_file_name, "w") as f:
                    json.dump(service_principal_info["value"][0], f)
            return service_principal_info["value"][0]
        
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
                self.client.logger.warning(f"{self.__class__.__name__}({service_principal_id})({group_id}) Error (1) deleting group from service principal response code: {response.status_code}")
                return False
            for value in response.json()['value']:
                if value['principalId'] == group_id:
                    next_uri = f"{self.client.graph_api_url}/v1.0/servicePrincipals/{service_principal_id}/appRoleAssignedTo/{value['id']}"
                    response = requests.delete(next_uri, headers=self.client.headers)
                    if response.status_code != 204:
                        self.client.logger.warning(f"{self.__class__.__name__}({service_principal_id})({group_id}) Error (2) deleting group from service principal response code: {response.status_code}")
                        return False
                    self.client.logger.info(f"{self.__class__.__name__}({service_principal_id})({group_id}) Group deleted from application")
                    return True
            self.client.logger.info(f"{self.__class__.__name__}({service_principal_id})({group_id}) Group not assigned to application")
            return False
        
        def get_users_groups(self, app_name, service_principal_id):
            self.client.logger.debug(f"{self.__class__.__name__}() Getting Users/Groups assigned to {app_name}")
            next_uri = f"{self.client.graph_api_url}/v1.0/servicePrincipals/{service_principal_id}/appRoleAssignedTo"
            response = requests.get(next_uri,headers=self.client.headers,)
            if response.status_code != 200:
                self.client.logger.info(f"{self.__class__.__name__}({app_name}) FAILURE_GROUP_APP Failed to retrieve users/groups assigned {response.status_code}")
                return None
            response_json = response.json()
            # logger.debug(json.dumps(response_json, indent=4))
            if "value" in response_json and len(response_json["value"]) > 0:
                return response_json["value"]
            self.client.logger.debug(f"{self.__class__.__name__}() No users/groups assigned to ({app_name}) ({service_principal_id})")
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
                    self.client.logger.debug(f"{self.__class__.__name__}({names}) - Role with description containing '{name}' already exists.")
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
                self.client.logger.debug(f"{self.__class__.__name__}({names}) new_app_role: {new_app_role}")

            if new_app_details != app_details:
                next_uri = f"{self.client.graph_api_url}/v1.0/applications/{app_id}"
                response = requests.patch(next_uri,headers=self.client.headers,json={"appRoles": new_app_details})
                if response.status_code == 204:
                    self.client.logger.debug(f"{self.__class__.__name__}({names}) New appRole added {app_id}")
                    return new_app_details
                self.client.logger.warning(f"{self.__class__.__name__}({names}) FAILURE_GROUP_APPROLE to add new appRole(s)")
                return None
            return app_details
        
        def __add_group__(self, group_name, app_name, app_id, app_details):
            service_principal_id = self.get_service_principal_id(app_name)
            existing_assignments = self.get_users_groups(app_name, service_principal_id)
            self.client.logger.debug(f"{self.__class__.__name__}({group_name}) existing_assignments: {existing_assignments}")
            if existing_assignments is None:
                self.client.logger.warning(f"{self.__class__.__name__}({group_name}) FAILURE_GROUP_APP Failed to retrieve existing assignments - WHY?")
                return False           
            if not isinstance(group_name, list):
                groups = [group_name]
            else:
                groups = group_name
            appRoleResponse = self.__add_role__(groups, app_id, app_details)
            if appRoleResponse is None:
                self.client.logger.warning(f"{self.__class__.__name__}({group_name}) FAILURE_GROUP_APPROLE Failed to add to {app_name}")
                return False
            for my_group_name in groups:
                group_id = self.client.Groups.get_id(my_group_name)
                if group_id is None:
                    self.client.logger.warning(f"{self.__class__.__name__}({group_name})({my_group_name}) FAILURE_GROUP_APP not found")
                    continue
                if any(assignment["principalId"] == group_id for assignment in existing_assignments):
                    self.client.logger.debug(f"{self.__class__.__name__}({group_name})({my_group_name}) is already attached to application {app_name}")
                    continue
                self.client.logger.debug(f"{self.__class__.__name__}({group_name})({my_group_name}) found with ID {group_id}")
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
                    self.client.logger.debug(f"{self.__class__.__name__}({group_name})({my_group_name}) Group added to {app_name}")
                else:
                    self.client.logger.warning(f"{self.__class__.__name__}({group_name})({my_group_name}) FAILURE_GROUP_APP Failed to add group to ({app_name}) - {response.status_code} - {add_group_body}")
                    return False
            return True

        def add_group(self, group_name, app_name, app_id, app_details):
            status = self.__add_group__(group_name, app_name, app_id, app_details)
            if not status:
                self.client.logger.warning(f"{self.__class__.__name__}({app_name}) FAILURE_GROUP_APP Failed to add group to - sleep for 15s and try again")
                time.sleep(15)
                status = self.__add_group__(group_name, app_name, app_id, app_details)
                if not status:
                    self.client.logger.warning(f"{self.__class__.__name__}({app_name}) FAILURE_GROUP_APP Failed to add group")
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
            self.client.logger.info (f"{self.__class__.__name__}({app_name})({app_id})")
            response = requests.delete( url, headers=self.client.headers)
            if response.status_code != 204:
                self.client.logger.warning(f"{self.__class__.__name__}({app_name})({app_id}) Error deleting app response code: {response.status_code}")
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
                    self.client.logger.debug(f"{self.__class__.__name__}({id})({function})({user_oid}) is already an owner")
                    continue
                next_uri = f"{self.client.graph_api_url}/v1.0/{function}/{id}/owners/$ref"
                payload = { "@odata.id" : f"https://graph.microsoft.com/v1.0/directoryObjects/{user_oid}" }
                # print(f"next_uri: {next_uri}")
                # print(f"payload: {payload}")
                response = requests.post(next_uri, headers=self.client.headers, json=payload)
                if response.status_code == 204:
                    self.client.logger.info(f"{self.__class__.__name__}({id})({user_oid}) added")
                else:
                    self.client.logger.warning(f"{self.__class__.__name__}({id})({user_oid}) Error adding owner")
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
                        self.client.logger.info(f"{self.__class__.__name__}({id})({function})({user_oid}) removed")
                    else:
                        self.client.logger.warning(f"{self.__class__.__name__}({id})({function})({user_oid}) Error removing owner")
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
                self.client.logger.debug(f"{self.__class__.__name__}({app_id}) app_id required")
                return False
            
            # get the current notes field - this is a string value, we happen to put json into it
            next_uri = f"{self.client.graph_api_url}/v1.0/applications/{app_id}"
            response = requests.get(next_uri, headers=self.client.headers)
            if response.status_code != 200:
                self.client.logger.warning(f"{self.__class__.__name__}({app_id}) failed to get notes {response.status_code}/{response.json()}")
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
                self.client.logger.debug(f"{self.__class__.__name__}({app_id}) note with ({key})/({value}) set")
            else:
                self.client.logger.warning(f"{self.__class__.__name__}({app_id}) note setting {response.status_code}/{response.json()}")
                return False
        
        def get_note(self, app):
            if self.client.__is_valid_uuid__(app):
                app_id = self.get_id(app)
            else:
                app_id = app
            self.client.logger.debug(f"{self.__class__.__name__}({app_id})")
            if not app_id:
                self.client.logger.debug(f"{self.__class__.__name__}({app_id}) app_id required")
                return None
            
            # get the current notes field - this is a string value, we happen to put json into it
            next_uri = f"{self.client.graph_api_url}/v1.0/applications/{app_id}"
            response = requests.get(next_uri, headers=self.client.headers)
            if response.status_code != 200:
                self.client.logger.warning(f"{self.__class__.__name__}({app_id}) failed to get notes {response.status_code}/{response.json()}")
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
            self.client.logger.debug(f"{self.__class__.__name__}({app_id}) {key} / {value}")
            current_notes = self.get_note(app_id)
            if current_notes is None:
                self.client.logger.debug(f"{self.__class__.__name__}({app_id}) no note found")
                return False
            if key in current_notes and current_notes[key] == value:
                self.client.logger.debug(f"{self.__class__.__name__}({app_id}) key/value matched")
                return True
            self.client.logger.debug(f"{self.__class__.__name__}({app_id}) key/value not matched")
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
            if (self.client.cache_dir is not None):
                self.groups_cache_dir = self.client.__mkdir_p__(f'{self.client.cache_dir}/entra_groups')

        def get_details(self, group):
            if group is None:
                return None
            if self.groups_cache_dir is not None:
                group_file_name = f"{self.groups_cache_dir}/{urllib.parse.quote(group, safe='')}"
                if os.path.exists(group_file_name):
                    with open(group_file_name, "r") as f:
                        data = json.load(f)
                        return data

            encoded_group_name = urllib.parse.quote(group)
            next_uri = f"{self.client.graph_api_url}/v1.0/groups?$filter=displayName eq '{encoded_group_name}'"
            response = requests.get(next_uri, headers=self.client.headers)
            if response.status_code != 200:
                self.client.logger.debug(f"{self.__class__.__name__} Failed to get group for '{group}': {response.text}")
                return None
            
            # this is a query so it comes back in a value record
            groups = response.json().get('value', [])
            if len(groups) == 0:
                self.client.logger.debug(f"{self.__class__.__name__} Failed to get group for '{group}': {response.text}")
                return None

            if self.groups_cache_dir is not None:
                self.client.logger.debug(f"-e-e-e- Writing into disk cache: ({group})")
                with open(group_file_name, "w") as f:
                    json.dump(groups[0], f)
            return groups[0]

        def get_id(self, group_name):
            group = self.get_details(group_name)
            if group:
                return group['id']
            return None
        
        def get_members(self, group_id):
            members = []
            next_uri = f"{self.client.graph_api_url}/v1.0/groups/{group_id}/members"
            while next_uri:
                response = requests.get(next_uri, headers=self.client.headers)
                if response.status_code == 200:
                    data = response.json()
                    members.extend([member['id'] for member in data.get('value', [])])
                    next_uri = data.get('@odata.nextLink')
                else:
                    self.client.logger.warning(f"{self.__class__.__name__} Failed to get members for group '{group_id}': {response.text}")
                    return []
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
                        self.client.logger.debug(f"{self.__class__.__name__}({group_id}) added {len(chunk)} users successfully.")
                        total_added += len(chunk)
                    else:
                        # logger but keep going)
                        self.client.logger.warning(f"{self.__class__.__name__}({group_id}) FAILURE_GROUP_USER failed to add {len(chunk)} users: {response.text}")
                return total_added
            return 0
        
        def add_users(self, group_id, user_oids):
            current_members = self.get_members(group_id)
            membership_list = []
            for user_oid in user_oids:
                if user_oid not in current_members:
                    membership_list.append(f"{self.client.graph_api_url}/v1.0/directoryObjects/{user_oid}")
            if len(membership_list) > 0:
                return self.__add_users__(group_id, membership_list)
            else:
                self.client.logger.debug(f"{self.__class__.__name__}({group_id}) No new users to add to group")
            return True
        
        def remove_users(self, group_id, user_oids):
            ## this works differently than the add - you can only remove one at a time
            current_members = self.get_members(group_id)
            removed_users   = False
            for user_oid in user_oids:
                if user_oid in current_members:
                    next_uri = f"{self.client.graph_api_url}/v1.0/groups/{group_id}/members/{user_oid}/$ref"
                    response = requests.delete(next_uri, headers=self.client.headers)
                    if response.status_code == 204:
                        self.client.logger.debug(f"{self.__class__.__name__}({group_id}) removed {user_oid} user successfully")
                        removed_users = True
                    else:
                        self.client.logger.warning(f"{self.__class__.__name__}({group_id}) FAILURE_GROUP_USER failed to remove {user_oid} user: {response.text}")
            if not removed_users:
                self.client.logger.debug(f"{self.__class__.__name__}({group_id}) No users to remove")
            return True
        
        def owners_fetch(self, group_id):
            url = f"{self.client.graph_api_url}/v1.0/groups/{group_id}/owners"
            response = requests.get(url, headers=self.client.headers)
            if response.status_code != 200:
                self.client.logger.info(f"{self.__class__.__name__}({group_id}) No group owners")
                return None
            return response.json()
        
        def owners_add(self, group_id, user_oids):
            group_owners = self.owners_fetch(group_id)
            if user_oids:
                for user_oid in user_oids:
                    if any(owner['id'] == user_oid for owner in group_owners['value']):
                        self.client.logger.debug(f"{self.__class__.__name__}({group_id}) {user_oid} is already an owner")
                        continue
                    url = f"{self.client.graph_api_url}/v1.0/groups/{group_id}/owners/$ref"
                    payload = { "@odata.id": f"{self.client.graph_api_url}/v1.0/users/{user_oid}" }
                    response = requests.post(url, headers=self.client.headers, json=payload)
                    if response.status_code != 204:
                        self.client.logger.warning(f"{self.__class__.__name__}({group_id}) {user_oid} Error adding owner to group")
                    else:
                        self.client.logger.info(f"{self.__class__.__name__}({group_id}) {user_oid} is now a group owner")
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
                            self.client.logger.warning(f"{self.__class__.__name__}({group_id}) {user_oid} Error removing owner from group")
                        else:
                            self.client.logger.info(f"{self.__class__.__name__}({group_id}) {user_oid} removed as group owner")
            return True
        
        def update_name(self, group_id, modified_group_name):
            url = f"{self.client.graph_api_url}/v1.0/groups/{group_id}"
            payload = { "displayName": modified_group_name }
            response = requests.patch(url, headers=self.client.headers, json=payload)
            if response.status_code != 204:
                self.client.logger.warning(f"{self.__class__.__name__}({group_id})({modified_group_name}) Error updating group name response: ({response.text})")
                return False
            self.client.logger.info(f"{self.__class__.__name__}({group_id})({modified_group_name}) Updated group name)")
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
                    self.client.logger.debug(f"{self.__class__.__name__}({group_name}) already exists.")
                    return groups[0]  # Return the existing group
                else:
                    self.client.logger.debug(f"{self.__class__.__name__}({group_name}) Creating new group.")
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
                        self.client.logger.debug(f"{self.__class__.__name__}({group_name}) created successfully.")
                        return create_response.json()
                    else:
                        self.client.logger.warning(f"{self.__class__.__name__}({group_name}) FAILURE_GROUP_CREATE {create_response.text}")
                        return None
            else:
                self.client.logger.warning(f"{self.__class__.__name__}({group_name}) FAILURE_GROUP_CREATE Failed to check if group exists: {response.text}")
                return None
            
        def create(self, group_name):
            entra_group_info = self.get_details(group_name)
            if entra_group_info is None:
                self.client.logger.info(f"{self.__class__.__name__}({group_name}) Creating entra group")
                if not self.__create__(group_name):
                    self.client.logger.warning(f"{self.__class__.__name__}({group_name}) FAILURE_GROUP_CREATE")
                    return None
            else:
                self.client.logger.debug(f"{self.__class__.__name__}({group_name}) Entra group exists")
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
                    self.client.logger.debug(f"{self.__class__.__name__}({dyn_group_name}) already exists.")
                    return groups[0]  # Return the existing group
                else:
                    group_ids_list = [ app_group_id]
                    for additional_group_name in additional_group_names:
                        additional_group_id = self.client.Groups.get_id(additional_group_name)
                        if additional_group_id:
                            group_ids_list.append(additional_group_id)
                    group_ids_str = ', '.join([f"'{gid}'" for gid in group_ids_list])
                    updated_membership_rule = f"user.memberOf -any (group.objectId -in [{group_ids_str}])"
                    self.client.logger.debug(f"{self.__class__.__name__}({dyn_group_name}) Creating new group.")
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
                        self.client.logger.debug(f"{self.__class__.__name__}({dyn_group_name}) SUCCESS_GROUP_DYNAMIC_CREATE")
                        return create_response.json()
                    else:
                        self.client.logger.warning(f"{self.__class__.__name__}({dyn_group_name}) FAILURE_GROUP_DYNAMIC_CREATE {create_response.text}")
                        return None
            else:
                self.client.logger.warning(f"{self.__class__.__name__}({dyn_group_name}) FAILURE_GROUP_DYNAMIC_CREATE Failed to check if group exists: {response.text}")
                return None

        def create(self, dyn_group_name, app_group_name, additional_group_names):
            app_group_info = self.client.Groups.get_id(app_group_name)
            if app_group_info is None:
                self.client.logger.warning(f"{self.__class__.__name__}({dyn_group_name}) FAILURE_GROUP_DYNAMIC_CREATE app_group_name must exist prior")
                return None
            entra_group_info = self.client.Groups.get_info(dyn_group_name)
            if entra_group_info is None:
                self.client.logger.info(f"{self.__class__.__name__}({dyn_group_name}) Creating dynamic entra group")
                if not self.__create__(dyn_group_name, app_group_info['id'], additional_group_names):
                    self.client.logger.warning(f"{self.__class__.__name__}({dyn_group_name}) FAILURE_GROUP_DYNAMIC_CREATE")
                    return None
            else:
                self.client.logger.debug(f"{self.__class__.__name__}({dyn_group_name}) Entra dynamic group exists")
            return dyn_group_name

        def add_group(self, dyn_group_id, group_id):
            # Step 1: Get the current group details
            group_details_url = f"{self.client.graph_api_url}/v1.0/groups/{dyn_group_id}"
            response = requests.get(group_details_url, headers=self.client.headers)
            if response.status_code != 200:
                self.client.logger.warning(f"{self.__class__.__name__}({dyn_group_id}) FAILURE_GET_GROUP_DETAILS {response.text}")
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
                self.client.logger.debug(f"{self.__class__.__name__}({dyn_group_id}) Group {group_id} already present in membership rule")
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
                self.client.logger.warning(f"{self.__class__.__name__}({dyn_group_id}) FAILURE_UPDATE_MEMBERSHIP_RULE {update_response.text}")
                return None
            self.client.logger.debug(f"{self.__class__.__name__}({dyn_group_id}) SUCCESS_UPDATE_MEMBERSHIP_RULE")
            return True
    ###########################################################################################
    #################################### DYNAMIC GROUPS #######################################
    ###########################################################################################
