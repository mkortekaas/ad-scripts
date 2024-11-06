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

import logging
import time
import os
import urllib.parse
import socket
import pycurl
from io import BytesIO
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.firefox.options import Options as FirefoxOptions

############################# GENERAL LOGGER ITEMS ######################################################
## make sure that other modules are calling with same logger name
logger                  = logging.getLogger('__COMMONLOGGER__')

###################################################################################
def selenium_screen_shot(driver, file_name, calling_tag):
	save_as = f"{file_name}." + datetime.now().strftime("%Y%m%d_%H%M%S") + f".{calling_tag}.png"
	try:
		driver.execute_script("window.stop();")
		driver.save_screenshot(save_as)
		logger.debug(f"selenium_screen_shot({file_name}) saved as: {save_as}")
	except Exception as e:
		logger.warning(f"selenium_screen_shot({file_name}) saving screenshot: {str(e)}")

###################################################################################
def selenium_profile_dir(profile_dir, tenant_id, FIREFOX):
	if FIREFOX:
		if profile_dir:
			return profile_dir
		else:
			return os.path.join(os.getenv("HOME"), "__selenium__", "profile_firefox", tenant_id)
	else:
		if profile_dir:
			return profile_dir
		else:
			return os.path.join(os.getenv("HOME"), "__selenium__", "profile_chrome", tenant_id)
	return None

def selenium_firefox_setup(profile_dir, tenant_id, firefox_driver_path, firefox_binary_location):
	my_profile_dir = selenium_profile_dir(profile_dir, tenant_id, True)
	if not os.path.exists(my_profile_dir):
		logger.critical(f"Firefox profile directory does not exist: {my_profile_dir}")
		exit(1)
	if not os.path.exists(firefox_driver_path):
		logger.critical(f"Firefox driver path does not exist: {firefox_driver_path}")
		exit(1)
	if not os.path.exists(firefox_binary_location):
		logger.critical(f"Firefox binary location does not exist: {firefox_binary_location}")
		exit(1)
	# logger.debug(f"FFOX_PROFILE_DIR: ({my_profile_dir})")
	firefox_options = FirefoxOptions()
	if my_profile_dir:
		firefox_options.add_argument("-profile")
		firefox_options.add_argument(my_profile_dir)
		firefox_options.add_argument("--width=1920")
		firefox_options.add_argument("--height=1080")

	firefox_options.binary_location = firefox_binary_location
	service = FirefoxService(firefox_driver_path)
	driver = webdriver.Firefox(service=service, options=firefox_options)
	return driver

###################################################################################
def selenium_click_text(driver, text_to_click):
	try:
		element = WebDriverWait(driver, 15).until(
			EC.any_of(
				EC.presence_of_element_located((By.XPATH, f"//*[contains(text(), '{text_to_click}')]")),
				EC.title_is("Sign in to your account")
			)
		)
		if driver.title == "Sign in to your account":
			logger.error(f"selenium_click_text({text_to_click}) FAILURE_CLICK_SIGNIN")
			logger.critical(f"selenium_click_text({text_to_click}) FAILURE_CLICK_SIGNIN")
			exit(0)

		element.click()
		logger.debug(f"selenium_click_text({text_to_click}) - got_it")
		return True
	except Exception as e:
		logger.warning(f"selenium_click_text({text_to_click}) FAILURE_CLICK_OTHER")
		return False
	
###################################################################################
def selenium_entra_signin(admin_account, driver):
	url = "https://entra.microsoft.com/#view/Microsoft_AAD_IAM/AppGalleryBladeV2"
	driver.get(url)
	WebDriverWait(driver, 15).until(
		EC.presence_of_element_located((By.ID, "i0116"))  # Adjust the locator as needed
    )
	# Perform login steps
	driver.find_element(By.ID, "i0116").send_keys(admin_account)  # Enter email
	driver.find_element(By.ID, "idSIButton9").click()  # Click Next button
	logger.info("Once you are signed in you can ctrl-c this, sleeping for 60s")
	time.sleep(60)  ## should be long enough to signin

