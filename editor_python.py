"""Editor Python local para Electronica Pi, sin dependencias externas."""
import base64
import atexit
import ast
import getpass
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import signal
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

CONFIG = Path.home() / '.config/electronica-editor/auth.json'
SCRIPTS = Path.home() / 'Compartido/Proyectos/Python'
VENV_PYTHON = Path.home() / '.local/share/electronica-python/venv/bin/python'
LOCK = threading.Lock()
JOB = None
RESTART_PENDING = False
TOKEN = secrets.token_urlsafe(32)
UPDATE_CONFIG = CONFIG.parent / 'update.json'

def repository_name(url):
    if not isinstance(url,str):
        raise ValueError('Escribe la dirección de tu repositorio GitHub.')
    match = re.fullmatch(r'https://github\.com/([A-Za-z0-9_-]+)/([A-Za-z0-9_.-]+)/?',url.strip())
    if not match:
        raise ValueError('Usa https://github.com/TU_USUARIO/TU_REPOSITORIO')
    return '/'.join(match.groups()).removesuffix('.git')

def github_bytes(url):
    request = Request(url, headers={'User-Agent':'Electronica-Pi-Updater','Accept':'application/vnd.github+json'})
    with urlopen(request,timeout=25) as response:
        data = response.read(1024*1024+1)
    if len(data)>1024*1024:
        raise ValueError('Archivo remoto demasiado grande.')
    return data

def update_from_github(repo_url, destination=None):
    repo = repository_name(repo_url)
    destination = Path(destination or Path(__file__).resolve().parent)
    print('Buscando la versión de main en '+repo,flush=True)
    commit = json.loads(github_bytes('https://api.github.com/repos/'+repo+'/commits/main'))['sha']
    if not re.fullmatch(r'[a-f0-9]{40}',commit):
        raise ValueError('Identificador de versión no válido.')
    content = {}
    for name in ('explorador.py','editor_python.py'):
        data = github_bytes('https://raw.githubusercontent.com/'+repo+'/'+commit+'/'+name)
        tree = ast.parse(data.decode('utf-8-sig'),filename=name)
        functions={node.name for node in ast.walk(tree) if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef))}
        if name=='editor_python.py' and not {'handle','authorize'}.issubset(functions):
            raise ValueError('El archivo remoto no contiene el editor esperado.')
        if name=='explorador.py' and not any(isinstance(n,ast.ClassDef) and n.name=='Explorer' for n in ast.walk(tree)):
            raise ValueError('El archivo remoto no contiene el explorador esperado.')
        content[name]=data
        print('Descargado y validado: '+name,flush=True)
    backup = CONFIG.parent / 'backup'
    backup.mkdir(parents=True,exist_ok=True,mode=0o700)
    original = {}
    staged = {}
    try:
        for name,data in content.items():
            path=destination/name
            original[name]=path.read_bytes() if path.exists() else None
            if path.exists():
                shutil.copy2(path,backup/name)
            fd,temp_path=tempfile.mkstemp(prefix='.actualizacion-',dir=destination)
            with os.fdopen(fd,'wb') as f:
                f.write(data)
            staged[name]=Path(temp_path)
        for name,temp_path in staged.items():
            os.replace(temp_path,destination/name)
        UPDATE_CONFIG.write_text(json.dumps({'repository':repo_url,'commit':commit}),encoding='utf-8')
    except Exception:
        for name,data in original.items():
            if data is not None:
                (destination/name).write_bytes(data)
            elif (destination/name).exists():
                (destination/name).unlink()
        raise
    finally:
        for path in staged.values():
            path.unlink(missing_ok=True)
    print('Actualización aplicada: '+commit[:12]+'. Reiniciando el explorador…',flush=True)

def install_packages(packages):
    total=len(packages)
    print(f'EDITOR_PROGRESS 0/{total}',flush=True)
    for index,package in enumerate(packages,1):
        print('Instalando '+package+'…',flush=True)
        result=subprocess.run([environment_python(),'-u','-m','pip','--isolated','--disable-pip-version-check','install','--no-input','--progress-bar','off','--',package])
        if result.returncode:
            return result.returncode
        print(f'EDITOR_PROGRESS {index}/{total}',flush=True)
    return 0

