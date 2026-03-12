#!/usr/bin/env python3
"""
PlayBirds BBE - Biomas Brasileiros em Evidência
Explore os sons das aves nos biomas do Brasil

Desenvolvido para a Rede Sabiá
"""

from flask import Flask, render_template, jsonify, request, Response, send_from_directory
import csv
import os
import re
import math

# --- CONFIGURAÇÕES ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FOLDER = os.path.join(BASE_DIR, 'data')
SONS_FOLDER = os.path.join(BASE_DIR, 'sons')
IMAGES_FOLDER = os.path.join(BASE_DIR, 'images')

PROJECT_TITLE = 'PlayBirds BBE'
PROJECT_SUBTITLE = 'Biomas Brasileiros em Evidência'

AUDIO_EXTENSIONS = ('.wav', '.mp3', '.flac', '.ogg')

# Biomas suportados (adicione novos aqui)
BIOMAS = {
    'amazonia': {
        'nome': 'Amazon',
        'descricao': 'The largest tropical rainforest on Earth',
        'cor': '#1b5e20',
        'icone': '🌿',
        'hotspot_x': 5, 'hotspot_y': 28, 'hotspot_w': 18, 'hotspot_h': 10
    },
    'caatinga': {
        'nome': 'Caatinga',
        'descricao': 'Brazil\'s unique semi-arid biome',
        'cor': '#c4a35a',
        'icone': '🌵',
        'hotspot_x': 68, 'hotspot_y': 28, 'hotspot_w': 18, 'hotspot_h': 10
    },
    'pantanal': {
        'nome': 'Pantanal',
        'descricao': 'The world\'s largest tropical wetland',
        'cor': '#0277bd',
        'icone': '💧',
        'hotspot_x': 12, 'hotspot_y': 48, 'hotspot_w': 16, 'hotspot_h': 10
    },
    'cerrado': {
        'nome': 'Cerrado',
        'descricao': 'The most biodiverse savanna on the planet',
        'cor': '#8d6e34',
        'icone': '🌾',
        'hotspot_x': 17, 'hotspot_y': 58, 'hotspot_w': 14, 'hotspot_h': 10
    },
    'mata-atlantica': {
        'nome': 'Atlantic Forest',
        'descricao': 'One of the richest biodiversity hotspots',
        'cor': '#2e7d32',
        'icone': '🌳',
        'hotspot_x': 52, 'hotspot_y': 55, 'hotspot_w': 22, 'hotspot_h': 10
    },
    'pampa': {
        'nome': 'Pampa',
        'descricao': 'The grasslands of southern Brazil',
        'cor': '#7cb342',
        'icone': '🌱',
        'hotspot_x': 39, 'hotspot_y': 78, 'hotspot_w': 14, 'hotspot_h': 10
    }
}

# Carregar hotspots salvos (se existirem)
import json as _json
_hotspots_path = os.path.join(DATA_FOLDER, 'hotspots.json')
if os.path.exists(_hotspots_path):
    with open(_hotspots_path, 'r') as _f:
        _saved = _json.load(_f)
        for _bid, _vals in _saved.items():
            if _bid in BIOMAS:
                BIOMAS[_bid].update(_vals)


def scan_audio_files(bioma_id):
    """
    Escaneia sons/<bioma_id>/ e retorna dict {latin_name: filename}.
    Nome do arquivo = Nome_cientifico.ext (ex: Paroaria_dominicana.mp3)
    """
    audio_folder = os.path.join(SONS_FOLDER, bioma_id)
    if not os.path.isdir(audio_folder):
        return {}

    audio_map = {}
    for f in os.listdir(audio_folder):
        if f.lower().endswith(AUDIO_EXTENSIONS):
            # Extrair nome científico: "Paroaria_dominicana.mp3" -> "Paroaria dominicana"
            latin_name = os.path.splitext(f)[0].replace('_', ' ')
            audio_map[latin_name] = f
            print(f"   🎵 {latin_name} → {f}")

    return audio_map


def find_species_image(latin_name, bioma_id):
    """Procura imagem da espécie na pasta do bioma ou na pasta geral."""
    normalized_name = latin_name.strip().replace(' ', '_')

    bioma_img_folder = os.path.join(IMAGES_FOLDER, bioma_id)
    folders_to_search = [bioma_img_folder, IMAGES_FOLDER]

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