###################################################################################
def selenium_entra_app_create(app_name, driver):
	url = "https://entra.microsoft.com/#view/Microsoft_AAD_IAM/AppGalleryBladeV2"
	logger.debug(f"selenium_entra_app_create({app_name}) Opening URL: {url}")
	driver.get(url)
	time.sleep(2)
	driver.get(url)   ## honestly not sure why need this extra one but seems to help (caching??)
	time.sleep(2)
	if not selenium_click_text(driver, "Create your own application"):
		logger.warning(f"selenium_entra_app_create({app_name}) FAILURE_APP_CREATE Failed to get to the create page - sleep and try again")
		time.sleep(2)
		driver.get(url)
		time.sleep(2)
		if not selenium_click_text(driver, "Create your own application"):
			logger.warning(f"selenium_entra_app_create({app_name}) FAILURE_APP_CREATE Failed to get to the create page")
			return False

	# Insert app_name into the text box
	try:
		text_box = WebDriverWait(driver, 5).until(
        	EC.presence_of_element_located((By.XPATH, "//input[@placeholder='Input name']"))
		)
		text_box.send_keys(app_name)
		logger.debug(f"selenium_entra_app_create({app_name}) Inserted app_name into the text box")
	except Exception as e:
		logger.warning(f"selenium_entra_app_create({app_name}) FAILURE_APP_CREATE inserting app_name into the text box")
		return False

	# Click on the "Create" button
	try:
		create_button = WebDriverWait(driver, 15).until(
			EC.element_to_be_clickable((By.XPATH, "//span[contains(text(), 'Create') and @class='fxs-button-text']"))
		)
		create_button.click()
		logger.debug(f"selenium_entra_app_create({app_name}) Clicked on the 'Create' button")
	except Exception as e:
		logger.warning(f"selenium_entra_app_create({app_name}) FAILURE_APP_CREATE clicking on the 'Create' button")
		return False
	
	# wait for the application name to appear
	try: 
		WebDriverWait(driver, 60).until(
        	EC.presence_of_element_located((By.XPATH, "//div[@class='fxc-menu-listView-item' and @data-telemetryname='Menu-SignOn' and contains(text(), 'Single sign-on')]"))
		)
		logger.debug(f"selenium_entra_app_create({app_name}) SUCCESS_APP_CREATE Application created")
	except Exception as e:
		logger.warning(f"selenium_entra_app_create({app_name}) FAILURE_APP_CREATE waiting for application name to appear")
		return False	
	
	return True

###################################################################################
def selenium_verify_sso_url(sso_url):
	if not sso_url:
		logger.warning(f"selenium_verify_sso_url(NONE) FAILURE_SSO_URL DNS_INVALID: (none)")
		return False
	if len(sso_url) >= 255:
		logger.warning(f"selenium_verify_sso_url({sso_url}) FAILURE_SSO_URL INVALID string too long - max 255 characters")
		return False
	
	parsed_url = urllib.parse.urlparse(sso_url)
	hostname = parsed_url.hostname
	if not hostname: 
		logger.warning(f"selenium_verify_sso_url({sso_url}) FAILURE_SSO_URL DNS_INVALID (none)")
		return False
	if hostname == "localhost":
		logger.warning(f"selenium_verify_sso_url({sso_url}) FAILURE_SSO_URL DNS_INVALID (localhost)")
		return False
	
	socket.setdefaulttimeout(60)
	try:
		socket.gethostbyname(hostname)
		logger.debug(f"selenium_verify_sso_url({sso_url}) SSO_PASSWORD_APP_URL VALID DNS_ADDRESS")
	except socket.timeout:
		logger.warning(f"selenium_verify_sso_url({sso_url}) FAILURE_SSO_URL TIMEOUT")
		return False
	except socket.error:
		logger.warning(f"selenium_verify_sso_url({sso_url}) FAILURE_SSO_URL INVALID DNS_ADDRESS")
		return False
	finally:
        # Reset the default timeout to None (no timeout)
		socket.setdefaulttimeout(None)

	buffer = BytesIO()
	c = pycurl.Curl()
	c.setopt(c.URL, sso_url)
	c.setopt(c.WRITEDATA, buffer)
	c.setopt(c.FOLLOWLOCATION, True)  # Follow redirects
	c.setopt(c.SSL_VERIFYPEER, False)  # Disable SSL verification
	c.setopt(c.TIMEOUT, 90)

	for attempt in range(3):
		try:
			c.perform()
			status_code = c.getinfo(pycurl.RESPONSE_CODE)
			if status_code == 200 or status_code == 301 or status_code == 302 or status_code == 403:
				logger.debug(f"selenium_verify_sso_url({sso_url}) SSO_PASSWORD_APP_URL is VALID ({status_code})")
				return True
			logger.debug(f"selenium_verify_sso_url({sso_url}) SSO_PASSWORD_APP_URL attempt {attempt} - status_code: {status_code}")
		except Exception as e:
			logger.debug(f"selenium_verify_sso_url({sso_url}) SSO_PASSWORD_APP_URL attempt {attempt} ({str(e)})")
	c.close()
	logger.warning(f"selenium_verify_sso_url({sso_url}) FAILURE_SSO_URL INVALID after 3 attempts")
	return False