def cleanup():
    if JOB:
        kill_job(JOB)
        JOB['file'].close()
        try:
            os.unlink(JOB['file'].name)
        except OSError:
            pass

atexit.register(cleanup)

PAGE = r'''<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Electrónica Pi · Python</title><style>
:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#101624;color:#eef3fc;font:16px/1.5 system-ui}main{max-width:1200px;margin:auto;padding:26px}a{color:#65dfbb}h1{margin-bottom:4px}p{color:#aab9d0}.toolbar{display:flex;flex-wrap:wrap;gap:10px;margin:20px 0}button,input,select{font:inherit;padding:10px 14px;border-radius:10px;border:1px solid #34435e;background:#192235;color:#eef3fc}button{cursor:pointer}button:hover{border-color:#65dfbb}.primary{background:#65dfbb;color:#102a24;font-weight:bold}.layout{display:grid;grid-template-columns:3fr 2fr;gap:16px}textarea,pre{width:100%;height:470px;background:#151e2e;color:#eef3fc;border:1px solid #34435e;border-radius:14px;padding:18px;font:15px/1.6 monospace;tab-size:4}textarea{resize:vertical;white-space:pre;overflow:auto}pre{margin:0;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere}label{display:block;margin:8px 0;color:#aab9d0}#status{min-height:28px;color:#65dfbb}button:disabled{opacity:.5;cursor:wait}input{max-width:240px}footer{color:#aab9d0;font-size:13px;margin:20px 0}*:focus-visible{outline:2px solid #65dfbb;outline-offset:3px}@media(max-width:800px){.layout{grid-template-columns:1fr}textarea{height:360px}pre{height:230px}}

.code-editor{position:relative;height:470px;border:1px solid #34435e;border-radius:14px;background:#1e1e1e;overflow:hidden}.code-editor textarea,.code-editor #highlight{font:15px/24px Consolas,"Liberation Mono",monospace;letter-spacing:0;font-variant-ligatures:none;tab-size:4;padding:18px;white-space:pre;overflow-wrap:normal;margin:0;border:0;border-radius:0;background:transparent}.code-editor textarea{position:absolute;left:56px;top:0;width:calc(100% - 56px);height:100%;resize:none;color:transparent;caret-color:#ffffff;z-index:2;overflow:auto;-webkit-text-fill-color:transparent}.code-editor textarea::selection{background:#264f78;color:transparent}.code-editor textarea:focus-visible{outline:0}.code-editor:focus-within{border-color:#65dfbb;box-shadow:0 0 0 1px #65dfbb}.paint{position:absolute;left:56px;right:0;top:0;bottom:0;overflow:hidden;pointer-events:none}.code-editor #highlight{width:max-content;min-width:100%;height:auto;overflow:visible;color:#d4d4d4;transform-origin:top left}.gutter{position:absolute;left:0;top:0;bottom:0;width:56px;background:#202020;border-right:1px solid #343434;overflow:hidden;pointer-events:none}#line-numbers{padding:18px 10px 18px 0;text-align:right;color:#858585;font:15px/24px Consolas,"Liberation Mono",monospace}#line-numbers span{display:block;height:24px}.tok-keyword{color:#c586c0}.tok-variable{color:#9cdcfe}.tok-function{color:#dcdcaa}.tok-string{color:#ce9178}.tok-number{color:#b5cea8}.tok-comment{color:#6a9955;font-style:italic}.tok-operator{color:#d4d4d4}.tok-punctuation{color:#ffd700}.tok-constant{color:#569cd6}.legend{display:flex;flex-wrap:wrap;gap:12px;font-size:12px;padding:10px 2px}.toolbar #files{min-width:140px}.toolbar #name{min-width:140px}#package-list{height:180px!important}@media(max-width:800px){.code-editor{height:360px}}
</style><main><a href="/">← Volver al explorador</a><h1>Laboratorio Python</h1><p>Crea tus scripts, guárdalos y ejecútalos en tu Raspberry Pi.</p><section aria-label="Librerías Python"><h2>Librerías</h2><p>Instala por nombre, por ejemplo: requests pyserial. Necesitas Internet.</p><div class="toolbar"><input id="package" placeholder="requests pyserial" aria-label="Librerías a instalar"><button class="primary" id="install">＋ Instalar librerías</button><button id="packages">Ver instaladas</button></div><pre id="package-list" hidden style="height:180px" aria-label="Librerías instaladas"></pre></section><section aria-label="Actualización del editor"><h2>Actualizaciones</h2><p>Repositorio público propio · rama main · Guarda tu código antes de actualizar.</p><div class="toolbar"><input id="repository" placeholder="https://github.com/usuario/electronica-pi" aria-label="Repositorio GitHub" style="max-width:none;min-width:260px;flex:1"><button id="update">↻ Actualizar desde GitHub</button></div></section><div id="install-progress" hidden><label id="progress-label" for="progress">Librerías completadas: 0%</label><progress id="progress" max="100" value="0" style="width:100%;height:20px;accent-color:#65dfbb"></progress></div><div id="status" role="status" aria-live="polite">Listo para programar.</div><section aria-label="Carpeta de trabajo"><h2>Carpeta de trabajo</h2><p id="folder-path" style="overflow-wrap:anywhere"></p><div class="toolbar"><button id="folder-up">↑ Subir carpeta</button><select id="folder-select" aria-label="Subcarpetas"></select><button id="folder-enter">Entrar en carpeta</button><button id="folder-home">⌂ Mi carpeta personal</button></div><p id="file-path" style="overflow-wrap:anywhere"></p></section><div class="toolbar"><button id="new">＋ Nuevo</button><select id="files" aria-label="Scripts guardados"></select><button id="open">Abrir</button><input id="name" value="hola.py" aria-label="Nombre del archivo"><button id="save">Guardar</button><button class="primary" id="run">▶ Guardar y ejecutar</button><button id="stop">■ Detener</button></div><div class="layout"><section><label for="code">Código Python · UTF-8</label><div class="code-editor"><div class="gutter" aria-hidden="true"><div id="line-numbers"></div></div><div class="paint" aria-hidden="true"><pre id="highlight"></pre></div><textarea id="code" wrap="off" spellcheck="false" autocapitalize="off" autocomplete="off" autocorrect="off">print("Hola desde mi Raspberry Pi")
</textarea></div></section><section><label for="output">Consola de resultados</label><pre id="output" tabindex="0">La salida y los errores aparecerán aquí.</pre></section></div><footer>Carpeta: la seleccionada arriba · Un script a la vez · Scripts: hasta 60 segundos · Instalaciones: hasta 10 minutos · Entorno virtual propio.<br>Esta consola muestra resultados; no admite entrada interactiva con input(). Los scripts se ejecutan con los permisos de electronica.</footer></main><script>
const token=__TOKEN__, $=id=>document.getElementById(id);let dirty=false,polling=false,reloading=false,currentDirectory="",parentDirectory=null;
async function api(action,data){let path='/api/editor/'+action;if(!data&&currentDirectory)path+=(path.includes('?')?'&':'?')+'directory='+encodeURIComponent(currentDirectory);const r=await fetch(path,{method:data?'POST':'GET',headers:{'Content-Type':'application/json','X-Editor-Token':token},body:data?JSON.stringify({...data,directory:currentDirectory}):undefined});let j;try{j=await r.json()}catch(e){throw Error('No se pudo conectar al editor. Recarga la página.')}if(!r.ok)throw Error(j.error||'Error');return j}
function showFilePath(){$('file-path').textContent='Archivo: '+currentDirectory+'/'+$('name').value}
async function loadFolder(directory){const previous=currentDirectory;currentDirectory=directory||'';try{const info=await api('folders');currentDirectory=info.directory;parentDirectory=info.parent;$('folder-path').textContent='Guardar y ejecutar en: '+currentDirectory;$('folder-up').disabled=!parentDirectory;$('folder-select').replaceChildren();for(const name of info.folders){const opt=document.createElement('option');opt.textContent=opt.value=name;$('folder-select').append(opt)}$('folder-enter').disabled=info.folders.length===0;await list();showFilePath();if(previous&&previous!==currentDirectory){dirty=true;status('Carpeta cambiada. El código actual se guardará aquí; los archivos anteriores permanecen en su ubicación.')}}catch(e){currentDirectory=previous;throw e}}
$('folder-up').addEventListener('click',()=>{if(parentDirectory)loadFolder(parentDirectory).catch(e=>status(e.message))});$('folder-enter').addEventListener('click',()=>{if($('folder-select').value)loadFolder(currentDirectory+'/'+$('folder-select').value).catch(e=>status(e.message))});$('folder-home').addEventListener('click',()=>loadFolder(__HOME__).catch(e=>status(e.message)));

function status(t){$('status').textContent=t}async function list(){const j=await api('list');$('files').replaceChildren();for(const n of j.files){const o=document.createElement('option');o.value=o.textContent=n;$('files').append(o)}}
// Coloreado local de Python: conserva el texto original.
const pyKeywords=new Set('and as assert async await break class continue def del elif else except finally for from global if import in is lambda nonlocal not or pass raise return try while with yield match case'.split(' '));
const pyBuiltins=new Set('abs all any bin bool bytearray bytes callable chr classmethod compile complex delattr dict dir divmod enumerate eval exec filter float format frozenset getattr globals hasattr hash help hex id input int isinstance issubclass iter len list locals map max memoryview min next object oct open ord pow print property range repr reversed round set setattr slice sorted staticmethod str sum super tuple type vars zip __import__'.split(' '));
function escapeCode(t){return t.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;')}
function highlightPython(code){let i=0,html='',expectName=false;function add(t,kind){html+=kind?'<span class="tok-'+kind+'">'+escapeCode(t)+'</span>':escapeCode(t)}while(i<code.length){let rest=code.slice(i),m;
if(rest[0]==='#'){let end=code.indexOf('\n',i);if(end<0)end=code.length;add(code.slice(i,end),'comment');i=end;continue}
m=/^(?:[rRuUbBfF]{1,2})?(\x27\x27\x27|"""|'|")/.exec(rest);if(m){let opening=m[0],q=m[1],end=i+opening.length;while(end<code.length){if(code[end]==='\\'){end+=2;continue}if(code.startsWith(q,end)){end+=q.length;break}if(q.length===1&&code[end]==='\n')break;end++}add(code.slice(i,end),'string');i=end;continue}
m=/^(?:0[xX][0-9a-fA-F_]+|0[bB][01_]+|0[oO][0-7_]+|(?:\d[\d_]*(?:\.[\d_]*)?|\.\d[\d_]*)(?:[eE][+-]?[\d_]+)?[jJ]?)/.exec(rest);if(m){add(m[0],'number');i+=m[0].length;continue}
m=/^[\p{L}_][\p{L}\p{N}_]*/u.exec(rest);if(m){const word=m[0];let kind='variable';if(pyKeywords.has(word))kind='keyword';else if(['True','False','None'].includes(word))kind='constant';else if(expectName||pyBuiltins.has(word)||/^\s*\(/.test(rest.slice(word.length)))kind='function';add(word,kind);expectName=word==='def'||word==='class';i+=word.length;continue}
if('()[]{}:,.'.includes(rest[0]))add(rest[0],'punctuation');else if('+-*/%=!<>|&^~'.includes(rest[0]))add(rest[0],'operator');else add(rest[0]);i++}return html}
function renderCode(){const code=$('code').value;$('highlight').innerHTML=highlightPython(code)+'\n';const count=code.split('\n').length;$('line-numbers').innerHTML=Array.from({length:count},(_,i)=>'<span>'+(i+1)+'</span>').join('');syncEditorScroll()}
function syncEditorScroll(){$('highlight').style.transform='translate('+-$('code').scrollLeft+'px,'+-$('code').scrollTop+'px)';$('line-numbers').style.transform='translateY('+-$('code').scrollTop+'px)'}
$('code').addEventListener('scroll',syncEditorScroll);$('code').addEventListener('input',renderCode);

function confirmDiscard(){return !dirty||confirm('Hay cambios sin guardar. ¿Quieres descartarlos?')}
async function save(){await api('save',{name:$('name').value,code:$('code').value});dirty=false;await list();$('files').value=$('name').value;status('Archivo guardado.');}
async function poll(){if(polling)return;polling=true;try{const j=await api('status');$('output').textContent=j.output||'Sin salida todavía.';for(const id of ['run','install','packages','update'])$(id).disabled=j.running;$('stop').disabled=!j.running||j.kind==='update';$('install-progress').hidden=j.kind!=='install';$('progress').value=j.percent||0;$('progress-label').textContent='Librerías completadas: '+(j.percent||0)+'%';if(j.running)status(j.kind==='install'?'Instalando librerías…':j.kind==='update'?'Descargando actualización…':'Ejecutando…');else if(j.started){status(j.reason||(j.kind==='install'?(j.returncode===0?'Librerías instaladas. Ya puedes importarlas.':'Falló la instalación. Revisa la consola.'):j.kind==='update'?(j.returncode===0?'Actualización aplicada. Reiniciando; la página se recargará.':'Falló la actualización. Revisa la consola.'):'Ejecución terminada. Código de salida: '+j.returncode));if(j.kind==='update'&&j.returncode===0&&!reloading){reloading=true;for(const id of ['run','install','packages','update'])$(id).disabled=true;setTimeout(()=>location.reload(),9000)}}}catch(e){status(reloading?'Reiniciando el explorador…':e.message)}finally{polling=false}}
for(const [id,fn] of Object.entries({new:async()=>{if(!confirmDiscard())return;$('name').value='nuevo.py';$('code').value='print("Hola desde mi Raspberry Pi")\n';dirty=true;renderCode();showFilePath();status('Nuevo script: recuerda guardarlo.');},open:async()=>{if(!confirmDiscard())return;if(!$('files').value)return;const j=await api('read?name='+encodeURIComponent($('files').value));$('name').value=j.name;$('code').value=j.code;dirty=false;renderCode();showFilePath();status('Archivo abierto.');},update:async()=>{if(dirty){status("Guarda el código antes de actualizar.");return}if(!confirm("¿Actualizar desde tu repositorio y reiniciar el explorador?"))return;await api("update",{repository:$("repository").value.trim()});status("Actualizando…");await poll()},install:async()=>{await api('install',{packages:$('package').value});status('Instalando librerías…');await poll()},packages:async()=>{const j=await api('packages');$('package-list').hidden=false;$('package-list').textContent=j.packages.map(p=>p.name+'  '+p.version).join('\n');status('Lista de librerías actualizada.');},save,run:async()=>{await save();await api('run',{name:$('name').value});status('Ejecutando…');await poll()},stop:async()=>{await api('stop',{});await poll()}}))$(id).addEventListener('click',async()=>{try{await fn()}catch(e){status(e.message)}});
$('code').addEventListener('input',()=>dirty=true);$('name').addEventListener('input',()=>{dirty=true;showFilePath()});$('code').addEventListener('keydown',e=>{if(e.key==='Tab'){e.preventDefault();const t=e.target,a=t.selectionStart,b=t.selectionEnd;t.setRangeText('    ',a,b,'end');dirty=true;renderCode()}});window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue=''}});api('repository').then(j=>$('repository').value=j.repository||'').catch(e=>status(e.message));renderCode();loadFolder().catch(e=>status(e.message));poll();setInterval(poll,1000);
</script></html>'''

