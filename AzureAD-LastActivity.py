#!/usr/bin/python3

# MIT License
# Copyright (c) 2020 L.M. Kortekaas
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
##############################################################
#
# This file takes two inputs from the O365 admin portal and provides back the
# Last Activity Information as best provided from the inputs available.
#
# It should be noted that if one has an Azure Active Directory Premium License
# you should -seriously- look at the Azure AD PowerSheell cmdlets for reporting
# instead of using this bit of hackery
#
##############################################################

import pandas as pd

usersFile = 'export-users.csv'
activityFile = 'export-activity.csv'
outputFile = 'last-activity.csv'

# load users file (AzureAD -> users -> export), index with DisplayName
usersFrame = pd.read_csv(usersFile, index_col='DisplayName')

# load activity file (AzureAD -> reports -> M365 active users -> 180 days -> export
activityFrame = pd.read_csv(activityFile, index_col='Display Name', parse_dates=['Exchange Last Activity Date', 'OneDrive Last Activity Date', 'SharePoint Last Activity Date', 'Skype For Business Last Activity Date', 'Yammer Last Activity Date', 'Teams Last Activity Date'])

# add last activity field as max on activy from others cols
activityFrame['LastActivity'] = activityFrame[['Exchange Last Activity Date', 'OneDrive Last Activity Date', 'SharePoint Last Activity Date', 'Skype For Business Last Activity Date', 'Yammer Last Activity Date', 'Teams Last Activity Date']].max(axis=1)

# add LastActivity to usersFrame - default to old date so something exists
usersFrame['LastActivity'] = '01/01/1970'

# itterate through source
for label, row in usersFrame.iterrows():
    try:
        lastActivity = activityFrame.loc[label, 'LastActivity']
    except KeyError:
        lastActivity = 'Nat'

    # add data to usersFrame
    if type(lastActivity) is pd.Timestamp:
        usersFrame.at[label, 'LastActivity'] = lastActivity

# export to new file which has new field added
usersFrame.to_csv(outputFile, index=True, header=True)

