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
import uuid
import time

class Applications:
    def __init__(self, client):
        self.client           = client
        self.cache            = {}
        self.sp_cache         = {}
        self.apps_cache_dir = None
        self.sp_cache_dir   = None
        if (self.client.cache_dir is not None):
            self.apps_cache_dir = self.client.__mkdir_p__(f'{self.client.cache_dir}/entra_apps')
            self.sp_cache_dir   = self.client.__mkdir_p__(f'{self.client.cache_dir}/entra_service_principals')

    def get_details(self, app, FORCE_NEW=False):
        return self.client.__get_details__(app, "applications", self.cache, self.apps_cache_dir, "displayName", FORCE_NEW)
    
    def get_all(self, STOP_LIMIT=None):
        return self.client.__get_all__("applications", self.cache, self.apps_cache_dir, 'displayName', STOP_LIMIT)

    def get_service_principal_details(self, app, FORCE_NEW=False):
        return self.client.__get_details__(app, "servicePrincipals", self.sp_cache, self.sp_cache_dir, "displayName", FORCE_NEW)
        
    def get_all_service_principals(self, STOP_LIMIT=None):
        return self.client.__get_all__("servicePrincipals", self.sp_cache, self.sp_cache_dir, 'displayName', STOP_LIMIT)
    
    def get_id(self, app_name, FORCE_NEW=False):
        app_info = self.get_details(app_name, FORCE_NEW)
        if app_info is None:
            return None
        return app_info.get("id")
    
    def get_aid(self, app_name, FORCE_NEW=False):
        app_info = self.get_details(app_name, FORCE_NEW)
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