def selenium_app2_passwd_sso(app_name, sso_url, driver):
	url = "https://entra.microsoft.com/#view/Microsoft_AAD_IAM/StartboardApplicationsMenuBlade/~/AppAppsPreview"
	driver.get(url)
	time.sleep(5)
	## issues with driver.refresh() - so we just quit and start again
	driver.get(url)
	try:
		text_box = WebDriverWait(driver, 15).until(
			EC.any_of(
        		EC.presence_of_element_located((By.XPATH, "//input[@placeholder='Search by application name or object ID']")),
				EC.title_is("Sign in to your account")
			)
		)
		if driver.title == "Sign in to your account":
			logger.error(f"selenium_app2_passwd_sso({app_name})({sso_url}) FAILURE_CLICK_SIGNIN")
			logger.critical(f"selenium_app2_passwd_sso({app_name})({sso_url}) FAILURE_CLICK_SIGNIN")
			exit(0)
		text_box.send_keys(app_name)
		logger.debug(f"selenium_app2_passwd_sso({app_name})({sso_url}) SSO_PASSWORD_APP_URL Entered app_name into the text box")
	except Exception as e:
		logger.warning(f"selenium_app2_passwd_sso({app_name})({sso_url}) FAILURE_SSO_URL can't find app search box to continue")
		return False
	
	# Click on the link with the app name
	try:
		link = WebDriverWait(driver, 15).until(
			EC.element_to_be_clickable((By.LINK_TEXT, app_name))
		)
		link.click()
		logger.debug(f"selenium_app2_passwd_sso({app_name})({sso_url}) SSO_PASSWORD_APP_URL Clicked on the app")
	except Exception as e:
		logger.warning(f"selenium_app2_passwd_sso({app_name})({sso_url}) FAILURE_SSO_URL clicking on the link with the specified text")
		return False
	
	# go into SSO settings
	try: 
		sso_link = WebDriverWait(driver, 60).until(
        	EC.presence_of_element_located((By.XPATH, "//div[@class='fxc-menu-listView-item' and @data-telemetryname='Menu-SignOn' and contains(text(), 'Single sign-on')]"))
		)
		sso_link.click()
		logger.debug(f"selenium_app2_passwd_sso({app_name})({sso_url}) SSO_PASSWORD_APP_URL Into SSO for application")
	except Exception as e:
		logger.warning(f"selenium_app2_passwd_sso({app_name})({sso_url}) FAILURE_SSO_URL waiting to get into SSO for application")
		return False
	
	# Click on the "Password-based" button
	try:
		password_based_button = WebDriverWait(driver, 15).until(
			EC.element_to_be_clickable((By.XPATH, "//div[@class='ext-ad-problem-details-card-tile-title' and contains(text(), 'Password-based')]"))
		)
		password_based_button.click()
		logger.debug(f"selenium_app2_passwd_sso({app_name})({sso_url}) SSO_PASSWORD_APP_URL Clicked on the 'Password-based' button for app")
	except Exception as e:
		logger.warning(f"selenium_app2_passwd_sso({app_name})({sso_url}) FAILURE_SSO_URL clicking on the 'Password-based' button for application")
		return False
	
	# now add the SSO URL to the app
	try:
		sso_url_text_box = WebDriverWait(driver, 15).until(
			EC.presence_of_element_located((By.XPATH, "//input[@placeholder='https://']"))
       		# EC.presence_of_element_located((By.ID, "form-label-id-95-for"))
		)
		sso_url_text_box.send_keys(sso_url)
		logger.debug(f"selenium_app2_passwd_sso({app_name})({sso_url}) SSO_PASSWORD_APP_URL Inserted SSO URL: {sso_url} into the text box")
	except Exception as e:
		logger.warning(f"selenium_app2_passwd_sso({app_name})({sso_url}) FAILURE_SSO_URL inserting SSO URL into the text box")
		return False
	
	# Click on the "Save" button
	try:
		### NOT WORKING RELIABLY...
		time.sleep(2)
		save_button = WebDriverWait(driver, 20).until(
			# EC.element_to_be_clickable((By.XPATH, "//li[@title='Save']//div[@role='button' and @aria-label='Save']"))
			# EC.element_to_be_clickable((By.XPATH, "//div[@class='azc-toolbarButton-label fxs-commandBar-item-text' and @data-telemetryname='Command-Save' and contains(text(), 'Save')]"))
			# EC.element_to_be_clickable((By.XPATH, "//div[contains(text(), 'Save') and contains(@class, 'fxs-commandBar-item-text')]"))
	   		# EC.element_to_be_clickable((By.XPATH, "//li[@role='presentation' and @title='Save']//div[@class='azc-toolbarButton-label fxs-commandBar-item-text' and @data-telemetryname='Command-Save']"))
			# EC.element_to_be_clickable((By.CSS_SELECTOR, "li[role='presentation'][title='Save'] div.azc-toolbarButton-label.fxs-commandBar-item-text[data-telemetryname='Command-Save']"))
		    EC.element_to_be_clickable((By.XPATH, "//li[@role='presentation' and @title='Save']//div[contains(text(), 'Save')]"))
		)
		save_button.click()
		# driver.execute_script("arguments[0].scrollIntoView(true);", save_button)
		# driver.execute_script("arguments[0].click();", save_button)
		logger.debug(f"selenium_app2_passwd_sso({app_name})({sso_url}) SSO_PASSWORD_APP_URL Clicked on the 'Save' button")
	except Exception as e:
		logger.warning(f"selenium_app2_passwd_sso({app_name})({sso_url}) FAILURE_SSO_URL clicking on the 'Save' button")
		return False
	
	# Wait for the success message to appear
	try:
		success_message = WebDriverWait(driver, 60).until(
			EC.any_of(
				EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'A sign-in form was successfully detected at the provided URL. You can now assign users to this app and test it using My Apps')]")),
				EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 't find any sign-in fields at the URL specified above')]")),
				EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'find any sign-in fields at that URL')]"))
			)
		)
		# Determine which message appeared
		if driver.find_elements(By.XPATH, "//*[contains(text(), 'A sign-in form was successfully detected at the provided URL. You can now assign users to this app and test it using My Apps')]"):
			logger.debug(f"selenium_app2_passwd_sso({app_name})({sso_url}) SUCCESS_SSO_URL message appeared: 'A sign-in form was successfully detected at the provided URL. You can now assign users to this app and test it using My Apps'")
		elif driver.find_elements(By.XPATH, "//*[contains(text(), 't find any sign-in fields at the URL specified above')]"):
			logger.warning(f"selenium_app2_passwd_sso({app_name})({sso_url}) FAILURE_SSO_URL FAIL_MSG 'We couldn't find any sign-in fields at the ..'")
			return False
		elif driver.find_elements(By.XPATH, "//*[contains(text(), 'find any sign-in fields at that URL')]"):
			logger.warning(f"selenium_app2_passwd_sso({app_name})({sso_url}) FAILURE_SSO_URL FAIL_MSG 'We couldn't find any sign-in fields at that URL'")
			return False
		else:
			logger.warning(f"selenium_app2_passwd_sso({app_name})({sso_url}) FAILURE_SSO_URL FAIL_MSG Neither success nor failure message appeared for {app_name}")
			return False
	except Exception as e:
		logger.warning(f"selenium_app2_passwd_sso({app_name})({sso_url}) FAILURE_SSO_URL exception on turning on SSO password")
		return False
	logger.debug(f"selenium_app2_passwd_sso({app_name})({sso_url}) SUCCESS_SSO_URL")
	return True

