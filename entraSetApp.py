#!/usr/bin/env python3

# MIT License
# 
# Copyright (c) 2024 Mark Kortekaas
# 
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
# 
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
# 
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import msal
import requests
import argparse
import json
import jwt
import os
import uuid
import logging

###################################################################################
def setPasswordSSO(app_id, app_name, service_principal_id, sso_url, headers):
    ## no idea how to make this work
    print(f"\tSetting password-based SSO for {app_name} with URL {sso_url}")

    ### chatgpt recommended this but this does not work:
    # body = { "web": { "redirectUris": [] } }
    # next_uri = f"{graph_api_url}/v1.0/applications/{app_id}"

    # tried both passwordSingleSignOn and passwordSingleSignOnSettings - both throw a  "Invalid property 'passwordSingleSignOnSettings'.", error
    body = {
        "preferredSingleSignOnMode": "password",
        "passwordSingleSignOnSettings": {
            "fieldValues": [
                {
                    "name": "loginUrl",
                    "value": sso_url
                }
            ]
        }
    }
    next_uri = f"{graph_api_url}/v1.0/servicePrincipals/{service_principal_id}"
    response = requests.patch(next_uri, headers=headers, json=body)
    if response.status_code == 204:
        print(f"\t{app_name} is now set to password-based SSO")
    else:
        logging.error(f"Failed to set SSO mode for application {app_name}")
        logging.error(f"URI: {next_uri}")
        logging.error(json.dumps(body, indent=4))
        logging.error(json.dumps(response.json(), indent=4))
        exit (1)

###################################################################################
def getAppUserAccessURL(app_name, app_id, service_principal_id, tenant_id, headers):
    ## While I'd love to have this be a call, doesn't appear we can get this info from the API (??) but the pattern seems to always be:
    user_access_url = f"https://launcher.myapps.microsoft.com/api/signin/{app_id}?tenantId={tenant_id}"
    print(f"\taccess URL for {app_name}: {user_access_url}")
    return user_access_url

###################################################################################
def getAppUsersGroups(app_id, app_aid, app_name, service_principal_id, headers):
    print(f"\tGetting Users/Groups assigned to {app_name}")
    next_uri = f"{graph_api_url}/v1.0/servicePrincipals/{service_principal_id}/appRoleAssignedTo"
    response = requests.get(
        next_uri,
        headers=headers,
    )
    if response.status_code != 200:
        logging.error("Failed to retrieve users/groups assigned to application")
        logging.error(f"URI: {next_uri}")
        logging.error(json.dumps(response.json(), indent=4))
        exit(1)

    response_json = response.json()
    if "value" in response_json and len(response_json["value"]) > 0:
        return response_json["value"]
    else:
        print("No users/groups assigned to the application")
        return []


###################################################################################
def addAppRole(app_name, app_id, app_details, headers): 
    ## this works
    appRoleUUID = str(uuid.uuid4())
    new_app_role = {
        "id": appRoleUUID,  # Generate a unique GUID for this role
        "allowedMemberTypes": ["User"],  # only works with User as option
        "description": f"Entra App Role for {app_name}",
        "displayName": f"Entra App Role for {app_name}",
        "isEnabled": True,
        "value": f"newRoleValue-{appRoleUUID}"
    }
    app_details["appRoles"].append(new_app_role)
    next_uri = f"{graph_api_url}/v1.0/applications/{app_id}"
    response = requests.patch(
        next_uri,
        headers=headers,
        json={"appRoles": app_details["appRoles"]}
    )
    if response.status_code == 204:
        print(f"\tNew appRole added to application {app_name}")
    else:
        logging.error(f"Failed to add new appRole to application {app_name}")
        logging.error(f"URI: {next_uri}")
        logging.error(json.dumps(response.json(), indent=4))
        exit(1)
    return appRoleUUID