def configure():
    print('Configura una contraseña para el editor web. Usuario: electronica')
    password = getpass.getpass('Contraseña nueva del editor: ')
    if len(password) < 4:
        raise ValueError('Usa al menos 4 caracteres.')
    if password != getpass.getpass('Repite la contraseña: '):
        raise ValueError('Las contraseñas no coinciden.')
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 200000)
    CONFIG.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(CONFIG, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.chmod(CONFIG, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump({'salt':salt.hex(), 'hash':digest.hex()}, f)
    SCRIPTS.mkdir(parents=True, exist_ok=True)
    print('Editor configurado. Reinicia el servicio explorador.')

def authorize(handler):
    try:
        config = json.loads(CONFIG.read_text())
    except (OSError, ValueError):
        handler.send_error(503, 'Configura el editor con python3 editor_python.py --configurar')
        return False
    try:
        auth = handler.headers.get('Authorization', '')
        scheme, encoded = auth.split(' ', 1)
        if scheme.lower() != 'basic':
            raise ValueError()
        user, password = base64.b64decode(encoded, validate=True).decode().split(':', 1)
        digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(config['salt']), 200000)
        if user == 'electronica' and hmac.compare_digest(digest.hex(), config['hash']):
            return True
    except (ValueError, KeyError, UnicodeError):
        pass
    handler.send_response(401)
    handler.send_header('WWW-Authenticate', 'Basic realm="Editor Python", charset="UTF-8"')
    handler.send_header('Content-Length', '0')
    handler.end_headers()
    return False

def resolve_directory(value=None):
    directory=Path(value) if value else SCRIPTS
    home=Path.home().resolve()
    if not directory.is_absolute():
        raise ValueError('Selecciona una ruta absoluta dentro de tu carpeta personal.')
    resolved=directory.resolve()
    if not resolved.is_relative_to(home) or directory.absolute()!=resolved:
        raise ValueError('Selecciona una carpeta dentro de home, sin enlaces simbólicos.')
    if any(part.startswith('.') for part in resolved.relative_to(home).parts):
        raise ValueError('Las carpetas ocultas están protegidas.')
    if not resolved.is_dir():
        raise ValueError('La carpeta seleccionada ya no existe.')
    return resolved

def script_path(name, directory=None):
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}\.py', name):
        raise ValueError('Nombre válido: letras sin acentos, números, guion o guion bajo, terminado en .py.')
    path = resolve_directory(directory) / name
    if path.is_symlink():
        raise ValueError('No se permiten enlaces simbólicos.')
    return path

