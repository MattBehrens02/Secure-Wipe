from modules.terminal import WipeCommands, run_command, CommandRunnerError
import datetime

class WipeEngine:
    drive: object
    path: str
    dry_run: bool

    def __init__(self, drive, dry_run: bool = False):
        self.drive = drive
        self.path = drive.path # /dev/sdx
        self.dry_run = dry_run
        # For demonstration, use fixed keyfile and mapping name
        self.keyfile = "/tmp/securewipe.key"
        self.mapping_name = f"wipe_{self.path.split('/')[-1]}"

    def execute(self):

        if self.dry_run:
            print(f"[DRY RUN] Would execute wipe on drive at {self.path}")
            return WipeResult(status="dry_run")
        else:
            self.generate_temporary_key()
            self.create_luks2_container()
            self.open_encrypted_container()
            self.write_across_encrypted_drive()
            self.close_encrypted_container()
            self.destroy_luks2_container()
            self.remove_residual_signatures()
        
            return WipeResult(status="success")

    def generate_temporary_key(self):
        cmd = ["dd", "if=/dev/urandom", f"of={self.keyfile}", "bs=1M", "count=4"]
        if self.dry_run:
            print("[DRY RUN]", " ".join(cmd))
        else:
            print("[INFO] Generating temporary keyfile...")
            run_command(cmd, check=True)

    def create_luks2_container(self):
        cmd = WipeCommands.luks_format(self.path, self.keyfile)
        if self.dry_run:
            print("[DRY RUN]", " ".join(cmd))
        else:
            print("[INFO] Creating LUKS2 container...")
            run_command(cmd, check=True)

    def open_encrypted_container(self):
        cmd = WipeCommands.luks_open(self.path, self.keyfile, self.mapping_name)
        if self.dry_run:
            print("[DRY RUN]", " ".join(cmd))
        else:
            print("[INFO] Opening encrypted container...")
            run_command(cmd, check=True)

    def write_across_encrypted_drive(self):
        mapped_device = f"/dev/mapper/{self.mapping_name}"
        cmd = WipeCommands.scrub(mapped_device)
        if self.dry_run:
            print("[DRY RUN]", " ".join(cmd))
        else:
            print("[INFO] Scrubbing mapped device...")
            run_command(cmd, check=True)

    def close_encrypted_container(self):
        cmd = WipeCommands.luks_close(self.mapping_name)
        if self.dry_run:
            print("[DRY RUN]", " ".join(cmd))
        else:
            print("[INFO] Closing encrypted container...")
            run_command(cmd, check=True)

    def destroy_luks2_container(self):
        cmd = WipeCommands.destroy_luks_header(self.path)
        if self.dry_run:
            print("[DRY RUN]", " ".join(cmd))
        else:
            print("[INFO] Destroying LUKS2 header...")
            run_command(cmd, check=True)

    def remove_residual_signatures(self):
        cmd = WipeCommands.wipefs(self.path)
        if self.dry_run:
            print("[DRY RUN]", " ".join(cmd))
        else:
            print("[INFO] Removing residual filesystem signatures...")
            run_command(cmd, check=True)

    def verify(self):
        # Placeholder for verification logic after wiping, e.g. checking for residual data
        pass
    
class WipeResult:
    def __init__(self, status: str):
        self.status = status