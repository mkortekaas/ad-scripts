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

###########################################################################################
## THIS IS NOT IN USE - NEVER GOT THIS TO WORK ... sigh ms does not expose these

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