###################################################################################
def getAppDetails(app_name, headers):
    ## this works
    next_uri = f"{graph_api_url}/v1.0/applications?$filter=displayName eq '{app_name}'"
    response = requests.get(next_uri, headers=headers)
    if response.status_code != 200:
        logging.error("Failed to retrieve application information")
        logging.error(f"URI: {next_uri}")
        logging.error(json.dumps(response.json(), indent=4))
        exit(1)

    app_info = response.json()
    if not app_info["value"]:
        print(f"Application {app_name} not found")
        exit(1)

    app_id = app_info["value"][0]["id"]
    app_aid = app_info["value"][0]["appId"]
    print(f"Application {app_name} found with ID {app_id} and AppID {app_aid}")

    # Retrieve detailed application information
    next_uri = f"{graph_api_url}/v1.0/applications/{app_id}"
    response = requests.get(next_uri, headers=headers)
    if response.status_code != 200:
        logging.error("Failed to retrieve detailed application information")
        logging.error(f"URI: {next_uri}")
        logging.error(json.dumps(response.json(), indent=4))
        exit(1)

    app_details = response.json()
    logging.debug("============================== DEBUG APP_DETAILS =======================================")
    logging.debug(json.dumps(app_details, indent=4))
    logging.debug("============================== END DEBUG APP_DETAILS =======================================")
    return app_info, app_details, app_id, app_aid

###################################################################################
def getToken(tenant_id, client_id, client_secret):
    ## this works
    app = msal.ConfidentialClientApplication(
        client_id,
        authority=f"https://login.microsoftonline.com/{tenant_id}",
        client_credential=client_secret,
    )
    result = app.acquire_token_for_client(scopes=required_scopes)
    if "access_token" not in result:
        logging.error("Failed to acquire token")
        logging.error(result.get("error"))
        logging.error(result.get("error_description"))
        exit()

    access_token = result["access_token"]
    logging.debug("============================== DEBUG JWT =======================================")
    decoded_token = jwt.decode(access_token, options={"verify_signature": False})
    logging.debug(json.dumps(decoded_token, indent=4))
    scopes = decoded_token.get("scp", "No scopes found")
    logging.debug(f"Scopes: {scopes}")
    logging.debug("============================== END DEBUG JWT =======================================")

    return access_token

###################################################################################
def addGroupToApp(group_name, app_name, app_id, app_aid, appRoleUUID, service_principal_id, headers):
    ## This works
    next_uri = f"{graph_api_url}/v1.0/groups?$filter=displayName eq '{group_name}'"
    response = requests.get(
        next_uri,
        headers=headers
    )
    if response.status_code != 200:
        logging.error("Failed to retrieve group information")
        logging.error(f"URI: {next_uri}")
        logging.error(json.dumps(response.json(), indent=4))
        exit (1)

    group_info = response.json()
    if not group_info["value"]:
        print(f"Group {group_name} not found")
        exit(1)

    group_id = group_info["value"][0]["id"]
    print(f"Group {group_name} found with ID {group_id}")

    add_group_body = {
        # "@odata.id": f"{graph_api_url}/v1.0/groups/{group_id}"
        "principalId": group_id,
        "resourceId": service_principal_id,  ## service principal ID
        "appRoleId": appRoleUUID
    }
    next_uri = f"{graph_api_url}/v1.0/groups/{group_id}/appRoleAssignments"
    response = requests.post(
        next_uri,
        headers=headers,
        json=add_group_body
    )
    if response.status_code == 201:
        print(f"\tGroup {group_name} added to application {app_name}")
    else:
        logging.error(f"Failed to add group {group_name} to application {app_name}")
        logging.error(f"URI: {next_uri}")
        logging.error(json.dumps(add_group_body, indent=4))
        logging.error(json.dumps(response.json(), indent=4))
        exit(1)
    return group_id

###################################################################################
def getAppServicePrincipal(app_name, headers):
    ## this works
    service_principal_url = f"{graph_api_url}/v1.0/servicePrincipals?$filter=displayName eq '{app_name}'"
    response = requests.get(service_principal_url, headers=headers)
    if response.status_code != 200:
        logging.error("Failed to retrieve service principal information")
        logging.error(json.dumps(response.json(), indent=4))
        exit(1)

    logging.debug("============================== DEBUG APP SVC PRINCIPAL =======================================")
    logging.debug(json.dumps(response.json(), indent=4))
    logging.debug("============================== END DEBUG APP SVC PRINCIPAL =======================================")

    service_principal_info = response.json()
    if not service_principal_info["value"]:
        logging.error(f"Service principal for application {app_name} not found")
        exit(1)

    # Extract the service principal ID
    service_principal_id = service_principal_info["value"][0]["id"]
    print(f"\tService principal ID for application {app_name} is {service_principal_id}")
    return service_principal_id

