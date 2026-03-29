"""
Tenant management for PlayBirds BBE.
Each tenant is a JSON file in the tenants directory.
Inspired by the Naturalists Alive (dashbio) tenant system.
"""

import os
import json
import re

DEFAULTS = {
    'name': '',
    'subtitle': '',
    'slug': '',
    'coverImage': '',        # filename for landing page hero image
    'mapImage': '',          # filename for biome selection map (optional)
    'theme': {
        'primaryColor': '#1b5e20',
        'accentColor': '#66bb6a',
    },
    'biomes': {},            # biome configs keyed by biome_id
    'extraContent': {},      # future: references, tourism links per biome
    'adminPassword': '',
    'language': 'pt',
}

# Biome defaults within a tenant
BIOME_DEFAULTS = {
    'nome': '',
    'descricao': '',
    'cor': '#666666',
    'icone': '',
    'hotspot_x': 10,
    'hotspot_y': 10,
    'hotspot_w': 15,
    'hotspot_h': 10,
}


def _tenants_dir(data_folder):
    d = os.path.join(data_folder, 'tenants')
    os.makedirs(d, exist_ok=True)
    return d


def _sanitize_slug(slug):
    """Sanitize slug to alphanumeric + hyphens only."""
    return re.sub(r'[^a-z0-9-]', '', slug.lower().strip())[:50]


def _tenant_path(data_folder, slug):
    safe_slug = _sanitize_slug(slug)
    if not safe_slug:
        return None
    return os.path.join(_tenants_dir(data_folder), f'{safe_slug}.json')


def list_tenants(data_folder):
    """List all tenants (returns list of {slug, name, subtitle, coverImage})."""
    tenants_path = _tenants_dir(data_folder)
    tenants = []
    for fname in sorted(os.listdir(tenants_path)):
        if not fname.endswith('.json'):
            continue
        slug = fname[:-5]
        try:
            with open(os.path.join(tenants_path, fname), 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            tenants.append({
                'slug': slug,
                'name': cfg.get('name', slug),
                'subtitle': cfg.get('subtitle', ''),
                'coverImage': cfg.get('coverImage', ''),
                'theme': cfg.get('theme', DEFAULTS['theme']),
            })
        except (json.JSONDecodeError, OSError):
            continue
    return tenants


def get_tenant(data_folder, slug):
    """Get full tenant config. Returns None if not found."""
    path = _tenant_path(data_folder, slug)
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        # Merge with defaults
        result = {**DEFAULTS, **cfg}
        result['slug'] = _sanitize_slug(slug)
        # Don't expose password to frontend
        result.pop('adminPassword', None)
        return result
    except (json.JSONDecodeError, OSError):
        return None


def get_tenant_full(data_folder, slug):
    """Get full tenant config including adminPassword (for admin use)."""
    path = _tenant_path(data_folder, slug)
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        result = {**DEFAULTS, **cfg}
        result['slug'] = _sanitize_slug(slug)
        return result
    except (json.JSONDecodeError, OSError):
        return None


def create_tenant(data_folder, slug, name, subtitle='', biomes=None, **kwargs):
    """Create a new tenant. Returns the config or None if slug exists."""
    safe_slug = _sanitize_slug(slug)
    if not safe_slug or len(safe_slug) < 3:
        return None, 'Slug deve ter pelo menos 3 caracteres (a-z, 0-9, hifens)'

    path = _tenant_path(data_folder, safe_slug)
    if os.path.exists(path):
        return None, 'Tenant já existe'

    if not name:
        return None, 'Nome é obrigatório'

    cfg = {
        **DEFAULTS,
        'name': name,
        'subtitle': subtitle,
        'slug': safe_slug,
        'biomes': biomes or {},
    }
    # Apply extra kwargs (theme, coverImage, etc.)
    for k, v in kwargs.items():
        if k in DEFAULTS:
            cfg[k] = v

    with open(path, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

    # Create data directories for the tenant
    _ensure_tenant_dirs(data_folder, safe_slug, cfg.get('biomes', {}))

    return cfg, None


def update_tenant(data_folder, slug, updates):
    """Update a tenant config. Returns updated config or None."""
    safe_slug = _sanitize_slug(slug)
    path = _tenant_path(data_folder, safe_slug)
    if not path or not os.path.exists(path):
        return None, 'Tenant não encontrado'

    with open(path, 'r', encoding='utf-8') as f:
        cfg = json.load(f)

    # Merge updates
    for k, v in updates.items():
        if k == 'slug':
            continue  # Can't change slug
        cfg[k] = v

    with open(path, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

    # Ensure dirs for any new biomes
    _ensure_tenant_dirs(data_folder, safe_slug, cfg.get('biomes', {}))

    return cfg, None


def delete_tenant(data_folder, slug):
    """Delete a tenant config file. Returns True if deleted."""
    safe_slug = _sanitize_slug(slug)
    path = _tenant_path(data_folder, safe_slug)
    if not path or not os.path.exists(path):
        return False
    os.remove(path)
    return True


def add_biome_to_tenant(data_folder, slug, biome_id, biome_config):
    """Add or update a biome within a tenant."""
    safe_slug = _sanitize_slug(slug)
    tenant = get_tenant_full(data_folder, safe_slug)
    if not tenant:
        return None, 'Tenant não encontrado'

    biome_id = re.sub(r'[^a-z0-9-]', '', biome_id.lower().strip())
    if not biome_id:
        return None, 'ID do bioma inválido'

    biome = {**BIOME_DEFAULTS, **biome_config}
    tenant['biomes'][biome_id] = biome

    update_tenant(data_folder, safe_slug, {'biomes': tenant['biomes']})

    # Ensure directories
    _ensure_tenant_dirs(data_folder, safe_slug, {biome_id: biome})

    return biome, None


def remove_biome_from_tenant(data_folder, slug, biome_id):
    """Remove a biome from a tenant config."""
    safe_slug = _sanitize_slug(slug)
    tenant = get_tenant_full(data_folder, safe_slug)
    if not tenant:
        return False
    tenant['biomes'].pop(biome_id, None)
    update_tenant(data_folder, safe_slug, {'biomes': tenant['biomes']})
    return True


def _ensure_tenant_dirs(data_folder, slug, biomes):
    """Create the directory structure for a tenant's biomes."""
    base_dir = os.path.dirname(data_folder)  # project root or volume root

    for biome_id in biomes:
        # Data dir for CSVs
        os.makedirs(os.path.join(data_folder, slug, biome_id), exist_ok=True)
        # Sons dir for audio
        sons_dir = os.path.join(base_dir, 'sons', slug, biome_id)
        os.makedirs(sons_dir, exist_ok=True)
        # Images dir for species + backgrounds
        img_dir = os.path.join(base_dir, 'images', slug, biome_id)
        os.makedirs(img_dir, exist_ok=True)

    # Tenant-level images dir (for cover image, map, etc.)
    os.makedirs(os.path.join(base_dir, 'images', slug), exist_ok=True)