###################################################################################
def selenium_passwd_sso_set_sub(app_name, group_name, app_aid, sp_id, user_pass_json, driver):
	# validate the user_pass_json
	if not user_pass_json:
		logger.warning(f"selenium_passwd_sso_set_sub({app_name})({group_name}) FAILURE_SSO_CREDENTIAL No user_pass_json")
		return False
	if not user_pass_json.get("username"):
		logger.warning(f"selenium_passwd_sso_set_sub({app_name})({group_name}) FAILURE_SSO_CREDENTIAL No username in user_pass_json")
		return False
	if not user_pass_json.get("password"):
		logger.warning(f"selenium_passwd_sso_set_sub({app_name})({group_name}) FAILURE_SSO_CREDENTIAL No password in user_pass_json")
		return False
	
	url = (f"https://entra.microsoft.com/#view/Microsoft_AAD_IAM/ManagedAppMenuBlade/~/Users/objectId/{sp_id}/appId/{app_aid}/preferredSingleSignOnMode/password/servicePrincipalType/Application/fromNav/")
	browser_name = driver.capabilities['browserName'].lower()
	driver.get(url)
	time.sleep(2)
	driver.get(url)

	try:
		WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
		rows = WebDriverWait(driver, 30).until(
			EC.any_of(
        		EC.presence_of_all_elements_located((By.XPATH, "//div[@class='azc-vivaControl']")),
				EC.title_is("Sign in to your account")
			)
		)
		if driver.title == "Sign in to your account":
			logger.error(f"selenium_passwd_sso_set_sub({app_name})({group_name}) FAILURE_CLICK_SIGNIN")
			logger.critical(f"selenium_passwd_sso_set_sub({app_name})({group_name}) FAILURE_CLICK_SIGNIN")
			exit(0)

		# Locate the row containing the group name using a more specific XPath
		row_xpath = f"//tr[.//div[contains(text(), '{group_name}')]]"
		row_element = WebDriverWait(driver, 1).until(
			EC.presence_of_element_located((By.XPATH, row_xpath))
		)
		logger.debug(f"selenium_passwd_sso_set_sub({app_name})({group_name}) SSO_CREDENTIAL Found the row containing {group_name}")
	except Exception as e:
		logger.warning(f"selenium_passwd_sso_set_sub({app_name})({group_name}) FAILURE_SSO_CREDENTIAL INTERFACE finding the parent row for {group_name} {e}")
		return False
	
	try:
		# Click the checkbox
		driver.execute_script("arguments[0].click();", row_element)
		logger.debug(f"selenium_passwd_sso_set_sub({app_name})({group_name}) SSO_CREDENTIAL on the checkbox for group: {group_name}")
	except Exception as e:
		logger.warning(f"selenium_passwd_sso_set_sub({app_name})({group_name}) FAILURE_SSO_CREDENTIAL clicking on the checkbox for group {group_name} {e}")
		return False
	time.sleep(1)

	try:
		xpath = "//div[contains(text(), 'Update credentials')]"
		update_credentials_button = WebDriverWait(driver, 15).until(
			EC.element_to_be_clickable((By.XPATH, xpath))
		)
		driver.execute_script("arguments[0].scrollIntoView(true);", update_credentials_button)
		driver.execute_script("arguments[0].click();", update_credentials_button)
		logger.debug(f"selenium_passwd_sso_set_sub({app_name})({group_name}) SSO_CREDENTIAL  on the 'Update Credentials' button for {group_name}")
	except Exception as e:
		logger.warning(f"selenium_passwd_sso_set_sub({app_name})({group_name}) FAILURE_SSO_CREDENTIAL clicking on the 'Update Credentials' button for {group_name} {e}")
		return False
	
	###################################################################################
	# Wait for the elements to appear
	time.sleep(2)  
	try: 
		# Switch back to the default content - we need to go up a level to see the popover
		driver.switch_to.default_content()
	except Exception as e:
		logger.warning(f"selenium_passwd_sso_set_sub({app_name})({group_name}) FAILURE_SSO_CREDENTIAL switching to default content")
		return False

	try:
		# wait for the username/password fields to appear
		input_field = WebDriverWait(driver, 15).until(
			EC.presence_of_element_located((By.XPATH, "//div[@class='fxc-weave-pccontrol fxc-section-control fxc-base msportalfx-form-formelement fxc-has-label azc-textField fxc-TextField azc-fabric azc-validationBelowCtrl']//input[@type='text']"))
		)
		username_aria_labelledby = input_field.get_attribute("aria-labelledby")
		logger.debug(f"selenium_passwd_sso_set_sub({app_name})({group_name}) SSO_CREDENTIAL username label is {username_aria_labelledby}")
		input_field.clear()
		input_field.send_keys(user_pass_json.get("username"))
		logger.debug(f"selenium_passwd_sso_set_sub({app_name})({group_name}) SSO_CREDENTIAL  username entered")
	except Exception as e:
		logger.warning(f"selenium_passwd_sso_set_sub({app_name})({group_name}) FAILURE_SSO_CREDENTIAL  username failed")
		return False

	try:
		password_field = WebDriverWait(driver, 15).until(
			EC.presence_of_element_located((By.XPATH, "//div[@class='fxc-weave-pccontrol fxc-section-control fxc-base msportalfx-form-formelement fxc-has-label azc-passwordField fxc-PasswordField azc-fabric azc-validationBelowCtrl']//input[@type='password']"))
		)
		password_field.clear()
		password_field.send_keys(user_pass_json.get("password"))
		logger.debug(f"selenium_passwd_sso_set_sub({app_name})({group_name}) SSO_CREDENTIAL  passwd entered")
	except Exception as e:
		logger.warning(f"selenium_passwd_sso_set_sub({app_name})({group_name}) FAILURE_SSO_CREDENTIAL  password failed")
		return False

	# determine if there are additional fields to be filled in
	third_field_set = None
	try: 
		input_fields = driver.find_elements(By.XPATH, "//div[@class='fxc-weave-pccontrol fxc-section-control fxc-base msportalfx-form-formelement fxc-has-label azc-textField fxc-TextField azc-fabric azc-validationBelowCtrl']//input[@type='text']")
		logger.debug(f"selenium_passwd_sso_set_sub({app_name})({group_name}) SSO_CREDENTIAL  Found {len(input_fields)} text input fields")
		for field in input_fields:
			my_labelledby = field.get_attribute("aria-labelledby")
			if my_labelledby == username_aria_labelledby:
				continue

			field.clear()
			if not user_pass_json.get("extraFieldValue"):
				logger.warning(f"selenium_passwd_sso_set_sub({app_name})({group_name}) SSO_CREDENTIAL SSO_3RD have field but no value to insert")
				extra_field_value = "nothing_from_bot_engine"
				third_field_set = False
			else:
				extra_field_value = user_pass_json.get("extraFieldValue")
				third_field_set = True
			field.send_keys(extra_field_value)
			logger.warning(f"selenium_passwd_sso_set_sub({app_name})({group_name}) SSO_CREDENTIAL SSO_3RD text input field filled in {my_labelledby}")

	except Exception as e:
		if not user_pass_json.get("extraFieldValue"):
			logger.debug(f"selenium_passwd_sso_set_sub({app_name})({group_name}) SSO_CREDENTIAL no issue - no additional input fields found")
		else:
			logger.warning(f"selenium_passwd_sso_set_sub({app_name})({group_name}) FAILURE_SSO_CREDENTIAL SSO_3RD text input field failed")
			return False
		
	## SSO_3RD just throw a warning message in to examine the case later
	if third_field_set is not None:
		if third_field_set == False:
			logger.warning(f"selenium_passwd_sso_set_sub({app_name})({group_name}) SSO_CREDENTIAL SSO_3RD field in bot input but no value to insert")

	try:
		# Click on the "Save" button
		save_button = WebDriverWait(driver, 15).until(
			EC.element_to_be_clickable((By.XPATH, "//div[@class='azc-toolbarButton-label fxs-commandBar-item-text' and @data-telemetryname='Command-Save' and contains(text(), 'Save')]"))
		)
		save_button.click()
		logger.debug(f"selenium_passwd_sso_set_sub({app_name})({group_name}) SSO_CREDENTIAL Clicked on the 'Save' button for sso password")
	except Exception as e:
		logger.warning(f"selenium_passwd_sso_set_sub({app_name})({group_name}) FAILURE_SSO_CREDENTIAL clicking on the 'Save' button for sso password")
		return False
	
	try:
		# Wait for the success message to appear
		success_message = WebDriverWait(driver, 60).until(
			EC.any_of(
				EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'Successfully saved credentials')]")),
				EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'maximum number of secrets has been reached')]"))
			)
		)
		if driver.find_elements(By.XPATH, "//*[contains(text(), 'Successfully saved credentials')]"):
			logger.info(f"selenium_passwd_sso_set_sub({app_name})({group_name}) SUCCESS_SSO_CREDENTIAL message appeared: 'Successfully saved credentials'")
		else:
			logger.warning(f"selenium_passwd_sso_set_sub({app_name})({group_name}) FAILURE_SSO_CREDENTIAL_MAXIMUM message appeared: 'maximum number of secrets has been reached'")
			return False
	except Exception as e:
		logger.warning(f"selenium_passwd_sso_set_sub({app_name})({group_name}) FAILURE_SSO_CREDENTIAL waiting for the success message for ({group_name})")
		return False
	return True

