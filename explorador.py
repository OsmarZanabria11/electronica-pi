#!/usr/bin/env python3
"""Explorador local de solo lectura; Python 3, sin dependencias."""
import argparse
import html
import io
import mimetypes
from datetime import datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit, parse_qs

STYLE = '''
:root{color-scheme:dark;--bg:#101624;--panel:#192235;--line:#2b3750;--text:#eef3fc;--muted:#aab9d0;--accent:#65dfbb}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:16px/1.5 system-ui,sans-serif}a{color:inherit;text-decoration:none}header{border-bottom:1px solid var(--line);padding:22px max(24px,calc((100% - 1100px)/2));display:flex;align-items:center;gap:12px}.logo{background:var(--accent);color:#101624;border-radius:13px;padding:9px 13px;font-weight:900}.brand{font-weight:750}.sub{font-size:13px;color:var(--muted)}main{max-width:1150px;margin:auto;padding:40px 24px}h1{font-size:clamp(30px,5vw,46px);letter-spacing:-1.5px;margin:0 0 8px}.intro{color:var(--muted);margin:0 0 28px}.stats{display:flex;gap:12px;margin:24px 0}.stat{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:15px 22px;flex:1}.stat strong{display:block;font-size:27px}.stat span{color:var(--muted);font-size:13px}.toolbar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:24px 0}.button,button{border:1px solid var(--line);border-radius:10px;padding:10px 14px;background:var(--panel);color:var(--text);font:inherit;cursor:pointer}.button:hover,button:hover{border-color:var(--accent)}.primary{background:var(--accent);color:#102a24;border-color:var(--accent);font-weight:700}input,select{border:1px solid var(--line);border-radius:10px;padding:12px;background:var(--panel);color:var(--text);font:inherit}input{flex:1;min-width:180px}a:focus-visible,button:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid var(--accent);outline-offset:3px}.crumb{color:var(--muted);overflow-wrap:anywhere}.crumb a{color:var(--accent)}.items{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:16px}.card{background:var(--panel);border:1px solid var(--line);border-radius:18px;padding:20px;min-width:0}.card:hover{border-color:#4d658a}.icon{width:46px;height:46px;background:#25354f;display:grid;place-items:center;border-radius:12px;font-size:23px;color:var(--accent);margin-bottom:16px}.name{font-weight:700;overflow-wrap:anywhere;display:block}.meta{color:var(--muted);font-size:13px;margin:7px 0 18px}.actions{display:flex;gap:8px}.actions .button{font-size:14px;padding:8px 12px}.empty{color:var(--muted);padding:30px;border:1px dashed var(--line);border-radius:16px}.list{display:block}.list .card{display:flex;align-items:center;gap:18px;margin-bottom:10px;padding:14px 18px}.list .icon{margin:0;flex-shrink:0}.list .details{flex:1;min-width:0}.list .meta{margin:3px 0}.list .actions{flex-shrink:0}footer{margin-top:36px;color:var(--muted);font-size:13px}[hidden]{display:none!important}@media(max-width:580px){main{padding:26px 16px}.stats{gap:7px}.stat{padding:12px}.stat strong{font-size:22px}.list .card{flex-wrap:wrap}.list .actions{width:100%}.toolbar select{width:100%}}
'''
JS = '''
const cards=[...document.querySelectorAll('.card')], box=document.querySelector('.items'), search=document.querySelector('#search'), order=document.querySelector('#order');
function update(){const term=search.value.toLocaleLowerCase();let count=0;cards.forEach(c=>{c.hidden=!c.dataset.name.toLocaleLowerCase().includes(term);if(!c.hidden)count++});document.querySelector('#noresults').hidden=count>0;cards.sort((a,b)=>{if(a.dataset.folder!==b.dataset.folder)return Number(b.dataset.folder)-Number(a.dataset.folder);if(order.value==='recent')return Number(b.dataset.time)-Number(a.dataset.time);if(order.value==='size')return Number(b.dataset.size)-Number(a.dataset.size);return a.dataset.name.localeCompare(b.dataset.name,'es',{numeric:true})}).forEach(c=>box.appendChild(c))}
search.addEventListener('input',update);order.addEventListener('change',update);document.querySelector('#view').addEventListener('click',e=>{const list=box.classList.toggle('list');e.currentTarget.textContent=list?'▦ Tarjetas':'☰ Lista';e.currentTarget.setAttribute('aria-pressed',String(list))});document.querySelector('#refresh').addEventListener('click',()=>location.reload());update();
'''

