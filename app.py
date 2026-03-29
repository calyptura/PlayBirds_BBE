#!/usr/bin/env python3
"""
PlayBirds BBE - Biomas Brasileiros em Evidência
Explore os sons das aves nos biomas do Brasil

Desenvolvido para a Rede Sabiá

Multi-tenant support: each tenant (project) has its own biomes,
species, audio and images. The default "bbe" tenant uses the original
flat file structure for backward compatibility.
"""

from flask import Flask, render_template, jsonify, request, Response, send_from_directory, redirect
import csv
import os
import re
import math
import base64
import json
import urllib.request
import urllib.error

import tenants as tenant_mod

# --- CONFIGURAÇÕES ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Railway Volume: se /app/data existe (volume montado), usa para dados persistentes
RAILWAY_DATA = os.environ.get('RAILWAY_VOLUME_MOUNT_PATH', '')
if RAILWAY_DATA and os.path.isdir(RAILWAY_DATA):
    DATA_FOLDER = os.path.join(RAILWAY_DATA, 'data')
    os.makedirs(DATA_FOLDER, exist_ok=True)

    # Migrate old flat structure to new tenant structure on volume
    # Old: data/caatinga/mural_sonoro.csv -> New: data/bbe/caatinga/mural_sonoro.csv
    import shutil
    _old_biome_ids = ['amazonia', 'caatinga', 'pantanal', 'cerrado', 'mata-atlantica', 'pampa']
    _migrated = False
    for _bid in _old_biome_ids:
        _old_dir = os.path.join(DATA_FOLDER, _bid)
        _new_dir = os.path.join(DATA_FOLDER, 'bbe', _bid)
        if os.path.isdir(_old_dir) and not os.path.exists(_new_dir):
            os.makedirs(os.path.dirname(_new_dir), exist_ok=True)
            shutil.move(_old_dir, _new_dir)
            print(f"  Migrado volume: data/{_bid}/ -> data/bbe/{_bid}/")
            _migrated = True

    # Migrate old hotspots.json to tenant config if it exists
    _old_hotspots = os.path.join(DATA_FOLDER, 'hotspots.json')
    if os.path.exists(_old_hotspots):
        # Load and apply to bbe tenant config
        try:
            with open(_old_hotspots, 'r') as _f:
                _hotspot_data = json.load(_f)
            _bbe_config_path = os.path.join(DATA_FOLDER, 'tenants', 'bbe.json')
            if os.path.exists(_bbe_config_path):
                with open(_bbe_config_path, 'r') as _f:
                    _bbe_cfg = json.load(_f)
                for _bid, _vals in _hotspot_data.items():
                    if _bid in _bbe_cfg.get('biomes', {}):
                        _bbe_cfg['biomes'][_bid].update(_vals)
                with open(_bbe_config_path, 'w') as _f:
                    json.dump(_bbe_cfg, _f, indent=2, ensure_ascii=False)
                print(f"  Migrado hotspots.json para tenant bbe config")
            os.rename(_old_hotspots, _old_hotspots + '.bak')
        except Exception as _e:
            print(f"  Aviso: erro ao migrar hotspots: {_e}")

    if _migrated:
        print("  Migracao do volume concluida!")

    # Copy new data from repo to volume if not present
    REPO_DATA = os.path.join(BASE_DIR, 'data')
    if os.path.isdir(REPO_DATA):
        for item in os.listdir(REPO_DATA):
            src = os.path.join(REPO_DATA, item)
            dst = os.path.join(DATA_FOLDER, item)
            if not os.path.exists(dst):
                if os.path.isdir(src):
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)
                print(f"  Copiado para volume: {item}")
    print(f"  Usando Railway Volume para dados: {DATA_FOLDER}")
else:
    DATA_FOLDER = os.path.join(BASE_DIR, 'data')

SONS_FOLDER = os.path.join(BASE_DIR, 'sons')
IMAGES_FOLDER = os.path.join(BASE_DIR, 'images')

AUDIO_EXTENSIONS = ('.wav', '.mp3', '.flac', '.ogg')

# Default tenant slug (uses flat file structure for backward compat)
DEFAULT_TENANT = 'bbe'

# --- GITHUB API ---
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN', '')
GITHUB_REPO = os.environ.get('GITHUB_REPO', 'calyptura/PlayBirds_BBE')
GITHUB_BRANCH = os.environ.get('GITHUB_BRANCH', 'main')


