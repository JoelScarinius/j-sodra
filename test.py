import os
import requests
from dotenv import load_dotenv

# Load environment variables from the .env file
load_dotenv()
CLIENTID = os.getenv("CLIENTID")
CLIENTSECRET = os.getenv("CLIENTSECRET")

# 1. Define the URL from your JSON file
# Uncomment the ONE url you want to test at a time, or put them in a list and loop!
# url = "https://apirest.wyscout.com/v3/players/89186/advancedstats?compId=524"
# url = "https://apirest.wyscout.com/v3/search?query=dybala&objType=player"
url = "https://apirest.wyscout.com/v3/areas"

# 2. Add your authentication (Wyscout usually requires Basic Auth)
# Replace 'username' and 'password' with your actual Wyscout API credentials
auth = (CLIENTID, CLIENTSECRET)

# 3. Make the request
response = requests.get(url, auth=auth)

# 4. Read the data
if response.status_code == 200:
    data = response.json()
    print(data)  # This will print the stats for player 89186!
else:
    print(f"Error: {response.status_code} - {response.text}")