def size_label(size):
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if size < 1024 or unit == 'TB':
            return f'{size:.0f} {unit}' if unit == 'B' else f'{size:.1f} {unit}'
        size /= 1024

class Explorer(SimpleHTTPRequestHandler):
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
        if not self.editor_request():
            super().do_GET()

    def do_HEAD(self):
        if not self.editor_request():
            super().do_HEAD()

    def do_POST(self):
        if not self.editor_request():
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
            cards.append(f'<article class="card" data-name="{name}" data-folder="{int(folder)}" data-size="{info.st_size}" data-time="{info.st_mtime}"><div class="icon" aria-hidden="true">{icon}</div><div class="details"><a class="name" href="{url}">{name}</a><div class="meta">{kind} · {date}</div></div><div class="actions">{actions}</div></article>')
        up = f'<a class="button" href="{parent}">↑ Subir carpeta</a>' if rel.parts else ''
        shortcuts = ''
        if system:
            shortcuts = '<nav class="toolbar" aria-label="Accesos rápidos"><a class="button" href="/">⌂ Inicio</a><a class="button" href="/home/">Home</a><a class="button" href="/home/electronica/Compartido/">Compartido</a><a class="button" href="/boot/">Arranque</a><a class="button" href="/var/log/">Registros</a><a class="button" href="/media/">Unidades</a></nav>'
        page = f'''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Electrónica · Mis archivos</title><style>{STYLE}</style></head><body>
        <header><a class="logo" href="/" aria-label="Inicio">E.</a><div><div class="brand">Electrónica Pi</div><div class="sub">Tu espacio de archivos</div></div></header>
        <main><h1>{'Mi Raspberry' if landing else 'Mis archivos'}</h1><p class="intro">Explora, abre y descarga tus archivos desde cualquier dispositivo de tu red.</p><nav class="toolbar"><a class="button primary" href="/editor">&lt;/&gt; Editor Python</a></nav>{shortcuts}<nav class="crumb" aria-label="Ruta actual">{' / '.join(crumbs)}</nav>
        <section class="stats" aria-label="Resumen de esta carpeta"><div class="stat"><strong>{len(entries)-folders}</strong><span>Archivos</span></div><div class="stat"><strong>{folders}</strong><span>Carpetas</span></div><div class="stat"><strong>{size_label(total)}</strong><span>Archivos de esta carpeta</span></div></section>
        <div class="toolbar"><input id="search" type="search" placeholder="Buscar en esta carpeta…" aria-label="Buscar archivos"><select id="order" aria-label="Ordenar archivos"><option value="name">Nombre A–Z</option><option value="recent">Más recientes</option><option value="size">Mayor tamaño</option></select><button id="view" type="button" aria-pressed="false">☰ Lista</button><button id="refresh" type="button">↻ Actualizar</button>{up}</div>
        <section class="items" aria-label="Archivos y carpetas">{''.join(cards)}</section><p id="noresults" class="empty" hidden>{'No hay coincidencias con tu búsqueda.' if entries else 'Esta carpeta está vacía. Agrega archivos desde PuTTY o SFTP para verlos aquí.'}</p>
        <footer>Electrónica Pi · Acceso de lectura y descarga · {'Carpetas seleccionadas del sistema' if system else 'Carpeta compartida'}</footer></main><script>{JS}</script></body></html>'''
        data = page.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
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