def github_commit_file(file_path, file_bytes, commit_message):
    """Faz commit de um arquivo no GitHub via API."""
    if not GITHUB_TOKEN:
        print("   GITHUB_TOKEN nao configurado - arquivo salvo apenas localmente")
        return False

    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{file_path}"

    sha = None
    get_req = urllib.request.Request(api_url + f'?ref={GITHUB_BRANCH}', headers={
        'Authorization': f'token {GITHUB_TOKEN}',
        'Accept': 'application/vnd.github.v3+json'
    })
    try:
        with urllib.request.urlopen(get_req) as resp:
            existing = json.loads(resp.read())
            sha = existing.get('sha')
    except urllib.error.HTTPError:
        pass

    payload = {
        'message': commit_message,
        'content': base64.b64encode(file_bytes).decode('utf-8'),
        'branch': GITHUB_BRANCH
    }
    if sha:
        payload['sha'] = sha

    data = json.dumps(payload).encode('utf-8')
    put_req = urllib.request.Request(api_url, data=data, method='PUT', headers={
        'Authorization': f'token {GITHUB_TOKEN}',
        'Accept': 'application/vnd.github.v3+json',
        'Content-Type': 'application/json'
    })

    try:
        with urllib.request.urlopen(put_req) as resp:
            print(f"   GitHub commit: {file_path}")
            return True
    except urllib.error.HTTPError as e:
        print(f"   GitHub erro: {e.code} {e.read().decode()}")
        return False


# --- TENANT-AWARE FILE PATHS ---
# All tenants use the same unified structure: {root}/{slug}/{bioma_id}/

def get_sons_folder(tenant_slug, bioma_id):
    """Get the audio folder for a tenant's biome."""
    return os.path.join(SONS_FOLDER, tenant_slug, bioma_id)


def get_images_folder(tenant_slug, bioma_id):
    """Get the images folder for a tenant's biome."""
    return os.path.join(IMAGES_FOLDER, tenant_slug, bioma_id)


def get_tenant_images_folder(tenant_slug):
    """Get the tenant-level images folder (cover, map, etc.)."""
    return os.path.join(IMAGES_FOLDER, tenant_slug)


def get_data_folder(tenant_slug, bioma_id):
    """Get the data folder for a tenant's biome."""
    return os.path.join(DATA_FOLDER, tenant_slug, bioma_id)


# --- DATA LOADING (tenant-aware) ---

def scan_audio_files(tenant_slug, bioma_id):
    """Scan audio files for a tenant's biome."""
    audio_folder = get_sons_folder(tenant_slug, bioma_id)
    if not os.path.isdir(audio_folder):
        return {}

    audio_map = {}
    for f in os.listdir(audio_folder):
        if f.lower().endswith(AUDIO_EXTENSIONS):
            latin_name = os.path.splitext(f)[0].replace('_', ' ')
            audio_map[latin_name] = f
    return audio_map


def find_species_image(latin_name, tenant_slug, bioma_id):
    """Find species image in tenant's biome folder or tenant root."""
    normalized_name = latin_name.strip().replace(' ', '_')

    bioma_img_folder = get_images_folder(tenant_slug, bioma_id)
    tenant_img_folder = get_tenant_images_folder(tenant_slug)
    folders_to_search = [bioma_img_folder, tenant_img_folder]

    for folder in folders_to_search:
        if not os.path.isdir(folder):
            continue
        for ext in ['.jpg', '.jpeg', '.png', '.webp']:
            image_file = normalized_name + ext
            if os.path.exists(os.path.join(folder, image_file)):
                return image_file
            if os.path.exists(os.path.join(folder, image_file.lower())):
                return image_file.lower()
    return None