def load_bioma_data(bioma_id):
    """
    Carrega os dados de um bioma.

    Estrutura esperada:
    - sons/<bioma_id>/          → áudios nomeados como Nome_cientifico.mp3
    - images/<bioma_id>/        → imagens das aves + fundo do mural
    - data/<bioma_id>/mural_sonoro.csv → posições no mural (Latin name, Common name, X, Y, Size, Layer, Mural)
    """
    print(f"🔄 Carregando bioma: {bioma_id}")

    # 1. Escanear áudios
    audio_map = scan_audio_files(bioma_id)
    if not audio_map:
        print(f"   ⚠️ Nenhum áudio encontrado em sons/{bioma_id}/")
        return {'mural': {}}

    # 2. Carregar mural_sonoro.csv
    mural_csv = os.path.join(DATA_FOLDER, bioma_id, 'mural_sonoro.csv')
    mural_data = {}

    if not os.path.exists(mural_csv):
        print(f"   ⚠️ mural_sonoro.csv não encontrado em data/{bioma_id}/")
        return {'mural': {}}

    try:
        with open(mural_csv, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)

            for row in reader:
                latin_name = row['Latin name']
                common_name = row.get('Common name', '')
                mural_id = row.get('Mural', 'default').strip().lower().replace(' ', '_')

                # Verificar se tem áudio
                audio_file = audio_map.get(latin_name)
                if not audio_file:
                    print(f"   ⚠️ Áudio não encontrado para: {latin_name}")
                    continue

                # Verificar se tem imagem
                species_image = find_species_image(latin_name, bioma_id)
                if not species_image:
                    print(f"   ⚠️ Imagem não encontrada para: {latin_name}")
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
                    'detectionDuration': 0  # 0 = tocar o áudio inteiro
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
                print(f"   ✅ [{mural_id}] {latin_name} ({item['size']})")

    except Exception as e:
        print(f"   ❌ Erro ao carregar mural: {e}")
        import traceback
        traceback.print_exc()

    total = sum(len(v) for v in mural_data.values())
    print(f"   🖼️ {total} espécies em {len(mural_data)} mural(is)")

    return {'mural': mural_data}


# Cache de dados por bioma
BIOMA_CACHE = {}


def get_bioma_data(bioma_id):
    """Retorna dados do bioma, carregando do cache ou disco."""
    if bioma_id not in BIOMA_CACHE:
        BIOMA_CACHE[bioma_id] = load_bioma_data(bioma_id)
    return BIOMA_CACHE[bioma_id]


def get_available_biomas():
    """Retorna biomas — disponível se tem pasta de sons com áudios."""
    available = {}
    for bioma_id, info in BIOMAS.items():
        sons_folder = os.path.join(SONS_FOLDER, bioma_id)
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


