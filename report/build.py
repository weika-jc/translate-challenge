import json
import shutil
from pathlib import Path

from .analyze import load_models
from .pricing import get_pricing

STATIC_DIR = Path(__file__).parent / 'static'


def prepare_models_data(csv_paths: list[str]) -> dict:
    models_data = load_models(csv_paths)
    models_data['pricing'] = {}
    for m in models_data['models']:
        metadata_path = Path(m['path']).with_suffix('.metadata.json')
        if metadata_path.exists():
            metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
            m['experiment'] = {
                'api': metadata.get('api'),
                'reasoning_effort': metadata.get('additionalModelRequestFields', {})
                    .get('reasoning', {}).get('effort'),
                'explicit_cache_configuration': metadata.get('explicit_cache_configuration'),
                'prompt_file': metadata.get('prompt_file'),
            }
        p = get_pricing(m['name'])
        models_data['pricing'][m['name']] = {
            'input_per_million': p.input_per_million,
            'output_per_million': p.output_per_million,
            'billing_mode': p.billing_mode,
            'cached_input_ratio': p.cached_input_ratio,
            'cache_write_input_ratio': p.cache_write_input_ratio,
            'cache_read_per_million': p.cache_read_per_million,
            'cache_write_per_million': p.cache_write_per_million,
        }
    return models_data


def build_static(output_dir: str | Path, csv_paths: list[str]) -> Path:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    data = prepare_models_data(csv_paths)

    shutil.copy2(STATIC_DIR / 'style.css', output / 'style.css')
    shutil.copy2(STATIC_DIR / 'app.js', output / 'app.js')

    data_js = 'window.REPORT_DATA = ' + json.dumps(data, ensure_ascii=False) + ';\n'
    (output / 'data.js').write_text(data_js, encoding='utf-8')

    html = (STATIC_DIR / 'index.html').read_text(encoding='utf-8')
    for needle in ('<script src="app.js"></script>', '<script src="/app.js"></script>'):
        if needle in html:
            html = html.replace(
                needle,
                '<script src="data.js"></script>\n  <script src="app.js"></script>',
            )
            break
    (output / 'index.html').write_text(html, encoding='utf-8')

    return output
