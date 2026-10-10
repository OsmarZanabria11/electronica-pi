#!/usr/bin/env python3
"""Explorador local de solo lectura; Python 3, sin dependencias."""
import argparse
import html
import io
import mimetypes
import json
import os
import secrets
import shutil
import threading
from datetime import datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit, parse_qs

FILE_LOCK = threading.Lock()

def mutate_files(handler, data):
    action = data.get('action')
    name = data.get('name')
    if action not in ('mkdir','create','delete-file','delete-folder'):
        raise ValueError('Operación desconocida.')
    if not isinstance(name,str) or not name.strip() or name in ('.','..') or name.startswith('.') or any(c in name for c in '/\\') or any(ord(c)<32 for c in name):
        raise ValueError('Escribe un nombre sin barras, sin caracteres de control y que no empiece por punto.')
    folder_url = data.get('directory')
    if not isinstance(folder_url,str) or not folder_url.startswith('/') or '?' in folder_url or '#' in folder_url:
        raise ValueError('Carpeta no válida.')
    directory = Path(handler.translate_path(folder_url))
    if not directory.is_dir():
        raise ValueError('La carpeta ya no existe.')
    if getattr(handler,'system',False) and directory==handler.root:
        raise PermissionError('Abre una carpeta antes de crear o eliminar elementos.')
    target_url=folder_url.rstrip('/')+'/'+quote(name,safe='')
    target=Path(handler.translate_path(target_url))
    if target.parent!=directory or (directory/name).is_symlink():
        raise PermissionError('Ruta o enlace no permitido.')
    protected = {handler.root,Path.home(),Path(__file__).resolve(),Path(__file__).resolve().with_name('editor_python.py')}
    if getattr(handler,'system',False):
        protected.update(handler.allowed)
    if target in protected:
        raise PermissionError('Este elemento está protegido para mantener el explorador funcionando.')
    with FILE_LOCK:
        if action=='mkdir':
            target.mkdir()
        elif action=='create':
            content=data.get('content','')
            if not isinstance(content,str) or len(content.encode('utf-8'))>131072:
                raise ValueError('Contenido demasiado grande.')
            # x evita sobrescribir un archivo existente.
            with target.open('x',encoding='utf-8') as file:
                file.write(content)
        else:
            if action=='delete-file' and not target.is_file():
                raise ValueError('Selecciona un archivo existente.')
            if action=='delete-folder' and not target.is_dir():
                raise ValueError('Selecciona una carpeta existente.')
            trash=Path.home()/'.local/share/electronica-papelera'
            trash.mkdir(parents=True,exist_ok=True,mode=0o700)
            item=trash/(datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(4))
            item.mkdir(mode=0o700)
            (item/'origen.json').write_text(json.dumps({'original':str(target)},ensure_ascii=False),encoding='utf-8')
            try:
                shutil.move(str(target),str(item/target.name))
            except Exception:
                (item/'origen.json').unlink(missing_ok=True)
                item.rmdir()
                raise
    return {'ok':True,'message':'Elemento enviado a la papelera.' if action.startswith('delete') else 'Elemento creado.'}

