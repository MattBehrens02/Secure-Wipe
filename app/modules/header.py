from modules import version
def print_header():
    print(r"""
   _____                         
  / ___/___  _______  __________ 
  \__ \/ _ \/ ___/ / / / ___/ _ \
 ___/ /  __/ /__/ /_/ / /  /  __/
/____/\___/\___/\__,_/_/   \___/ 
| |     / (_)___  ___            
| | /| / / / __ \/ _ \           
| |/ |/ / / /_/ /  __/           
|__/|__/_/ .___/\___/            
        /_/
    """)
    print(f"{version.AppVersion.app_name} - Version {version.AppVersion.app_version}")
    