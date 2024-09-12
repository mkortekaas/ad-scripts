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

###################################################################################
def setPasswordSSO(app_id, app_name, sso_url, headers):
    ## no idea how to make this work
    print(f"Setting password-based SSO for {app_name} with URL {sso_url}")
    ## this is hint from chat-gpt but no worky
    # body = {
    #     "preferredSingleSignOnMode": "password",
    #     "passwordSingleSignOn": {
    #         "fieldValues": [
    #             {
    #                 "name": "loginUrl",
    #                 "value": sso_url
    #             }
    #         ]
    #     }
    # }
    # response = requests.patch(f"{graph_api_url}/v1.0/applications/{app_id}", headers=headers, json=body)
    # if response.status_code == 204:
    #     print(f"Application {app_name} is now set to password-based SSO")
    # else:
    #     print(f"ERROR Failed to set SSO mode for application {app_name}")
    #     print(f"URI: {graph_api_url}/{app_id}")
    #     print(json.dumps(body, indent=4))
    #     print(json.dumps(response.json(), indent=4))
    #     exit (1);

###################################################################################
def getAppUsersGroups(app_id, app_name, headers):
    ## no idea how to make this work
    print(f"Getting Users/Groups assigned to {app_name}")

###################################################################################
def addAppRole(app_name, app_id, app_details, headers, DEBUG): 
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
        print(f"New appRole added to application {app_name}")
    else:
        print(f"ERROR Failed to add new appRole to application {app_name}")
        print(f"URI: {next_uri}")
        print(json.dumps(response.json(), indent=4))
        exit(1)
    return appRoleUUID

###################################################################################
def getAppDetails(app_name, headers):
    ## this works
    next_uri = f"{graph_api_url}/v1.0/applications?$filter=displayName eq '{app_name}'"
    response = requests.get(next_uri, headers=headers)
    if response.status_code != 200:
        print("Failed to retrieve application information")
        print(f"URI: {next_uri}")
        print(json.dumps(response.json(), indent=4))
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
        print("ERROR Failed to retrieve detailed application information")
        print(f"URI: {next_uri}")
        print(json.dumps(response.json(), indent=4))
        exit(1)

    app_details = response.json()
    if DEBUG:
        print("============================== DEBUG APP_DETAILS =======================================")
        print(json.dumps(app_details, indent=4))
        print("============================== END DEBUG APP_DETAILS =======================================")
    return app_info, app_details, app_id, app_aid

###################################################################################
def getToken(tenant_id, client_id, client_secret, DEBUG):
    ## this works
    app = msal.ConfidentialClientApplication(
        client_id,
        authority=f"https://login.microsoftonline.com/{tenant_id}",
        client_credential=client_secret,
    )
    result = app.acquire_token_for_client(scopes=required_scopes)
    if "access_token" not in result:
        print("Failed to acquire token")
        print(result.get("error"))
        print(result.get("error_description"))
        exit()

    access_token = result["access_token"]

    if DEBUG:
        print("============================== DEBUG JWT =======================================")
        decoded_token = jwt.decode(access_token, options={"verify_signature": False})
        print(json.dumps(decoded_token, indent=4))
        scopes = decoded_token.get("scp", "No scopes found")
        print(f"Scopes: {scopes}")
        print("============================== END DEBUG JWT =======================================")

    return access_token

###################################################################################
def addGroupToApp(group_name, app_name, app_id, app_aid, appRoleUUID, service_principal_id, headers, DEBUG):
    ## This works
    next_uri = f"{graph_api_url}/v1.0/groups?$filter=displayName eq '{group_name}'"
    response = requests.get(
        next_uri,
        headers=headers
    )
    if response.status_code != 200:
        print("ERROR: Failed to retrieve group information")
        print(f"URI: {next_uri}")
        print(json.dumps(response.json(), indent=4))
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
        print(f"Group {group_name} added to application {app_name}")
    else:
        print(f"ERROR Failed to add group {group_name} to application {app_name}")
        print(f"URI: {next_uri}")
        print(json.dumps(add_group_body, indent=4))
        print(json.dumps(response.json(), indent=4))
        exit(1)
    return group_id

###################################################################################
def getAppServicePrincipal(app_name, headers, DEBUG):
    ## this works
    service_principal_url = f"{graph_api_url}/v1.0/servicePrincipals?$filter=displayName eq '{app_name}'"
    response = requests.get(service_principal_url, headers=headers)
    if response.status_code != 200:
        print("Failed to retrieve service principal information")
        print(json.dumps(response.json(), indent=4))
        exit(1)

    if DEBUG:
        print("============================== DEBUG APP SVC PRINCIPAL =======================================")
        print(json.dumps(response.json(), indent=4))
        print("============================== END DEBUG APP SVC PRINCIPAL =======================================")

    service_principal_info = response.json()
    if not service_principal_info["value"]:
        print(f"Service principal for application {app_name} not found")
        exit(1)

    # Extract the service principal ID
    service_principal_id = service_principal_info["value"][0]["id"]
    print(f"Service principal ID for application {app_name} is {service_principal_id}")
    return service_principal_id

###################################################################################
def updateGroupCredentials(group_id, appRoleUUID, service_principal_id, username, password, headers, DEBUG):
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
        if DEBUG:
            print("============================== DEBUG UPDATED CREDENTIALS =======================================")
            print(json.dumps(response.json(), indent=4))
            print("============================== END DEBUG UPDATED CREDENTIALS =======================================")
    else:
        print(f"ERROR Failed to update credentials for group {group_id}")
        print(json.dumps(response.json(), indent=4))
        exit(1)    

###################################################################################
# Define your Azure AD tenant ID, client ID, and client secret
## THIS has to be for an application, not a user and that user has to be given the scopes:
##      Application.ReadWrite.All, User.Read, Directory.Read.All
parser = argparse.ArgumentParser(description="Set up an application for password-based SSO")
parser.add_argument("--tenant_id", help="Azure AD tenant ID", default=os.getenv("TENANT_ID"))
parser.add_argument("--client_id", help="Azure AD client ID", default=os.getenv("CLIENT_ID"))
parser.add_argument("--client_secret", help="Azure AD client secret", default=os.getenv("CLIENT_SECRET"))
parser.add_argument("--DEBUG", help="Enable debug output", action="store_true")
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

access_token = getToken(tenant_id, client_id, client_secret, DEBUG)
headers = {
    "Authorization": f"Bearer {access_token}",
    "Content-Type": "application/json",
}

# basic information about the app && enterprise app (aka: service principal)
(app_info, app_details, app_id, app_aid) = getAppDetails(app_name, headers)
service_principal_id = getAppServicePrincipal(app_name, headers, DEBUG)

setPasswordSSO(app_id, app_name, sso_url, headers)

## we have already done this a bunch of times - just hardcoding during testing
appRoleUUID = addAppRole(app_name, app_id, app_details, headers, DEBUG)

## we will actually need to create groups and populate with users - but for now, just add an existing group
group_id = addGroupToApp(group_name, app_name, app_id, app_aid, appRoleUUID, service_principal_id, headers, DEBUG)

## here we get the users && groups for the app so we can set the password for them
getAppUsersGroups(app_id, app_name, headers)

## now we need to set the password on a group
username = "new_username"
password = "new_password"
updateGroupCredentials(group_id, appRoleUUID, service_principal_id, username, password, headers, DEBUG)