STYLE = '''
:root{color-scheme:dark;--bg:#101624;--panel:#192235;--line:#2b3750;--text:#eef3fc;--muted:#aab9d0;--accent:#65dfbb}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:16px/1.5 system-ui,sans-serif}a{color:inherit;text-decoration:none}header{border-bottom:1px solid var(--line);padding:22px max(24px,calc((100% - 1100px)/2));display:flex;align-items:center;gap:12px}.logo{background:var(--accent);color:#101624;border-radius:13px;padding:9px 13px;font-weight:900}.brand{font-weight:750}.sub{font-size:13px;color:var(--muted)}main{max-width:1150px;margin:auto;padding:40px 24px}h1{font-size:clamp(30px,5vw,46px);letter-spacing:-1.5px;margin:0 0 8px}.intro{color:var(--muted);margin:0 0 28px}.stats{display:flex;gap:12px;margin:24px 0}.stat{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:15px 22px;flex:1}.stat strong{display:block;font-size:27px}.stat span{color:var(--muted);font-size:13px}.toolbar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:24px 0}.button,button{border:1px solid var(--line);border-radius:10px;padding:10px 14px;background:var(--panel);color:var(--text);font:inherit;cursor:pointer}.button:hover,button:hover{border-color:var(--accent)}.primary{background:var(--accent);color:#102a24;border-color:var(--accent);font-weight:700}input,select{border:1px solid var(--line);border-radius:10px;padding:12px;background:var(--panel);color:var(--text);font:inherit}input{flex:1;min-width:180px}a:focus-visible,button:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid var(--accent);outline-offset:3px}.crumb{color:var(--muted);overflow-wrap:anywhere}.crumb a{color:var(--accent)}.items{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:16px}.card{background:var(--panel);border:1px solid var(--line);border-radius:18px;padding:20px;min-width:0}.card:hover{border-color:#4d658a}.icon{width:46px;height:46px;background:#25354f;display:grid;place-items:center;border-radius:12px;font-size:23px;color:var(--accent);margin-bottom:16px}.name{font-weight:700;overflow-wrap:anywhere;display:block}.meta{color:var(--muted);font-size:13px;margin:7px 0 18px}.actions{display:flex;gap:8px}.actions .button{font-size:14px;padding:8px 12px}.empty{color:var(--muted);padding:30px;border:1px dashed var(--line);border-radius:16px}.list{display:block}.list .card{display:flex;align-items:center;gap:18px;margin-bottom:10px;padding:14px 18px}.list .icon{margin:0;flex-shrink:0}.list .details{flex:1;min-width:0}.list .meta{margin:3px 0}.list .actions{flex-shrink:0}footer{margin-top:36px;color:var(--muted);font-size:13px}[hidden]{display:none!important}@media(max-width:580px){main{padding:26px 16px}.stats{gap:7px}.stat{padding:12px}.stat strong{font-size:22px}.list .card{flex-wrap:wrap}.list .actions{width:100%}.toolbar select{width:100%}}
'''
JS = '''
const cards=[...document.querySelectorAll('.card')], box=document.querySelector('.items'), search=document.querySelector('#search'), order=document.querySelector('#order');
function update(){const term=search.value.toLocaleLowerCase();let count=0;cards.forEach(c=>{c.hidden=!c.dataset.name.toLocaleLowerCase().includes(term);if(!c.hidden)count++});document.querySelector('#noresults').hidden=count>0;cards.sort((a,b)=>{if(a.dataset.folder!==b.dataset.folder)return Number(b.dataset.folder)-Number(a.dataset.folder);if(order.value==='recent')return Number(b.dataset.time)-Number(a.dataset.time);if(order.value==='size')return Number(b.dataset.size)-Number(a.dataset.size);return a.dataset.name.localeCompare(b.dataset.name,'es',{numeric:true})}).forEach(c=>box.appendChild(c))}
search.addEventListener('input',update);order.addEventListener('change',update);document.querySelector('#view').addEventListener('click',e=>{const list=box.classList.toggle('list');e.currentTarget.textContent=list?'▦ Tarjetas':'☰ Lista';e.currentTarget.setAttribute('aria-pressed',String(list))});document.querySelector('#refresh').addEventListener('click',()=>location.reload());update();
const controls=document.querySelector('#file-controls');
async function changeFile(action,name,content=''){try{const auth=await fetch('/api/files/session');if(!auth.ok)throw Error('Inicia sesión con el usuario electronica y la contraseña del editor.');const session=await auth.json();const response=await fetch('/api/files/change',{method:'POST',headers:{'Content-Type':'application/json','X-Editor-Token':session.token},body:JSON.stringify({action,name,content,directory:controls.dataset.directory})});const result=await response.json();if(!response.ok)throw Error(result.error);location.reload()}catch(error){alert(error.message)}}
function deleteItem(kind,name){if(name===null||!name.trim())return;if(confirm('¿Enviar '+name+' a la papelera?'+(kind==='folder'?' Se moverá también todo su contenido.':'')))changeFile(kind==='folder'?'delete-folder':'delete-file',name)}
if(controls){document.querySelector('#new-folder').addEventListener('click',()=>{const name=prompt('Nombre de la nueva carpeta:');if(name&&name.trim())changeFile('mkdir',name)});document.querySelector('#new-file').addEventListener('click',()=>{const name=prompt('Nombre del nuevo archivo, por ejemplo notas.txt:');if(!name||!name.trim())return;const content=prompt('Contenido inicial (déjalo vacío para crear un archivo vacío):','');if(content!==null)changeFile('create',name,content)});document.querySelector('#delete-folder').addEventListener('click',()=>deleteItem('folder',prompt('Nombre exacto de la carpeta que quieres eliminar:')));document.querySelector('#delete-file').addEventListener('click',()=>deleteItem('file',prompt('Nombre exacto del archivo que quieres eliminar:')));document.querySelectorAll('.delete-item').forEach(button=>button.addEventListener('click',()=>deleteItem(button.dataset.kind,button.dataset.name)))}

'''