def load_bioma_data(tenant_slug, bioma_id):
    """Load biome data for a tenant."""
    audio_map = scan_audio_files(tenant_slug, bioma_id)
    if not audio_map:
        return {'mural': {}}

    data_dir = get_data_folder(tenant_slug, bioma_id)
    mural_csv = os.path.join(data_dir, 'mural_sonoro.csv')
    mural_data = {}

    if not os.path.exists(mural_csv):
        return {'mural': {}}

    try:
        with open(mural_csv, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                latin_name = row['Latin name']
                common_name = row.get('Common name', '')
                mural_id = row.get('Mural', 'default').strip().lower().replace(' ', '_')

                audio_file = audio_map.get(latin_name)
                if not audio_file:
                    continue

                species_image = find_species_image(latin_name, tenant_slug, bioma_id)
                if not species_image:
                    continue

                item = {
                    'latinName': latin_name,
                    'commonName': common_name,
                    'x': float(row['X']),
                    'y': float(row['Y']),
                    'size': row.get('Size', 'medium'),
                    'layer': int(row.get('Layer', 1)),
                    'image': species_image,
                    'audioFile': audio_file,
                    'startTime': 0,
                    'detectionDuration': 0
                }
                cw = row.get('Custom width', '')
                if cw:
                    item['customWidth'] = int(float(cw))
                lx = row.get('Label X', '')
                ly = row.get('Label Y', '')
                if lx and ly:
                    item['labelX'] = int(float(lx))
                    item['labelY'] = int(float(ly))
                fl = row.get('Flipped', '')
                if fl == '1':
                    item['flipped'] = True

                if mural_id not in mural_data:
                    mural_data[mural_id] = []
                mural_data[mural_id].append(item)

    except Exception as e:
        print(f"   Erro ao carregar mural: {e}")
        import traceback
        traceback.print_exc()

    return {'mural': mural_data}


# Cache de dados por tenant+bioma
BIOMA_CACHE = {}


def get_bioma_data(tenant_slug, bioma_id):
    cache_key = f'{tenant_slug}/{bioma_id}'
    if cache_key not in BIOMA_CACHE:
        BIOMA_CACHE[cache_key] = load_bioma_data(tenant_slug, bioma_id)
    return BIOMA_CACHE[cache_key]


def get_tenant_biomes(tenant_slug):
    """Get biome configs for a tenant, with availability status."""
    tenant = tenant_mod.get_tenant(DATA_FOLDER, tenant_slug)
    if not tenant:
        return {}
    biomes = tenant.get('biomes', {})
    available = {}
    for bioma_id, info in biomes.items():
        sons_folder = get_sons_folder(tenant_slug, bioma_id)
        has_audio = os.path.isdir(sons_folder) and any(
            f.lower().endswith(AUDIO_EXTENSIONS)
            for f in os.listdir(sons_folder)
        ) if os.path.isdir(sons_folder) else False
        available[bioma_id] = {
            **info,
            'id': bioma_id,
            'disponivel': has_audio
        }
    return available


# --- Legacy BIOMAS dict for backward compat ---
def _get_legacy_biomas():
    tenant = tenant_mod.get_tenant(DATA_FOLDER, DEFAULT_TENANT)
    if tenant:
        return tenant.get('biomes', {})
    return {}


def sanitize_nan(obj):
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):
        return {k: sanitize_nan(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize_nan(v) for v in obj]
    return obj


def create_app():
    app = Flask(__name__,
                template_folder=os.path.join(BASE_DIR, 'templates'),
                static_folder=os.path.join(BASE_DIR, 'static'))

    # ==========================================
    # TENANT MANAGEMENT ROUTES
    # ==========================================

    @app.route('/')
    def index():
        """Landing page: if multiple tenants exist, show tenant selector.
        If only the default tenant exists, show the original map page."""
        all_tenants = tenant_mod.list_tenants(DATA_FOLDER)
        if len(all_tenants) <= 1:
            # Single tenant: show original map page
            biomas = get_tenant_biomes(DEFAULT_TENANT)
            tenant = tenant_mod.get_tenant(DATA_FOLDER, DEFAULT_TENANT)
            title = tenant['name'] if tenant else 'PlayBirds BBE'
            subtitle = tenant['subtitle'] if tenant else ''
            return render_template('index.html',
                                   title=title,
                                   subtitle=subtitle,
                                   biomas=biomas,
                                   base_url='',
                                   tenant_slug=DEFAULT_TENANT)
        # Multiple tenants: show tenant selector
        return render_template('tenant_index.html', tenants=all_tenants)

    # --- TENANT LANDING PAGE ---

    @app.route('/t/<slug>')
    def tenant_landing(slug):
        """Tenant landing page with cover image and biome selection."""
        tenant = tenant_mod.get_tenant(DATA_FOLDER, slug)
        if not tenant:
            return "Projeto não encontrado", 404
        biomes = get_tenant_biomes(slug)
        return render_template('tenant_landing.html',
                               tenant=tenant,
                               biomes=biomes,
                               base_url=f'/t/{slug}',
                               tenant_slug=slug)

    # --- TENANT-SCOPED MURAL & API ---

    @app.route('/t/<slug>/bioma/<bioma_id>')
    def tenant_bioma_page(slug, bioma_id):
        tenant = tenant_mod.get_tenant(DATA_FOLDER, slug)
        if not tenant:
            return "Projeto não encontrado", 404
        biomes = tenant.get('biomes', {})
        if bioma_id not in biomes:
            return "Bioma não encontrado", 404
        bioma_info = biomes[bioma_id]
        return render_template('mural.html',
                               title=tenant['name'],
                               subtitle=tenant.get('subtitle', ''),
                               bioma_id=bioma_id,
                               bioma=bioma_info,
                               base_url=f'/t/{slug}',
                               tenant_slug=slug)

    @app.route('/t/<slug>/api/biomas')
    def tenant_api_biomas(slug):
        return jsonify(get_tenant_biomes(slug))

    @app.route('/t/<slug>/api/bioma/<bioma_id>/mural')
    def tenant_api_bioma_mural(slug, bioma_id):
        data = get_bioma_data(slug, bioma_id)
        return jsonify(sanitize_nan(data['mural']))

    @app.route('/t/<slug>/audio/<bioma_id>/<path:filename>')
    def tenant_serve_audio(slug, bioma_id, filename):
        audio_folder = get_sons_folder(slug, bioma_id)
        file_path = os.path.join(audio_folder, filename)
        if not os.path.exists(file_path):
            return "Audio not found", 404
        return _serve_audio_file(file_path, filename)

    @app.route('/t/<slug>/species-image/<bioma_id>/<path:filename>')
    def tenant_serve_species_image(slug, bioma_id, filename):
        bioma_img = get_images_folder(slug, bioma_id)
        if os.path.exists(os.path.join(bioma_img, filename)):
            return send_from_directory(bioma_img, filename)
        # Fallback to tenant-level images
        tenant_img = get_tenant_images_folder(slug)
        if os.path.exists(os.path.join(tenant_img, filename)):
            return send_from_directory(tenant_img, filename)
        return "Image not found", 404

    @app.route('/t/<slug>/tenant-image/<path:filename>')
    def tenant_serve_tenant_image(slug, filename):
        """Serve tenant-level images (cover, map, etc.)."""
        folder = get_tenant_images_folder(slug)
        if os.path.exists(os.path.join(folder, filename)):
            return send_from_directory(folder, filename)
        return "Image not found", 404

    # --- TENANT ADMIN ---

    @app.route('/t/<slug>/admin')
    def tenant_admin_page(slug):
        tenant = tenant_mod.get_tenant(DATA_FOLDER, slug)
        if not tenant:
            return "Projeto não encontrado", 404
        biomes = tenant.get('biomes', {})
        return render_template('admin.html',
                               title=tenant['name'],
                               biomas=biomes,
                               base_url=f'/t/{slug}',
                               tenant_slug=slug)

    @app.route('/t/<slug>/api/admin/status')
    def tenant_api_admin_status(slug):
        tenant = tenant_mod.get_tenant(DATA_FOLDER, slug)
        if not tenant:
            return jsonify({}), 404
        biomes = tenant.get('biomes', {})
        status = {}
        for bioma_id, info in biomes.items():
            audio_map = scan_audio_files(slug, bioma_id)
            species_with_image = sum(
                1 for ln in audio_map if find_species_image(ln, slug, bioma_id)
            )
            has_bg = False
            bg_folder = get_images_folder(slug, bioma_id)
            if os.path.isdir(bg_folder):
                for ext in ['.png', '.jpg', '.jpeg', '.webp']:
                    if os.path.exists(os.path.join(bg_folder, f'fundo_default{ext}')):
                        has_bg = True
                        break
            csv_path = os.path.join(get_data_folder(slug, bioma_id), 'mural_sonoro.csv')
            positioned = 0
            if os.path.exists(csv_path):
                with open(csv_path, 'r', encoding='utf-8') as f:
                    positioned = sum(1 for _ in csv.DictReader(f))

            status[bioma_id] = {
                'nome': info.get('nome', bioma_id),
                'cor': info.get('cor', '#666'),
                'icone': info.get('icone', ''),
                'totalAudio': len(audio_map),
                'totalWithImage': species_with_image,
                'hasBackground': has_bg,
                'positioned': positioned
            }
        return jsonify(status)

    # --- TENANT EDITOR ---

    @app.route('/t/<slug>/editor/<bioma_id>')
    def tenant_editor_page(slug, bioma_id):
        tenant = tenant_mod.get_tenant(DATA_FOLDER, slug)
        if not tenant:
            return "Projeto não encontrado", 404
        biomes = tenant.get('biomes', {})
        if bioma_id not in biomes:
            return "Bioma não encontrado", 404
        return render_template('editor.html',
                               title=tenant['name'],
                               bioma_id=bioma_id,
                               bioma=biomes[bioma_id],
                               base_url=f'/t/{slug}',
                               tenant_slug=slug)

    @app.route('/t/<slug>/api/editor/<bioma_id>/species')
    def tenant_api_editor_species(slug, bioma_id):
        audio_map = scan_audio_files(slug, bioma_id)
        species = []
        for latin_name, audio_file in sorted(audio_map.items()):
            image = find_species_image(latin_name, slug, bioma_id)
            species.append({
                'latinName': latin_name,
                'audioFile': audio_file,
                'image': image,
                'hasImage': image is not None
            })
        return jsonify(species)

    @app.route('/t/<slug>/api/editor/<bioma_id>/existing')
    def tenant_api_editor_existing(slug, bioma_id):
        data_dir = get_data_folder(slug, bioma_id)
        mural_csv = os.path.join(data_dir, 'mural_sonoro.csv')
        if not os.path.exists(mural_csv):
            return jsonify([])
        rows = []
        with open(mural_csv, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                entry = {
                    'latinName': row['Latin name'],
                    'commonName': row.get('Common name', ''),
                    'x': float(row.get('X', 50)),
                    'y': float(row.get('Y', 50)),
                    'size': row.get('Size', 'medium'),
                    'layer': int(row.get('Layer', 1)),
                    'mural': row.get('Mural', 'default')
                }
                cw = row.get('Custom width', '')
                if cw:
                    entry['customWidth'] = int(float(cw))
                lx = row.get('Label X', '')
                ly = row.get('Label Y', '')
                if lx and ly:
                    entry['labelX'] = int(float(lx))
                    entry['labelY'] = int(float(ly))
                fl = row.get('Flipped', '')
                if fl == '1':
                    entry['flipped'] = True
                rows.append(entry)
        return jsonify(rows)

    @app.route('/t/<slug>/api/editor/<bioma_id>/save', methods=['POST'])
    def tenant_api_editor_save(slug, bioma_id):
        data = request.get_json()
        if not data or 'species' not in data:
            return jsonify({'error': 'Dados inválidos'}), 400
        bioma_data_dir = get_data_folder(slug, bioma_id)
        os.makedirs(bioma_data_dir, exist_ok=True)
        csv_path = os.path.join(bioma_data_dir, 'mural_sonoro.csv')
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['Latin name', 'Common name', 'X', 'Y', 'Size', 'Custom width', 'Layer', 'Mural', 'Label X', 'Label Y', 'Flipped'])
            for sp in data['species']:
                writer.writerow([
                    sp['latinName'], sp.get('commonName', ''),
                    round(sp['x'], 1), round(sp['y'], 1),
                    sp.get('size', 'medium'), sp.get('customWidth', ''),
                    sp.get('layer', 1), sp.get('mural', 'default'),
                    sp.get('labelX', ''), sp.get('labelY', ''),
                    '1' if sp.get('flipped') else ''
                ])
        cache_key = f'{slug}/{bioma_id}'
        BIOMA_CACHE.pop(cache_key, None)
        return jsonify({'ok': True, 'path': csv_path})

    @app.route('/t/<slug>/api/editor/<bioma_id>/upload-species', methods=['POST'])
    def tenant_api_editor_upload_species(slug, bioma_id):
        latin_name = request.form.get('latinName', '').strip()
        if not latin_name:
            return jsonify({'error': 'Nome científico é obrigatório'}), 400
        parts = latin_name.split()
        if len(parts) < 2:
            return jsonify({'error': 'Nome deve ter pelo menos gênero e espécie'}), 400

        standardized = parts[0].capitalize() + ' ' + ' '.join(p.lower() for p in parts[1:])
        file_base = standardized.replace(' ', '_')
        results = {}

        if 'image' in request.files and request.files['image'].filename:
            img_file = request.files['image']
            ext = os.path.splitext(img_file.filename)[1].lower()
            if ext not in ['.jpg', '.jpeg', '.png', '.webp']:
                return jsonify({'error': f'Formato de imagem não suportado: {ext}'}), 400
            dest_folder = get_images_folder(slug, bioma_id)
            os.makedirs(dest_folder, exist_ok=True)
            for old_ext in ['.jpg', '.jpeg', '.png', '.webp']:
                old_path = os.path.join(dest_folder, f'{file_base}{old_ext}')
                if os.path.exists(old_path):
                    os.remove(old_path)
            dest_path = os.path.join(dest_folder, f'{file_base}{ext}')
            img_bytes = img_file.read()
            with open(dest_path, 'wb') as f:
                f.write(img_bytes)
            results['image'] = f'{file_base}{ext}'

        if 'audio' in request.files and request.files['audio'].filename:
            audio_file = request.files['audio']
            ext = os.path.splitext(audio_file.filename)[1].lower()
            if ext not in ['.mp3', '.wav', '.flac', '.ogg']:
                return jsonify({'error': f'Formato de áudio não suportado: {ext}'}), 400
            dest_folder = get_sons_folder(slug, bioma_id)
            os.makedirs(dest_folder, exist_ok=True)
            for old_ext in ['.mp3', '.wav', '.flac', '.ogg']:
                old_path = os.path.join(dest_folder, f'{file_base}{old_ext}')
                if os.path.exists(old_path):
                    os.remove(old_path)
            dest_path = os.path.join(dest_folder, f'{file_base}{ext}')
            audio_bytes = audio_file.read()
            with open(dest_path, 'wb') as f:
                f.write(audio_bytes)
            results['audio'] = f'{file_base}{ext}'

        if not results:
            return jsonify({'error': 'Nenhum arquivo enviado'}), 400

        cache_key = f'{slug}/{bioma_id}'
        BIOMA_CACHE.pop(cache_key, None)
        results['ok'] = True
        results['latinName'] = standardized
        return jsonify(results)

    @app.route('/t/<slug>/api/editor/<bioma_id>/upload-background', methods=['POST'])
    def tenant_api_editor_upload_bg(slug, bioma_id):
        if 'file' not in request.files:
            return jsonify({'error': 'Nenhum arquivo enviado'}), 400
        file = request.files['file']
        if not file.filename:
            return jsonify({'error': 'Arquivo vazio'}), 400
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in ['.jpg', '.jpeg', '.png', '.webp']:
            return jsonify({'error': 'Formato não suportado'}), 400
        mural_name = request.form.get('mural', 'default')
        dest_folder = get_images_folder(slug, bioma_id)
        os.makedirs(dest_folder, exist_ok=True)
        for old_ext in ['.jpg', '.jpeg', '.png', '.webp']:
            old_path = os.path.join(dest_folder, f'fundo_{mural_name}{old_ext}')
            if os.path.exists(old_path):
                os.remove(old_path)
        dest_path = os.path.join(dest_folder, f'fundo_{mural_name}{ext}')
        file.save(dest_path)
        return jsonify({'ok': True, 'filename': f'fundo_{mural_name}{ext}'})

    # --- TENANT MAP EDITOR ---

    @app.route('/t/<slug>/editor/mapa')
    def tenant_editor_mapa_page(slug):
        tenant = tenant_mod.get_tenant(DATA_FOLDER, slug)
        if not tenant:
            return "Projeto não encontrado", 404
        return render_template('editor_mapa.html',
                               title=tenant['name'],
                               biomas=tenant.get('biomes', {}),
                               base_url=f'/t/{slug}',
                               tenant_slug=slug)

    @app.route('/t/<slug>/api/editor/mapa/save', methods=['POST'])
    def tenant_api_editor_mapa_save(slug):
        data = request.get_json()
        if not data or 'hotspots' not in data:
            return jsonify({'error': 'Dados inválidos'}), 400
        tenant = tenant_mod.get_tenant_full(DATA_FOLDER, slug)
        if not tenant:
            return jsonify({'error': 'Tenant não encontrado'}), 404
        biomes = tenant.get('biomes', {})
        for h in data['hotspots']:
            bioma_id = h['id']
            if bioma_id in biomes:
                biomes[bioma_id]['hotspot_x'] = round(h['x'], 1)
                biomes[bioma_id]['hotspot_y'] = round(h['y'], 1)
                biomes[bioma_id]['hotspot_w'] = round(h['w'], 1)
                biomes[bioma_id]['hotspot_h'] = round(h['h'], 1)
        tenant_mod.update_tenant(DATA_FOLDER, slug, {'biomes': biomes})
        return jsonify({'ok': True})

    # ==========================================
    # MASTER ADMIN: TENANT MANAGEMENT API
    # ==========================================

    @app.route('/admin/tenants')
    def admin_tenants_page():
        return render_template('tenants_admin.html')

    @app.route('/api/tenants', methods=['GET'])
    def api_list_tenants():
        return jsonify(tenant_mod.list_tenants(DATA_FOLDER))

    @app.route('/api/tenants', methods=['POST'])
    def api_create_tenant():
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Dados inválidos'}), 400
        slug = data.get('slug', '')
        name = data.get('name', '')
        subtitle = data.get('subtitle', '')
        biomes = data.get('biomes', {})
        kwargs = {}
        if 'theme' in data:
            kwargs['theme'] = data['theme']
        if 'coverImage' in data:
            kwargs['coverImage'] = data['coverImage']
        if 'mapImage' in data:
            kwargs['mapImage'] = data['mapImage']
        if 'adminPassword' in data:
            kwargs['adminPassword'] = data['adminPassword']

        cfg, err = tenant_mod.create_tenant(DATA_FOLDER, slug, name, subtitle, biomes, **kwargs)
        if err:
            return jsonify({'error': err}), 400
        return jsonify(cfg), 201

    @app.route('/api/tenants/<slug>', methods=['GET'])
    def api_get_tenant(slug):
        tenant = tenant_mod.get_tenant(DATA_FOLDER, slug)
        if not tenant:
            return jsonify({'error': 'Não encontrado'}), 404
        return jsonify(tenant)

    @app.route('/api/tenants/<slug>', methods=['PUT'])
    def api_update_tenant(slug):
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Dados inválidos'}), 400
        cfg, err = tenant_mod.update_tenant(DATA_FOLDER, slug, data)
        if err:
            return jsonify({'error': err}), 400
        return jsonify(cfg)

    @app.route('/api/tenants/<slug>', methods=['DELETE'])
    def api_delete_tenant(slug):
        if slug == DEFAULT_TENANT:
            return jsonify({'error': 'Não é possível deletar o tenant padrão'}), 400
        if tenant_mod.delete_tenant(DATA_FOLDER, slug):
            return jsonify({'ok': True})
        return jsonify({'error': 'Não encontrado'}), 404

    @app.route('/api/tenants/<slug>/biomes', methods=['POST'])
    def api_add_biome(slug):
        data = request.get_json()
        if not data or 'id' not in data:
            return jsonify({'error': 'ID do bioma é obrigatório'}), 400
        biome_id = data.pop('id')
        biome, err = tenant_mod.add_biome_to_tenant(DATA_FOLDER, slug, biome_id, data)
        if err:
            return jsonify({'error': err}), 400
        return jsonify(biome), 201

    @app.route('/api/tenants/<slug>/biomes/<biome_id>', methods=['DELETE'])
    def api_remove_biome(slug, biome_id):
        if tenant_mod.remove_biome_from_tenant(DATA_FOLDER, slug, biome_id):
            return jsonify({'ok': True})
        return jsonify({'error': 'Não encontrado'}), 404

    # --- TENANT COVER/MAP IMAGE UPLOAD ---

    @app.route('/api/tenants/<slug>/upload-image', methods=['POST'])
    def api_tenant_upload_image(slug):
        """Upload cover or map image for a tenant."""
        tenant = tenant_mod.get_tenant(DATA_FOLDER, slug)
        if not tenant:
            return jsonify({'error': 'Tenant não encontrado'}), 404
        if 'file' not in request.files:
            return jsonify({'error': 'Nenhum arquivo enviado'}), 400
        file = request.files['file']
        if not file.filename:
            return jsonify({'error': 'Arquivo vazio'}), 400
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in ['.jpg', '.jpeg', '.png', '.webp']:
            return jsonify({'error': 'Formato não suportado'}), 400

        image_type = request.form.get('type', 'cover')  # 'cover' or 'map'
        dest_folder = get_tenant_images_folder(slug)
        os.makedirs(dest_folder, exist_ok=True)

        filename = f'{image_type}{ext}'
        dest_path = os.path.join(dest_folder, filename)
        file.save(dest_path)

        # Update tenant config
        field = 'coverImage' if image_type == 'cover' else 'mapImage'
        tenant_mod.update_tenant(DATA_FOLDER, slug, {field: filename})

        return jsonify({'ok': True, 'filename': filename})

    # ==========================================
    # LEGACY ROUTES (backward compatibility for BBE)
    # ==========================================

    @app.route('/bioma/<bioma_id>')
    def bioma_page(bioma_id):
        biomes = _get_legacy_biomas()
        if bioma_id not in biomes:
            return "Bioma não encontrado", 404
        bioma_info = biomes[bioma_id]
        tenant = tenant_mod.get_tenant(DATA_FOLDER, DEFAULT_TENANT)
        return render_template('mural.html',
                               title=tenant['name'] if tenant else 'PlayBirds BBE',
                               subtitle=tenant['subtitle'] if tenant else '',
                               bioma_id=bioma_id,
                               bioma=bioma_info,
                               base_url='',
                               tenant_slug=DEFAULT_TENANT)

    @app.route('/api/biomas')
    def api_biomas():
        return jsonify(get_tenant_biomes(DEFAULT_TENANT))

    @app.route('/api/bioma/<bioma_id>/mural')
    def api_bioma_mural(bioma_id):
        data = get_bioma_data(DEFAULT_TENANT, bioma_id)
        return jsonify(sanitize_nan(data['mural']))

    @app.route('/audio/<bioma_id>/<path:filename>')
    def serve_audio(bioma_id, filename):
        audio_folder = get_sons_folder(DEFAULT_TENANT, bioma_id)
        file_path = os.path.join(audio_folder, filename)
        if not os.path.exists(file_path):
            return "Audio not found", 404
        return _serve_audio_file(file_path, filename)

    @app.route('/species-image/<bioma_id>/<path:filename>')
    def serve_species_image(bioma_id, filename):
        bioma_img = get_images_folder(DEFAULT_TENANT, bioma_id)
        if os.path.exists(os.path.join(bioma_img, filename)):
            return send_from_directory(bioma_img, filename)
        # Fallback to tenant-level images
        tenant_img = get_tenant_images_folder(DEFAULT_TENANT)
        if os.path.exists(os.path.join(tenant_img, filename)):
            return send_from_directory(tenant_img, filename)
        return "Image not found", 404

    @app.route('/map-image/<path:filename>')
    def serve_map_image(filename):
        return send_from_directory(get_tenant_images_folder(DEFAULT_TENANT), filename)

    @app.route('/admin')
    def admin_page():
        return redirect('/admin/tenants')

    @app.route('/api/admin/status')
    def api_admin_status():
        return tenant_api_admin_status(DEFAULT_TENANT)

    @app.route('/editor/<bioma_id>')
    def editor_page(bioma_id):
        biomes = _get_legacy_biomas()
        if bioma_id not in biomes:
            return "Bioma não encontrado", 404
        return render_template('editor.html',
                               title='PlayBirds BBE',
                               bioma_id=bioma_id,
                               bioma=biomes[bioma_id],
                               base_url='',
                               tenant_slug=DEFAULT_TENANT)

    @app.route('/api/editor/<bioma_id>/species')
    def api_editor_species(bioma_id):
        return tenant_api_editor_species(DEFAULT_TENANT, bioma_id)

    @app.route('/api/editor/<bioma_id>/existing')
    def api_editor_existing(bioma_id):
        return tenant_api_editor_existing(DEFAULT_TENANT, bioma_id)

    @app.route('/api/editor/<bioma_id>/save', methods=['POST'])
    def api_editor_save(bioma_id):
        return tenant_api_editor_save(DEFAULT_TENANT, bioma_id)

    @app.route('/api/editor/<bioma_id>/upload-species', methods=['POST'])
    def api_editor_upload_species(bioma_id):
        return tenant_api_editor_upload_species(DEFAULT_TENANT, bioma_id)

    @app.route('/api/editor/<bioma_id>/upload-background', methods=['POST'])
    def api_editor_upload_bg(bioma_id):
        return tenant_api_editor_upload_bg(DEFAULT_TENANT, bioma_id)

    @app.route('/editor/mapa')
    def editor_mapa_page():
        biomes = _get_legacy_biomas()
        return render_template('editor_mapa.html',
                               title='PlayBirds BBE',
                               biomas=biomes,
                               base_url='',
                               tenant_slug=DEFAULT_TENANT)

    @app.route('/api/editor/mapa/save', methods=['POST'])
    def api_editor_mapa_save():
        return tenant_api_editor_mapa_save(DEFAULT_TENANT)

    # ==========================================
    # SHARED UTILITIES
    # ==========================================

    def _serve_audio_file(file_path, filename):
        """Serve an audio file with Range request support."""
        file_size = os.path.getsize(file_path)
        ext = os.path.splitext(filename)[1].lower()
        content_types = {
            '.mp3': 'audio/mpeg', '.wav': 'audio/wav',
            '.flac': 'audio/flac', '.ogg': 'audio/ogg'
        }
        content_type = content_types.get(ext, 'audio/mpeg')

        range_header = request.headers.get('Range', None)
        if range_header:
            match = re.search(r'bytes=(\d+)-(\d*)', range_header)
            if match:
                start = int(match.group(1))
                end = int(match.group(2)) if match.group(2) else file_size - 1
                end = min(end, file_size - 1)
                length = end - start + 1
                with open(file_path, 'rb') as f:
                    f.seek(start)
                    data = f.read(length)
                response = Response(data, 206, mimetype=content_type)
                response.headers['Content-Range'] = f'bytes {start}-{end}/{file_size}'
                response.headers['Accept-Ranges'] = 'bytes'
                response.headers['Content-Length'] = length
                return response

        return send_from_directory(os.path.dirname(file_path), os.path.basename(file_path), mimetype=content_type)

    return app


app = create_app()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5050))
    app.run(host='0.0.0.0', port=port, debug=True)
