"""Hash reviewed Git-visible source; never include local generated state."""
import hashlib,json,subprocess,sys
from pathlib import Path
from datetime import datetime,timezone
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
from agentsearch import __version__
paths=subprocess.check_output(['git','ls-files','-z','--cached','--others','--exclude-standard'],cwd=root).decode().split('\0')
files={}
for relative in sorted(set(paths)-{'','MANIFEST.json'}):
    p=root/relative
    if p.is_symlink() or not p.is_file():raise ValueError('Invalid release path: '+relative)
    if relative.startswith(('state/','config/','.git/')) or p.suffix in ('.db','.sqlite3','.pem','.key','.pfx') or p.name.startswith('.env'):
        raise ValueError('Private state cannot be sealed: '+relative)
    raw=p.read_bytes();files[relative]={'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
result={'schema_version':1,'name':'AgentSearch','version':__version__,
        'created_at_utc':datetime.now(timezone.utc).isoformat(),
        'validation':'docs/releases/v1.0.0-rc4.md','native_windows_verified':True,
        'authentication':'Unsigned local integrity manifest, not publisher authentication','files':files}
(root/'MANIFEST.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8',newline='\n')
print(json.dumps({'version':__version__,'sealed_files':len(files)}))
