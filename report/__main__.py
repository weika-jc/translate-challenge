import argparse
import json
import mimetypes
import os
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .build import build_static, prepare_models_data

STATIC_DIR = Path(__file__).parent / 'static'


class ReportHandler(SimpleHTTPRequestHandler):
    models_data: dict = {'models': []}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == '/api/data':
            self._send_json(self.models_data)
            return
        if parsed.path == '/api/records':
            qs = parse_qs(parsed.query)
            model = qs.get('model', [None])[0]
            dataset = qs.get('dataset', [None])[0]
            lang_pair = qs.get('lang_pair', [None])[0]
            min_score = qs.get('min_score', [None])[0]
            max_score = qs.get('max_score', [None])[0]
            q = qs.get('q', [''])[0].lower()
            page = int(qs.get('page', ['1'])[0])
            page_size = int(qs.get('page_size', ['50'])[0])

            records = []
            for m in self.models_data['models']:
                if model and m['name'] != model:
                    continue
                for r in m['records']:
                    item = {**r, 'model': m['name']}
                    if dataset and item['dataset'] != dataset:
                        continue
                    if lang_pair and item['lang_pair'] != lang_pair:
                        continue
                    if min_score is not None and (item['score'] is None or item['score'] < int(min_score)):
                        continue
                    if max_score is not None and (item['score'] is None or item['score'] > int(max_score)):
                        continue
                    if q and q not in item['raw'].lower() and q not in item['trans'].lower() and q not in item['ref'].lower():
                        continue
                    records.append(item)

            total = len(records)
            start = (page - 1) * page_size
            end = start + page_size
            self._send_json({
                'total': total,
                'page': page,
                'page_size': page_size,
                'records': records[start:end],
            })
            return
        if parsed.path == '/':
            self.path = '/index.html'
        return super().do_GET()

    def _send_json(self, data):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def guess_type(self, path):
        ctype = mimetypes.guess_type(path)[0]
        return ctype or 'application/octet-stream'


def resolve_csv_paths(csv_files: list[str], result_dir: str | None) -> list[str]:
    paths = []
    for f in csv_files:
        p = Path(f)
        if p.is_dir():
            paths.extend(sorted(p.glob('*.csv')))
        elif p.exists():
            paths.append(p)
        else:
            print(f'warning: file not found: {f}', file=sys.stderr)
    if result_dir:
        d = Path(result_dir)
        if d.is_dir():
            paths.extend(sorted(d.glob('*.csv')))
    seen = set()
    unique = []
    for p in paths:
        rp = str(p.resolve())
        if rp not in seen:
            seen.add(rp)
            unique.append(rp)
    return unique


def main():
    parser = argparse.ArgumentParser(description='翻译模型评估结果可视化网站')
    parser.add_argument('csv', nargs='*', help='评估结果 CSV 文件路径')
    parser.add_argument('--dir', '-d', default='result', help='扫描 CSV 的目录 (默认: result)')
    parser.add_argument('--port', '-p', type=int, default=8765, help='服务端口 (默认: 8765)')
    parser.add_argument('--host', default='127.0.0.1', help='绑定地址 (默认: 127.0.0.1)')
    parser.add_argument('--build', '-b', action='store_true', help='构建静态网站（无需启动服务）')
    parser.add_argument('--output', '-o', default='docs', help='静态网站输出目录 (默认: docs)')
    args = parser.parse_args()

    paths = resolve_csv_paths(args.csv, args.dir if not args.csv else None)
    if not paths:
        print('error: 未找到 CSV 文件。请指定文件路径或使用 --dir result', file=sys.stderr)
        sys.exit(1)

    print('加载评估数据:')
    for p in paths:
        print(f'  - {p}')

    if args.build:
        out = build_static(args.output, paths)
        size_mb = sum(f.stat().st_size for f in out.rglob('*') if f.is_file()) / (1024 * 1024)
        print(f'\n静态网站已生成: {out.resolve()}')
        print(f'  共 {len(paths)} 个模型, 约 {size_mb:.1f} MB')
        print(
            '  用浏览器打开 index.html，或: '
            f'python -m http.server --directory {out}'
        )
        return

    ReportHandler.models_data = prepare_models_data(paths)
    handler = partial(ReportHandler)
    server = ThreadingHTTPServer((args.host, args.port), handler)

    print(f'\n评估报告网站已启动: http://{args.host}:{args.port}')
    print('按 Ctrl+C 停止服务')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n已停止')
        server.server_close()


if __name__ == '__main__':
    main()
