import subprocess, json

def detect_drives():
    result = subprocess.run(
        ['lsblk', '--json', '--output', 'NAME,PATH,SIZE,MODEL,VENDOR,SERIAL,TYPE,MOUNTPOINTS,RM,TRAN'],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )

    return json.loads(result.stdout)