def kill_job(job):
    if job['process'].poll() is None:
        if os.name == 'posix':
            try:
                os.killpg(job['process'].pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            job['process'].kill()

def watch(job):
    global RESTART_PENDING
    while job['process'].poll() is None:
        if time.monotonic()-job['start'] > job['timeout'] or os.fstat(job['file'].fileno()).st_size > 1024*1024:
            with LOCK:
                job['reason'] = f"Proceso detenido: límite de {job['timeout']} segundos o 1 MB de salida."
                kill_job(job)
            break
        time.sleep(.2)
    job['process'].wait()
    if job['kind']=='update' and job['process'].returncode==0:
        RESTART_PENDING = True
        # systemd Restart=on-failure vuelve a iniciar el servidor con los archivos nuevos.
        time.sleep(5)
        os._exit(1)

def environment_python():
    if not VENV_PYTHON.is_file():
        raise ValueError('Falta preparar el entorno: python3 -m venv ~/.local/share/electronica-python/venv')
    return str(VENV_PYTHON)

def package_names(text):
    if not isinstance(text, str):
        raise ValueError('Escribe los nombres de las librerías.')
    packages = text.split()
    pattern = r'[A-Za-z0-9][A-Za-z0-9._-]*(?:==[A-Za-z0-9][A-Za-z0-9._+!-]*)?'
    if not 1 <= len(packages) <= 6 or any(len(p)>120 or not re.fullmatch(pattern,p) for p in packages):
        raise ValueError('Escribe hasta 6 nombres separados por espacios, por ejemplo: requests pyserial. También se acepta requests==2.32.3.')
    return packages

def start_job(command, kind='script', timeout=60, cwd=None):
    global JOB
    with LOCK:
        if RESTART_PENDING:
            raise ValueError('Actualización terminada; espera a que reinicie el explorador.')
        if JOB and JOB['process'].poll() is None:
            raise ValueError('Espera o detén el proceso actual antes de continuar.')
        if JOB:
            JOB['file'].close()
            os.unlink(JOB['file'].name)
        output = tempfile.NamedTemporaryFile(delete=False)
        try:
            process = subprocess.Popen(command,cwd=str(cwd or SCRIPTS),stdin=subprocess.DEVNULL,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
        except Exception:
            output.close()
            os.unlink(output.name)
            raise
        JOB = {'process':process,'file':output,'start':time.monotonic(),'reason':'','timeout':timeout,'kind':kind}
        threading.Thread(target=watch,args=(JOB,),daemon=True).start()

def json_response(handler, data, code=200):
    body = json.dumps(data, ensure_ascii=False).encode()
    handler.send_response(code)
    handler.send_header('Content-Type', 'application/json; charset=utf-8')
    handler.send_header('Content-Length', str(len(body)))
    handler.send_header('Cache-Control', 'no-store')
    handler.send_header('X-Content-Type-Options', 'nosniff')
    handler.end_headers()
    if handler.command != 'HEAD':
        handler.wfile.write(body)

def handle(handler):
    global JOB
    route = urlsplit(handler.path)
    if route.path not in ('/editor', '/editor/') and not route.path.startswith('/api/editor/'):
        return False
    if not authorize(handler):
        return True
    if route.path in ('/editor', '/editor/'):
        if handler.command not in ('GET','HEAD'):
            json_response(handler, {'error':'Método no permitido'}, 405)
            return True
        body = PAGE.replace('__TOKEN__', json.dumps(TOKEN)).replace('__HOME__',json.dumps(str(Path.home()))).encode()
        handler.send_response(200)
        handler.send_header('Content-Type','text/html; charset=utf-8')
        handler.send_header('Content-Length',str(len(body)))
        handler.send_header('Cache-Control','no-store')
        handler.send_header('Content-Security-Policy',"default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        handler.end_headers()
        if handler.command != 'HEAD':
            handler.wfile.write(body)
        return True
    if not hmac.compare_digest(handler.headers.get('X-Editor-Token',''), TOKEN):
        json_response(handler, {'error':'Recarga la página del editor.'},403)
        return True
    action = route.path.rsplit('/',1)[-1]
    try:
        if handler.command == 'POST':
            length = int(handler.headers.get('Content-Length','0'))
            if not 0 < length <= 262144:
                raise ValueError('El código es demasiado grande o falta el contenido.')
            data = json.loads(handler.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError('Contenido no válido.')
        else:
            data = {}
        if action in ('save','run','stop','install','update') and handler.command != 'POST':
            json_response(handler, {'error':'Se requiere POST'},405)
            return True
        if action in ('list','read','status','packages','repository','folders') and handler.command != 'GET':
            json_response(handler, {'error':'Se requiere GET'},405)
            return True
        SCRIPTS.mkdir(parents=True, exist_ok=True)
        query=parse_qs(route.query)
        directory=resolve_directory(data.get('directory') if handler.command=='POST' else query.get('directory',[None])[0]) if action in ('folders','list','read','save','run') else SCRIPTS
        result = {'ok':True}
        if action == 'folders':
            result={'directory':str(directory),'parent':str(directory.parent) if directory!=Path.home().resolve() else None,'folders':sorted(p.name for p in directory.iterdir() if not p.name.startswith('.') and not p.is_symlink() and p.is_dir())}
        elif action == 'list':
            result = {'directory':str(directory),'files':sorted(p.name for p in directory.glob('*.py') if p.is_file() and not p.is_symlink() and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}\.py',p.name))}
        elif action == 'read':
            name = parse_qs(route.query).get('name',[''])[0]
            path = script_path(name,directory)
            if path.stat().st_size > 262144:
                raise ValueError('Archivo demasiado grande para el editor.')
            result = {'name':name,'path':str(path), 'code':path.read_text(encoding='utf-8')}
        elif action == 'save':
            path = script_path(data.get('name'),directory)
            code = data.get('code')
            if not isinstance(code,str):
                raise ValueError('Código no válido.')
            with LOCK:
                if JOB and JOB['process'].poll() is None:
                    raise ValueError('Detén la ejecución antes de guardar.')
                path.write_text(code, encoding='utf-8')
        elif action == 'run':
            path = script_path(data.get('name'),directory)
            if not path.is_file():
                raise ValueError('Guarda el archivo antes de ejecutarlo.')
            start_job([environment_python(),'-u',str(path)],cwd=directory)
        elif action == 'install':
            packages = package_names(data.get('packages'))
            environment_python()
            start_job([sys.executable,'-u',str(Path(__file__).resolve()),'--instalar',*packages],kind='install',timeout=600)
        elif action == 'repository':
            result=json.loads(UPDATE_CONFIG.read_text()) if UPDATE_CONFIG.exists() else {'repository':''}
        elif action == 'update':
            repo=data.get('repository')
            repository_name(repo)
            start_job([sys.executable,'-u',str(Path(__file__).resolve()),'--actualizar',repo],kind='update',timeout=180)
        elif action == 'packages':
            with LOCK:
                if JOB and JOB['process'].poll() is None:
                    raise ValueError('Espera a que termine el proceso actual.')
                completed = subprocess.run([environment_python(),'-m','pip','--isolated','--disable-pip-version-check','list','--format=json'],capture_output=True,text=True,timeout=20)
            if completed.returncode:
                raise ValueError(completed.stderr.strip() or 'No se pudo consultar pip.')
            result = {'packages':json.loads(completed.stdout)}
        elif action == 'stop':
            with LOCK:
                if JOB and JOB['process'].poll() is None:
                    if JOB['kind']=='update':
                        raise ValueError('Espera a que termine la actualización.')
                    JOB['reason']='Proceso detenido por el usuario.'
                    kill_job(JOB)
                    JOB['process'].wait(timeout=5)
        elif action == 'status':
            with LOCK:
                if not JOB:
                    result = {'running':False,'started':False,'output':''}
                else:
                    with open(JOB['file'].name,'rb') as reader:
                        output = reader.read(1024*1024).decode('utf-8',errors='replace')
                    rc = JOB['process'].poll()
                    progress=re.findall(r'^EDITOR_PROGRESS (\d+)/(\d+)$',output,re.M)
                    percent=int(int(progress[-1][0])*100/int(progress[-1][1])) if progress else 0
                    output=re.sub(r'^EDITOR_PROGRESS \d+/\d+\r?\n?','',output,flags=re.M)
                    result = {'running':rc is None,'started':True,'output':output,'returncode':rc,'reason':JOB['reason'],'kind':JOB['kind'],'percent':percent}
        else:
            json_response(handler,{'error':'Acción desconocida'},404)
            return True
        json_response(handler,result)
    except (ValueError,OSError,KeyError,TypeError,subprocess.TimeoutExpired) as e:
        json_response(handler,{'error':str(e)},400)
    return True

if __name__ == '__main__':
    if len(sys.argv)>2 and sys.argv[1]=='--instalar':
        sys.exit(install_packages(package_names(' '.join(sys.argv[2:]))))
    elif len(sys.argv)==3 and sys.argv[1]=='--actualizar':
        try:
            update_from_github(sys.argv[2])
        except Exception as e:
            print('No se pudo actualizar: '+str(e),file=sys.stderr,flush=True)
            sys.exit(1)
    elif sys.argv[1:] == ['--configurar']:
        try:
            configure()
        except (ValueError,OSError) as e:
            print(e,file=sys.stderr)
            sys.exit(1)
    else:
        print('Uso: python3 editor_python.py --configurar')