def selenium_passwd_sso_set(app_name, group_name, app_aid, sp_id, userPassword_json, driver):
	if not selenium_passwd_sso_set_sub(app_name, group_name, app_aid, sp_id, userPassword_json, driver):
		logger.warning(f"selenium_passwd_sso_set({app_name})({group_name}) FAILURE_SSO_CREDENTIAL failed to set - sleep for 10s / try again")
		time.sleep(10)
		if not selenium_passwd_sso_set_sub(app_name, group_name, app_aid, sp_id, userPassword_json, driver):
			logger.warning(f"selenium_passwd_sso_set({app_name})({group_name}) FAILURE_SSO_CREDENTIAL Failed to set")
			return False
	return True

###################################################################################
###################################################################################
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
import subprocess
def selenium_chrome_getver(chrome_binary_location):
    try:
        result = subprocess.run([chrome_binary_location, '--version'], capture_output=True, text=True)
        return result.stdout.strip().split()[-1]
    except Exception as e:
        logger.warning(f"Failed to get Chrome version: {str(e)}")
        return None
def selenium_chrome_setup(user_data_dir, profile_dir, chrome_driver_path, chrome_binary_location):
	## had issues with Chrome and screen saving that did not have time to sort - firefox works so ...
	chrome_options = Options()
	chrome_options.add_argument("enable-automation")
	chrome_options.add_argument("--no-sandbox")
	chrome_options.add_argument('--disable-gpu')
	chrome_options.add_argument('--dns-prefetch-disable')
	chrome_options.add_argument("--remote-debugging-port=9222")  # This is important
	chrome_options.add_argument("--window-size=1920,1080")
	# chrome_options.add_argument("--headless")
	# chrome_options.add_argument("--start-maximized")
	chrome_options.add_argument("--disable-dev-shm-usage")

	## to find out which one you are using: Navigate to chrome://version/
	##    this only works if the browser is not used elsewhere and is setup cleanly
	if user_data_dir:
		chrome_options.add_argument(f"--user-data-dir={user_data_dir}")
	if profile_dir:
		chrome_options.add_argument(f"--profile-directory={profile_dir}")

	# Set up the Chrome WebDriver
	chrome_options.binary_location = chrome_binary_location
	service = Service(chrome_driver_path)
	driver = webdriver.Chrome(service=service, options=chrome_options)
	driver.set_page_load_timeout(30)
	return driver
###################################################################################
###################################################################################