###################################################################################
def updateGroupCredentials(group_id, appRoleUUID, service_principal_id, principal_display_name, username, password, headers):
    print(f"\tUpdating credentials for group {group_id} for the {principal_display_name} user")
    ### THIS NO WORKING
    credentials = {
        "principalId": group_id,
        "resourceId": service_principal_id,
        "appRoleId": appRoleUUID,
        "username": username,
        "password": password
    }
    
    # Make the request to update the credentials
    update_url = f"{graph_api_url}/v1.0/servicePrincipals/{service_principal_id}/appRoleAssignments/{group_id}"
    response = requests.patch(update_url, headers=headers, json=credentials)
    
    if response.status_code == 200:
        print(f"Credentials updated for group {group_id}")
        logging.debug("============================== DEBUG UPDATED CREDENTIALS =======================================")
        logging.debug(json.dumps(response.json(), indent=4))
        logging.debug("============================== END DEBUG UPDATED CREDENTIALS =======================================")
    else:
        logging.error(f"Failed to update credentials for group {group_id}")
        logging.error(json.dumps(response.json(), indent=4))
        exit(1)    

###################################################################################
# Define your Azure AD tenant ID, client ID, and client secret
## THIS has to be for an application, not a user and that user has to be given the scopes:
##      Application.ReadWrite.All, User.Read, Directory.Read.All
parser = argparse.ArgumentParser(description="Set up an application for password-based SSO")
parser.add_argument("--tenant_id", help="Azure AD tenant ID", default=os.getenv("TENANT_ID"))
parser.add_argument("--client_id", help="Azure AD client ID", default=os.getenv("CLIENT_ID"))
parser.add_argument("--client_secret", help="Azure AD client secret", default=os.getenv("CLIENT_SECRET"))
parser.add_argument("--DEBUG", help="Enable debug output", action="store_true", default=False)
parser.add_argument("--app_name", help="Application name", default=os.getenv("APP_NAME"))
parser.add_argument("--sso_url", help="SSO URL", default=os.getenv("SSO_URL"))
parser.add_argument("--group_name", help="GROUP NAME", default=os.getenv("GROUP_NAME"))

args = parser.parse_args()

# variables
required_scopes = ["https://graph.microsoft.com/.default"]
graph_api_url = f"https://graph.microsoft.com"
tenant_id = args.tenant_id
client_id = args.client_id
client_secret = args.client_secret
DEBUG = args.DEBUG
app_name = args.app_name
sso_url = args.sso_url
group_name = args.group_name

## set this to DEBUG if you want more details from the https request calls
if DEBUG:
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
else:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

access_token = getToken(tenant_id, client_id, client_secret)
headers = {
    "Authorization": f"Bearer {access_token}",
    "Content-Type": "application/json",
}

# basic information about the app && enterprise app (aka: service principal)
(app_info, app_details, app_id, app_aid) = getAppDetails(app_name, headers)
service_principal_id = getAppServicePrincipal(app_name, headers)

user_access_url = getAppUserAccessURL(app_name, app_id, service_principal_id, tenant_id, headers)

## we have already done this a bunch of times - just hardcoding during testing
appRoleUUID = addAppRole(app_name, app_id, app_details, headers, DEBUG)

## we will actually need to create groups and populate with users - but for now, just add an existing group
group_id = addGroupToApp(group_name, app_name, app_id, app_aid, appRoleUUID, service_principal_id, headers, DEBUG)

## here we get the users && groups for the app so we can set the password for them
assigned_users_groups = getAppUsersGroups(app_id, app_aid, app_name, service_principal_id, headers)

## now we need to set the password on a group
username = "new_username"
password = "new_password"
for item in assigned_users_groups:
    # item is a json object with the following keys we can use: id, deletedDateTime, appRoleId, createdDateTime, principalDisplayName, principalId, principalType, resourceDisplayName, resourceId
    principal_display_name = item.get("principalDisplayName")
    updateGroupCredentials(group_id, appRoleUUID, service_principal_id, principal_display_name, username, password, headers)