def sanitize_nan(obj):
    """Sanitiza valores NaN para JSON."""
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

    @app.route('/')
    def index():
        biomas = get_available_biomas()
        return render_template('index.html',
                               title=PROJECT_TITLE,
                               subtitle=PROJECT_SUBTITLE,
                               biomas=biomas)

    @app.route('/bioma/<bioma_id>')
    def bioma_page(bioma_id):
        if bioma_id not in BIOMAS:
            return "Bioma não encontrado", 404
        bioma_info = BIOMAS[bioma_id]
        return render_template('mural.html',
                               title=PROJECT_TITLE,
                               subtitle=PROJECT_SUBTITLE,
                               bioma_id=bioma_id,
                               bioma=bioma_info)

    @app.route('/api/biomas')
    def api_biomas():
        return jsonify(get_available_biomas())

    @app.route('/api/bioma/<bioma_id>/mural')
    def api_bioma_mural(bioma_id):
        data = get_bioma_data(bioma_id)
        return jsonify(sanitize_nan(data['mural']))

    @app.route('/audio/<bioma_id>/<path:filename>')
    def serve_audio(bioma_id, filename):
        """Serve arquivos de áudio da pasta sons/<bioma_id>/ com suporte a Range requests."""
        audio_folder = os.path.join(SONS_FOLDER, bioma_id)
        file_path = os.path.join(audio_folder, filename)

        if not os.path.exists(file_path):
            return "Audio not found", 404

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

        return send_from_directory(audio_folder, filename, mimetype=content_type)

    @app.route('/species-image/<bioma_id>/<path:filename>')
    def serve_species_image(bioma_id, filename):
        """Serve imagens — procura na pasta do bioma primeiro, depois na geral."""
        bioma_img = os.path.join(IMAGES_FOLDER, bioma_id)
        if os.path.exists(os.path.join(bioma_img, filename)):
            return send_from_directory(bioma_img, filename)
        if os.path.exists(os.path.join(IMAGES_FOLDER, filename)):
            return send_from_directory(IMAGES_FOLDER, filename)
        return "Image not found", 404

    @app.route('/map-image/<path:filename>')
    def serve_map_image(filename):
        """Serve imagem do mapa de biomas."""
        return send_from_directory(os.path.join(IMAGES_FOLDER, 'mapa'), filename)

    # --- EDITOR DE MURAL ---

    @app.route('/editor/<bioma_id>')
    def editor_page(bioma_id):
        if bioma_id not in BIOMAS:
            return "Bioma não encontrado", 404
        bioma_info = BIOMAS[bioma_id]
        return render_template('editor.html',
                               title=PROJECT_TITLE,
                               bioma_id=bioma_id,
                               bioma=bioma_info)

    @app.route('/api/editor/<bioma_id>/species')
    def api_editor_species(bioma_id):
        """Lista espécies disponíveis (que têm áudio e imagem) para o editor."""
        audio_map = scan_audio_files(bioma_id)
        species = []
        for latin_name, audio_file in sorted(audio_map.items()):
            image = find_species_image(latin_name, bioma_id)
            species.append({
                'latinName': latin_name,
                'audioFile': audio_file,
                'image': image,  # pode ser None
                'hasImage': image is not None
            })
        return jsonify(species)

    @app.route('/api/editor/<bioma_id>/existing')
    def api_editor_existing(bioma_id):
        """Carrega posições existentes do mural_sonoro.csv (se existir)."""
        mural_csv = os.path.join(DATA_FOLDER, bioma_id, 'mural_sonoro.csv')
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

    @app.route('/api/editor/<bioma_id>/save', methods=['POST'])
    def api_editor_save(bioma_id):
        """Salva o mural_sonoro.csv com as posições do editor."""
        data = request.get_json()
        if not data or 'species' not in data:
            return jsonify({'error': 'Dados inválidos'}), 400

        # Garantir que a pasta existe
        bioma_data_dir = os.path.join(DATA_FOLDER, bioma_id)
        os.makedirs(bioma_data_dir, exist_ok=True)

        csv_path = os.path.join(bioma_data_dir, 'mural_sonoro.csv')

        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['Latin name', 'Common name', 'X', 'Y', 'Size', 'Custom width', 'Layer', 'Mural', 'Label X', 'Label Y', 'Flipped'])
            for sp in data['species']:
                writer.writerow([
                    sp['latinName'],
                    sp.get('commonName', ''),
                    round(sp['x'], 1),
                    round(sp['y'], 1),
                    sp.get('size', 'medium'),
                    sp.get('customWidth', ''),
                    sp.get('layer', 1),
                    sp.get('mural', 'default'),
                    sp.get('labelX', ''),
                    sp.get('labelY', ''),
                    '1' if sp.get('flipped') else ''
                ])

        # Limpar cache para recarregar dados
        BIOMA_CACHE.pop(bioma_id, None)

        return jsonify({'ok': True, 'path': csv_path})

    # --- EDITOR DE HOTSPOTS DO MAPA ---

    @app.route('/editor/mapa')
    def editor_mapa_page():
        return render_template('editor_mapa.html',
                               title=PROJECT_TITLE,
                               biomas=BIOMAS)

    @app.route('/api/editor/mapa/save', methods=['POST'])
    def api_editor_mapa_save():
        """Salva as posições dos hotspots no app.py."""
        data = request.get_json()
        if not data or 'hotspots' not in data:
            return jsonify({'error': 'Dados inválidos'}), 400

        # Atualizar BIOMAS em memória
        for h in data['hotspots']:
            bioma_id = h['id']
            if bioma_id in BIOMAS:
                BIOMAS[bioma_id]['hotspot_x'] = round(h['x'], 1)
                BIOMAS[bioma_id]['hotspot_y'] = round(h['y'], 1)
                BIOMAS[bioma_id]['hotspot_w'] = round(h['w'], 1)
                BIOMAS[bioma_id]['hotspot_h'] = round(h['h'], 1)

        # Salvar num JSON para persistência
        import json
        hotspots_path = os.path.join(DATA_FOLDER, 'hotspots.json')
        os.makedirs(DATA_FOLDER, exist_ok=True)
        hotspots = {}
        for bioma_id, info in BIOMAS.items():
            hotspots[bioma_id] = {
                'hotspot_x': info['hotspot_x'],
                'hotspot_y': info['hotspot_y'],
                'hotspot_w': info['hotspot_w'],
                'hotspot_h': info['hotspot_h']
            }
        with open(hotspots_path, 'w') as f:
            json.dump(hotspots, f, indent=2)

        return jsonify({'ok': True})

    @app.route('/api/editor/<bioma_id>/upload-background', methods=['POST'])
    def api_editor_upload_bg(bioma_id):
        """Recebe upload da imagem de fundo do mural."""
        if 'file' not in request.files:
            return jsonify({'error': 'Nenhum arquivo enviado'}), 400

        file = request.files['file']
        if not file.filename:
            return jsonify({'error': 'Arquivo vazio'}), 400

        # Determinar extensão
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in ['.jpg', '.jpeg', '.png', '.webp']:
            return jsonify({'error': 'Formato não suportado (use jpg, png ou webp)'}), 400

        # Salvar como fundo_default
        mural_name = request.form.get('mural', 'default')
        dest_folder = os.path.join(IMAGES_FOLDER, bioma_id)
        os.makedirs(dest_folder, exist_ok=True)

        # Remover fundos antigos
        for old_ext in ['.jpg', '.jpeg', '.png', '.webp']:
            old_path = os.path.join(dest_folder, f'fundo_{mural_name}{old_ext}')
            if os.path.exists(old_path):
                os.remove(old_path)

        dest_path = os.path.join(dest_folder, f'fundo_{mural_name}{ext}')
        file.save(dest_path)

        return jsonify({'ok': True, 'filename': f'fundo_{mural_name}{ext}'})

    return app


if __name__ == '__main__':
    app = create_app()
    port = int(os.environ.get('PORT', 5050))
    app.run(host='0.0.0.0', port=port, debug=True)
