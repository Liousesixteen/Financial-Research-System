"""Evaluate knowledge retrieval against hand-labelled evidence IDs.

Dataset JSONL rows: {"query": "...", "relevant_ids": ["chunk-id"],
                     "kb_ids": ["library-id"], "filters": {}}.
"""

import argparse
import asyncio
import json
import time
from pathlib import Path


async def evaluate(service, cases, default_kb_ids=(), top_k=8):
    if not cases:
        raise ValueError('Evaluation dataset is empty')
    details = []
    for case in cases:
        if 'relevant_ids' not in case:
            raise ValueError('Each evaluation case needs relevant_ids (empty for no-answer cases)')
        relevant = set(case['relevant_ids'])
        started = time.perf_counter()
        result = await service.search(case['query'], case.get('kb_ids', default_kb_ids),
                                      case.get('filters', {}), top_k)
        latency_ms = (time.perf_counter() - started) * 1000
        retrieved = [item['evidence_id'] for item in result['results']]
        hits = relevant.intersection(retrieved)
        first_rank = next((index for index, key in enumerate(retrieved, 1) if key in relevant), None)
        details.append({'query': case['query'], 'retrieved_ids': retrieved,
                        'hit': bool(hits) if relevant else None,
                        'recall': len(hits) / len(relevant) if relevant else None,
                        'reciprocal_rank': (1 / first_rank if first_rank else 0) if relevant else None,
                        'no_answer_correct': not retrieved if not relevant else None,
                        'latency_ms': latency_ms, 'mode': result['mode'],
                        'warnings': result['warnings']})
    count = len(details)
    answerable = [item for item in details if item['recall'] is not None]
    unanswerable = [item for item in details if item['no_answer_correct'] is not None]
    return {'cases': count, 'top_k': top_k,
            'hit_at_k': sum(item['hit'] for item in answerable) / len(answerable) if answerable else None,
            'recall_at_k': sum(item['recall'] for item in answerable) / len(answerable) if answerable else None,
            'mrr_at_k': sum(item['reciprocal_rank'] for item in answerable) / len(answerable) if answerable else None,
            'no_answer_accuracy': sum(item['no_answer_correct'] for item in unanswerable) / len(unanswerable) if unanswerable else None,
            'mean_latency_ms': sum(item['latency_ms'] for item in details) / count,
            'details': details}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, help='Research YAML/JSON with knowledge_base and embedding settings')
    parser.add_argument('--cases', required=True, help='Hand-labelled JSONL dataset')
    parser.add_argument('--top-k', type=int, default=8)
    args = parser.parse_args()
    if not 1 <= args.top_k <= 30:
        parser.error('--top-k must be 1–30')
    from dotenv import load_dotenv
    load_dotenv()
    from src.config import Config
    from .runtime import service_for, settings
    config = Config(config_file_path=args.config)
    cases = [json.loads(line) for line in Path(args.cases).read_text(encoding='utf-8').splitlines() if line.strip()]
    result = asyncio.run(evaluate(service_for(config), cases, settings(config)['kb_ids'], args.top_k))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
