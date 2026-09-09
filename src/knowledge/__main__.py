"""python -m src.knowledge: library management without the agent stack."""
import argparse
import asyncio
import json
import os
from pathlib import Path
from .service import KnowledgeBaseService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default=os.getenv('FRS_KB_DIR', str(Path(__file__).resolve().parents[2] / 'data/knowledge')))
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('list')
    create = commands.add_parser('create'); create.add_argument('name')
    ingest = commands.add_parser('ingest'); ingest.add_argument('library'); ingest.add_argument('file'); ingest.add_argument('--metadata', default='{}')
    search = commands.add_parser('search'); search.add_argument('library'); search.add_argument('query'); search.add_argument('--as-of', default='')
    args = parser.parse_args()
    service = KnowledgeBaseService(args.root)
    if args.command == 'create':
        result = service.create_library(args.name)
    elif args.command == 'list':
        result = service.libraries()
    elif args.command == 'ingest':
        path = Path(args.file)
        result = service.enqueue(args.library, path.name, path.read_bytes(), json.loads(args.metadata))
        if result['job_id']:
            asyncio.run(service.process(result['job_id']))
            result['job'] = service.job(result['job_id'])
    else:
        result = asyncio.run(service.search(args.query, [args.library], {'as_of': args.as_of}))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