def size_label(size):
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if size < 1024 or unit == 'TB':
            return f'{size:.0f} {unit}' if unit == 'B' else f'{size:.1f} {unit}'
        size /= 1024

class Explorer(SimpleHTTPRequestHandler):
    def files_request(self):
        route=urlsplit(self.path).path
        if route not in ('/api/files/session','/api/files/change'):
            return False
        import editor_python as editor
        if not editor.authorize(self):
            return True
        if route=='/api/files/session' and self.command=='GET':
            editor.json_response(self,{'token':editor.TOKEN})
            return True
        if route!='/api/files/change' or self.command!='POST':
            editor.json_response(self,{'error':'Método no permitido'},405)
            return True
        import hmac
        if not hmac.compare_digest(self.headers.get('X-Editor-Token',''),editor.TOKEN):
            editor.json_response(self,{'error':'Recarga el explorador e inicia sesión.'},403)
            return True
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=262144:
                raise ValueError('Contenido no válido o demasiado grande.')
            data=json.loads(self.rfile.read(length))
            if not isinstance(data,dict):
                raise ValueError('Contenido no válido.')
            editor.json_response(self,mutate_files(self,data))
        except FileExistsError:
            editor.json_response(self,{'error':'Ya existe un elemento con ese nombre.'},409)
        except PermissionError:
            editor.json_response(self,{'error':'Sin permiso para modificar este elemento, o ruta protegida.'},403)
        except (OSError,ValueError,TypeError) as error:
            editor.json_response(self,{'error':str(error)},400)
        return True

    def editor_request(self):
        from urllib.parse import urlsplit
        route = urlsplit(self.path).path
        if route in ('/editor', '/editor/') or route.startswith('/api/editor/'):
            try:
                import editor_python
            except ImportError:
                self.send_error(503, 'Instala editor_python.py junto a explorador.py')
                return True
            return editor_python.handle(self)
        return False

    def do_GET(self):
        if not self.files_request() and not self.editor_request():
            super().do_GET()

    def do_HEAD(self):
        if not self.files_request() and not self.editor_request():
            super().do_HEAD()

    def do_POST(self):
        if not self.files_request() and not self.editor_request():
            self.send_error(405, 'Método no permitido')

    def __init__(self, *args, root, system=False, **kwargs):
        self.root = Path(root).resolve()
        self.system = system
        self.allowed = [self.root / p for p in ('home', 'boot', 'var/log', 'media', 'mnt', 'opt', 'usr/share')]
        super().__init__(*args, directory=str(self.root), **kwargs)

    def translate_path(self, path):
        # Bloquear rutas fuera de Compartido, incluyendo enlaces simbolicos.
        relative = unquote(urlsplit(path).path).lstrip('/')
        parts = Path(relative).parts
        if any(p.startswith('.') and p not in ('.', '..') for p in parts):
            raise PermissionError('Archivos ocultos no publicados')
        if '..' in parts:
            raise PermissionError('Ruta no permitida')
        candidate = (self.root / relative).resolve()
        if not candidate.is_relative_to(self.root):
            raise PermissionError('Ruta fuera de la carpeta compartida')
        if getattr(self, 'system', False):
            if candidate != self.root and not any(candidate.is_relative_to(p) for p in self.allowed):
                raise PermissionError('Carpeta no publicada')
            # No seguir enlaces simbolicos, ni siquiera dentro de las rutas publicadas.
            current = self.root
            for part in parts:
                current = current / part
                if current.is_symlink():
                    raise PermissionError('Enlace simbolico no publicado')
        return str(candidate)

    def send_head(self):
        try:
            target = Path(self.translate_path(self.path))
        except (PermissionError, ValueError, OSError):
            self.send_error(403, 'Acceso no permitido')
            return None
        if target.is_dir():
            # Siempre mostrar el explorador, aunque haya un index.html.
            return self.list_directory(str(target))
        if not target.is_file():
            self.send_error(404, 'Archivo no encontrado o no es un archivo regular')
            return None
        try:
            file = target.open('rb')
        except PermissionError:
            self.send_error(403, 'Sin permiso de lectura para electronica')
            return None
        except OSError:
            self.send_error(404, 'Archivo no encontrado')
            return None
        try:
            import os
            stat = os.fstat(file.fileno())
            download = parse_qs(urlsplit(self.path).query).get('download') == ['1']
            mime = mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
            if mime.startswith('text/'):
                mime += '; charset=utf-8'
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(stat.st_size))
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Cache-Control', 'no-store')
            # HTML/SVG compartidos no deben ejecutar scripts en este origen.
            self.send_header('Content-Security-Policy', "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:")
            if download or mime.startswith(('text/html', 'image/svg+xml')):
                self.send_header('Content-Disposition', "attachment; filename*=UTF-8''" + quote(target.name, safe=''))
            self.end_headers()
            return file
        except Exception:
            file.close()
            raise

    def list_directory(self, path):
        directory = Path(path)
        system = getattr(self, 'system', False)
        landing = system and directory == self.root
        try:
            entries = []
            children = self.allowed if landing else directory.iterdir()
            for child in children:
                if child.name.startswith('.') or child.is_symlink():
                    continue
                try:
                    info = child.stat()
                    if child.is_file() or child.is_dir():
                        entries.append((child, info, child.is_dir()))
                except OSError:
                    continue
        except OSError:
            self.send_error(403, 'No se puede abrir esta carpeta')
            return None
        entries.sort(key=lambda e: (not e[2], e[0].name.casefold()))
        esc = html.escape
        rel = directory.relative_to(self.root)
        crumbs = ['<a href="/">Raspberry Pi</a>' if system else '<a href="/">Compartido</a>']
        for i, part in enumerate(rel.parts):
            if system and not any((self.root.joinpath(*rel.parts[:i+1])).is_relative_to(p) for p in self.allowed):
                continue
            url = '/' + '/'.join(quote(p, safe='') for p in rel.parts[:i+1]) + '/'
            crumbs.append(f'<a href="{url}">{esc(part)}</a>')
        parent = '/' + '/'.join(quote(p, safe='') for p in rel.parts[:-1])
        if not parent.endswith('/'):
            parent += '/'
        if system and directory in self.allowed:
            parent = '/'
        folders = sum(e[2] for e in entries)
        total = sum(e[1].st_size for e in entries if not e[2])
        cards = []
        for child, info, folder in entries:
            url = '/' + '/'.join(quote(p, safe='') for p in child.relative_to(self.root).parts)
            if folder:
                url += '/'
            display_name = '/' + child.relative_to(self.root).as_posix() if landing else child.name
            name = esc(display_name)
            icon = '▣' if folder else {'txt':'≡','pdf':'PDF','png':'▧','jpg':'▧','jpeg':'▧','mp3':'♫','mp4':'▶','zip':'ZIP','py':'&lt;/&gt;'}.get(child.suffix.lower().lstrip('.'), '◇')
            kind = 'Carpeta' if folder else size_label(info.st_size)
            date = datetime.fromtimestamp(info.st_mtime).strftime('%d/%m/%Y %H:%M')
            actions = f'<a class="button primary" href="{url}">{"Entrar" if folder else "Abrir"}</a>'
            if not folder:
                actions += f'<a class="button" href="{url}?download=1" download>↓ Descargar</a>'
            if not landing:
                actions += f'<button class="button delete-item" data-kind="{"folder" if folder else "file"}" data-name="{name}" type="button">Eliminar</button>'
            cards.append(f'<article class="card" data-name="{name}" data-folder="{int(folder)}" data-size="{info.st_size}" data-time="{info.st_mtime}"><div class="icon" aria-hidden="true">{icon}</div><div class="details"><a class="name" href="{url}">{name}</a><div class="meta">{kind} · {date}</div></div><div class="actions">{actions}</div></article>')
        up = f'<a class="button" href="{parent}">↑ Subir carpeta</a>' if rel.parts else ''
        current_url='/'+'/'.join(quote(p,safe='') for p in rel.parts)
        controls = '' if landing else f'<div class="toolbar" id="file-controls" data-directory="{current_url}"><button id="new-folder" type="button">＋ Crear carpeta</button><button id="new-file" type="button">＋ Crear archivo</button><button id="delete-folder" type="button">Eliminar carpeta</button><button id="delete-file" type="button">Eliminar archivo</button></div><p class="sub">Eliminar mueve a la papelera; las carpetas incluyen su contenido. Las modificaciones requieren la contraseña del editor.</p>'
        shortcuts = ''
        if system:
            shortcuts = '<nav class="toolbar" aria-label="Accesos rápidos"><a class="button" href="/">⌂ Inicio</a><a class="button" href="/home/">Home</a><a class="button" href="/home/electronica/Compartido/">Compartido</a><a class="button" href="/boot/">Arranque</a><a class="button" href="/var/log/">Registros</a><a class="button" href="/media/">Unidades</a></nav>'
        page = f'''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Electrónica · Mis archivos</title><style>{STYLE}</style></head><body>
        <header><a class="logo" href="/" aria-label="Inicio">E.</a><div><div class="brand">Electrónica Pi</div><div class="sub">Tu espacio de archivos</div></div></header>
        <main><h1>{'Mi Raspberry' if landing else 'Mis archivos'}</h1><p class="intro">Explora, abre y descarga tus archivos desde cualquier dispositivo de tu red.</p><nav class="toolbar"><a class="button primary" href="/editor">&lt;/&gt; Editor Python</a></nav>{shortcuts}<nav class="crumb" aria-label="Ruta actual">{' / '.join(crumbs)}</nav>
        <section class="stats" aria-label="Resumen de esta carpeta"><div class="stat"><strong>{len(entries)-folders}</strong><span>Archivos</span></div><div class="stat"><strong>{folders}</strong><span>Carpetas</span></div><div class="stat"><strong>{size_label(total)}</strong><span>Archivos de esta carpeta</span></div></section>
        <div class="toolbar"><input id="search" type="search" placeholder="Buscar en esta carpeta…" aria-label="Buscar archivos"><select id="order" aria-label="Ordenar archivos"><option value="name">Nombre A–Z</option><option value="recent">Más recientes</option><option value="size">Mayor tamaño</option></select><button id="view" type="button" aria-pressed="false">☰ Lista</button><button id="refresh" type="button">↻ Actualizar</button>{up}</div>
        {controls}<section class="items" aria-label="Archivos y carpetas">{''.join(cards)}</section><p id="noresults" class="empty" hidden>{'No hay coincidencias con tu búsqueda.' if entries else 'Esta carpeta está vacía. Usa Crear carpeta o Crear archivo para agregar contenido.'}</p>
        <footer>Electrónica Pi · Gestión de archivos con permisos de electronica · {'Carpetas seleccionadas del sistema' if system else 'Carpeta compartida'}</footer></main><script>{JS}</script></body></html>'''
        data = page.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
        self.end_headers()
        return io.BytesIO(data)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default='/home/electronica/Compartido')
    parser.add_argument('--system', action='store_true', help='Publicar home, boot, var/log, media, mnt, opt y usr/share')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--bind', default='0.0.0.0')
    args = parser.parse_args()
    root = Path('/' if args.system else args.root).resolve()
    if not root.is_dir():
        parser.error('La carpeta compartida no existe')
    server = ThreadingHTTPServer((args.bind, args.port), partial(Explorer, root=root, system=args.system))
    print(f'Explorador disponible en puerto {args.port}. Carpeta: {root}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
