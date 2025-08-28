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
    
    def reset_password(self, id):
        if id is None: return False
        user_data = self.get_details(id)
        if user_data is None: return False
        if 'accountEnabled' in user_data and user_data['accountEnabled'] is False:
            self.client.logger.debug(f"Skipping disabled user {id} / {user_data['userPrincipalName']}")
            return False
        payload = {
            "passwordProfile": {
                "forceChangePasswordNextSignIn": True,
            }
        }
        next_uri = f"{self.client.graph_api_url}/v1.0/users/{id}"
        response = requests.patch(next_uri, headers=self.client.headers, json=payload)
        if response.status_code != 202:
            self.client.logger.warning(f"Failed to reset password for user {id}: {response.status_code} - {response.text}")
            return False
        return True
    
    def get_mfa_status(self, id):
        if id is None: return None
        user_data = self.get_details(id)
        if user_data is None: return None
        if 'accountEnabled' in user_data and user_data['accountEnabled'] is False:
            self.client.logger.debug(f"Skipping disabled user {id} / {user_data['userPrincipalName']}")
            return None
        next_uri = f"{self.client.graph_api_url}/v1.0/users/{id}/authentication/methods"
        response = requests.get(next_uri, headers=self.client.headers)
        if response.status_code != 200:
            self.client.logger.warning(f"Failed to get MFA status for user {id}: {response.status_code} - {response.text}")
            return None
        data = response.json()
        return data
    
    def get_mfa_report(self):
        next_uri = f"{self.client.graph_api_url}/beta/reports/credentialUserRegistrationDetails"
        response = requests.get(next_uri, headers=self.client.headers)
        if response.status_code != 200:
            self.client.logger.warning(f"Failed to get MFA report: {response.status_code} - {response.text}")
            return None
        data = response.json()
        return data

    def __str__(self):
        return f"{self.cache}"

    def __repr__(self):
        return f"{self.__class__.__name__}.{self.client.__caller_info__()}(graph_api_url={self.client.graph_api_url!r}, headers={self.client.headers!r}, cache={self.cache!r})"
