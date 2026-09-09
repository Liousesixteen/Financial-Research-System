"""SQLite is authoritative; vectors are replaceable derived data.

Each operation owns its SQLite connection. A ready document is published only
once every chunk and keyword index entry has committed. No model keys persisted.
"""
import asyncio
import hashlib
import json
import math
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path

from .parsers import PARSER_VERSION, SUPPORTED, NeedsOCR, chunk_blocks, extract


def now():
    return datetime.now(timezone.utc).isoformat()


def tokens(text):
    # CJK bi-grams make the no-extra-dependency path usable as well as Latin terms.
    words = re.findall(r'[a-z0-9]+', text.lower())
    for run in re.findall(r'[\u3400-\u9fff]+', text):
        words.extend(run[i:i + 2] for i in range(max(1, len(run) - 1)))
    try:
        import jieba
        words.extend(w.lower() for w in jieba.cut(text) if len(w.strip()) > 1)
    except ImportError:
        pass
    return list(dict.fromkeys(words))


def normalize(vector):
    result = [float(v) for v in vector]
    norm = math.sqrt(sum(v * v for v in result))
    if not result or not math.isfinite(norm) or norm == 0:
        raise ValueError('Invalid embedding vector')
    return [v / norm for v in result]


class KnowledgeBaseService:
    def __init__(self, root='data/knowledge', embedding=None, model_id='', backend='local',
                 qdrant_url='http://localhost:6333'):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / 'originals').mkdir(exist_ok=True)
        self.embedding = embedding
        self.model_id = model_id
        self.backend = backend
        self.qdrant_url = qdrant_url
        if backend not in ('local', 'qdrant'):
            raise ValueError('vector backend must be local or qdrant')
        with self.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS libraries(id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT);
            CREATE TABLE IF NOT EXISTS documents(
                id TEXT PRIMARY KEY, kb_id TEXT NOT NULL REFERENCES libraries(id), title TEXT,
                filename TEXT, hash TEXT, metadata TEXT, status TEXT, error TEXT DEFAULT '',
                created_at TEXT, parser_version TEXT, UNIQUE(kb_id, hash, metadata, parser_version));
            CREATE TABLE IF NOT EXISTS chunks(
                id TEXT PRIMARY KEY, doc_id TEXT REFERENCES documents(id), text TEXT,
                locator TEXT, page INTEGER, kind TEXT);
            CREATE INDEX IF NOT EXISTS chunks_doc ON chunks(doc_id);
            CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(chunk_id UNINDEXED, terms);
            CREATE TABLE IF NOT EXISTS embeddings(
                hash TEXT, model TEXT, vector TEXT, PRIMARY KEY(hash, model));
            CREATE TABLE IF NOT EXISTS jobs(
                id TEXT PRIMARY KEY, doc_id TEXT, status TEXT, error TEXT DEFAULT '', updated_at TEXT);
            ''')

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.root / 'knowledge.sqlite3', timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA journal_mode=WAL')
        try:
            with db:
                yield db
        finally:
            db.close()

    def libraries(self):
        with self.db() as db:
            return [dict(r) for r in db.execute('SELECT * FROM libraries ORDER BY created_at')]

    def create_library(self, name):
        if not name.strip() or len(name) > 100:
            raise ValueError('Library name must contain 1–100 characters')
        library = {'id': uuid.uuid4().hex, 'name': name.strip(), 'created_at': now()}
        with self.db() as db:
            db.execute('INSERT INTO libraries VALUES (:id,:name,:created_at)', library)
        return library

    def rename_library(self, library_id, name):
        if not name.strip() or len(name) > 100:
            raise ValueError('Library name must contain 1–100 characters')
        with self.db() as db:
            if not db.execute('UPDATE libraries SET name=? WHERE id=?', (name.strip(), library_id)).rowcount:
                raise KeyError(library_id)

    def documents(self, kb_id):
        with self.db() as db:
            rows = db.execute("SELECT * FROM documents WHERE kb_id=? AND status!='deleted' ORDER BY created_at DESC", (kb_id,))
            return [self._document(r) for r in rows]

    @staticmethod
    def _document(row):
        result = dict(row)
        result['metadata'] = json.loads(result['metadata'])
        return result

    def document(self, doc_id):
        with self.db() as db:
            row = db.execute("SELECT * FROM documents WHERE id=? AND status!='deleted'", (doc_id,)).fetchone()
            if not row:
                raise KeyError(doc_id)
            return self._document(row)

    def original_path(self, doc_id):
        doc = self.document(doc_id)
        return self.root / 'originals' / (doc['id'] + Path(doc['filename']).suffix.lower())

    def enqueue(self, kb_id, filename, content, metadata=None):
        suffix = Path(filename).suffix.lower()
        if suffix not in SUPPORTED:
            raise ValueError('Supported formats: PDF, DOCX, Markdown, TXT')
        if not content or len(content) > 50 * 1024 * 1024:
            raise ValueError('File must be nonempty and no larger than 50 MB')
        metadata = dict(metadata or {})
        allowed = {'company', 'ticker', 'market', 'industry', 'published_at', 'report_period', 'source_url', 'source_type'}
        if set(metadata) - allowed:
            raise ValueError('Unknown metadata fields')
        for key, value in metadata.items():
            if not isinstance(value, str) or len(value) > 1000:
                raise ValueError('Metadata must contain short text values')
        if metadata.get('published_at'):
            date.fromisoformat(metadata['published_at'])
        if metadata.get('source_url') and not metadata['source_url'].startswith(('http://', 'https://')):
            raise ValueError('Source URL must use HTTP or HTTPS')
        encoded = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
        digest = hashlib.sha256(content).hexdigest()
        doc_id, job_id = uuid.uuid4().hex, uuid.uuid4().hex
        with self.db() as db:
            if not db.execute('SELECT 1 FROM libraries WHERE id=?', (kb_id,)).fetchone():
                raise KeyError(kb_id)
            old = db.execute('SELECT id,status FROM documents WHERE kb_id=? AND hash=? AND metadata=? AND parser_version=?',
                             (kb_id, digest, encoded, PARSER_VERSION)).fetchone()
            if old and old['status'] != 'deleted':
                return {'doc_id': old['id'], 'job_id': None, 'duplicate': True}
            if old:
                # Re-importing deleted content creates a new immutable version.
                db.execute('UPDATE documents SET parser_version=? WHERE id=?', ('deleted-' + old['id'], old['id']))
            path = self.root / 'originals' / (doc_id + suffix)
            path.write_bytes(content)
            db.execute('INSERT INTO documents(id,kb_id,title,filename,hash,metadata,status,created_at,parser_version) VALUES(?,?,?,?,?,?,?,?,?)',
                       (doc_id, kb_id, Path(filename).stem, Path(filename).name, digest, encoded, 'queued', now(), PARSER_VERSION))
            db.execute('INSERT INTO jobs(id,doc_id,status,updated_at) VALUES(?,?,?,?)', (job_id, doc_id, 'queued', now()))
        return {'doc_id': doc_id, 'job_id': job_id, 'duplicate': False}

    def retry(self, doc_id):
        self.document(doc_id)
        with self.db() as db:
            active = db.execute("SELECT id FROM jobs WHERE doc_id=? AND status IN ('queued','parsing','indexing')", (doc_id,)).fetchone()
            if active:
                return active['id']
            job_id = uuid.uuid4().hex
            db.execute('INSERT INTO jobs(id,doc_id,status,updated_at) VALUES(?,?,?,?)', (job_id, doc_id, 'queued', now()))
            db.execute("UPDATE documents SET status='queued',error='' WHERE id=?", (doc_id,))
            return job_id

    def job(self, job_id):
        with self.db() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
            if not row:
                raise KeyError(job_id)
            return dict(row)

    def recover_jobs(self):
        # Called once on single-worker application startup, never on each request.
        with self.db() as db:
            rows = db.execute("SELECT id FROM jobs WHERE status IN ('queued','parsing','indexing')").fetchall()
            db.execute("UPDATE jobs SET status='queued' WHERE status IN ('parsing','indexing')")
            return [r['id'] for r in rows]

    def _status(self, job_id, status, error=''):
        with self.db() as db:
            db.execute('UPDATE jobs SET status=?,error=?,updated_at=? WHERE id=?', (status, error, now(), job_id))
            db.execute("UPDATE documents SET status=?,error=? WHERE id=(SELECT doc_id FROM jobs WHERE id=?) AND status!='deleted'",
                       (status, error, job_id))

    async def process(self, job_id):
        job = self.job(job_id)
        if job['status'] not in ('queued',):
            return
        with self.db() as db:
            if not db.execute("UPDATE jobs SET status='parsing' WHERE id=? AND status='queued'", (job_id,)).rowcount:
                return
        try:
            self._status(job_id, 'parsing')
            doc = self.document(job['doc_id'])
            blocks = await asyncio.to_thread(extract, self.original_path(doc['id']))
            pieces = list(chunk_blocks(blocks))
            if not pieces:
                raise ValueError('Document contains no readable text')
            self._status(job_id, 'indexing')
            chunks = [{**p, 'id': uuid.uuid5(uuid.NAMESPACE_URL, f"{doc['id']}:{i}:{PARSER_VERSION}").hex,
                       'doc_id': doc['id']} for i, p in enumerate(pieces)]
            # Vectors can be built later with the configured model; lexical availability is explicit.
            if self.embedding:
                vectors = await self._embed([p['text'] for p in chunks])
                if self.backend == 'qdrant':
                    await asyncio.to_thread(self._qdrant_upsert, chunks, vectors)
            with self.db() as db:
                current = db.execute('SELECT status FROM documents WHERE id=?', (doc['id'],)).fetchone()
                if current['status'] == 'deleted':
                    db.execute("UPDATE jobs SET status='cancelled' WHERE id=?", (job_id,))
                    return
                db.execute('DELETE FROM chunk_fts WHERE chunk_id IN (SELECT id FROM chunks WHERE doc_id=?)', (doc['id'],))
                db.execute('DELETE FROM chunks WHERE doc_id=?', (doc['id'],))
                for p in chunks:
                    db.execute('INSERT INTO chunks VALUES(?,?,?,?,?,?)',
                               (p['id'], doc['id'], p['text'], p['locator'], p['page'], p['kind']))
                    db.execute('INSERT INTO chunk_fts(chunk_id,terms) VALUES(?,?)', (p['id'], ' '.join(tokens(p['text']))))
                db.execute("UPDATE documents SET status='ready',error='' WHERE id=?", (doc['id'],))
                db.execute("UPDATE jobs SET status='ready',error='',updated_at=? WHERE id=?", (now(), job_id))
        except Exception as exc:
            self._status(job_id, 'needs_ocr' if isinstance(exc, NeedsOCR) else 'failed', f'{type(exc).__name__}: {exc}'[:1000])

    def delete_document(self, doc_id):
        self.document(doc_id)
        with self.db() as db:
            db.execute("UPDATE documents SET status='deleted' WHERE id=?", (doc_id,))
            db.execute("UPDATE jobs SET status='cancelled' WHERE doc_id=?", (doc_id,))
            db.execute('DELETE FROM chunk_fts WHERE chunk_id IN (SELECT id FROM chunks WHERE doc_id=?)', (doc_id,))
            db.execute('DELETE FROM chunks WHERE doc_id=?', (doc_id,))
        # Retain original for audit; live retrieval always checks authoritative status.
        # Vector points are unreachable and can be removed by rebuilding the collection.

    def corpus(self, kb_ids, filters=None):
        if not kb_ids:
            return []
        filters = filters or {}
        if filters.get('as_of'):
            date.fromisoformat(filters['as_of'])
        with self.db() as db:
            placeholders = ','.join('?' for _ in kb_ids)
            rows = db.execute(f'''SELECT c.*,d.title,d.kb_id,d.metadata,d.hash AS version
                FROM chunks c JOIN documents d ON d.id=c.doc_id
                WHERE d.status='ready' AND d.kb_id IN ({placeholders})''', kb_ids).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            meta = json.loads(item.pop('metadata'))
            if any(filters.get(k) and filters[k] != meta.get(k) for k in ('company', 'ticker', 'market', 'industry', 'report_period')):
                continue
            if filters.get('as_of') and (not meta.get('published_at') or meta['published_at'] > filters['as_of']):
                continue
            if meta.get('source_type') == 'ai_generated' and not filters.get('include_generated', False):
                continue
            result.append({**item, 'metadata': meta})
        return result

    async def _embed(self, texts):
        if not self.model_id:
            raise ValueError('Embedding model identity is required')
        output = []
        for start in range(0, len(texts), 32):
            batch = texts[start:start + 32]
            hashes = [hashlib.sha256(t.encode()).hexdigest() for t in batch]
            with self.db() as db:
                cached = [db.execute('SELECT vector FROM embeddings WHERE hash=? AND model=?', (h, self.model_id)).fetchone() for h in hashes]
            missing = [i for i, row in enumerate(cached) if row is None]
            if missing:
                vectors = await self.embedding.generate_embeddings([batch[i] for i in missing])
                if len(vectors) != len(missing):
                    raise ValueError('Embedding batch size mismatch')
                with self.db() as db:
                    for index, vector in zip(missing, vectors):
                        value = json.dumps(normalize(vector))
                        db.execute('INSERT OR REPLACE INTO embeddings VALUES(?,?,?)', (hashes[index], self.model_id, value))
                        cached[index] = {'vector': value}
            output.extend(json.loads(row['vector']) for row in cached)
        if len({len(v) for v in output}) > 1:
            raise ValueError('Embedding dimension changed: configure a new model identity and reindex')
        return output

    def _qdrant(self, dimension):
        from qdrant_client import QdrantClient, models
        client = QdrantClient(url=self.qdrant_url, timeout=20)
        name = 'frs_' + hashlib.sha256(f'{self.model_id}:{dimension}:{PARSER_VERSION}'.encode()).hexdigest()[:20]
        if not client.collection_exists(name):
            client.create_collection(name, vectors_config=models.VectorParams(size=dimension, distance=models.Distance.COSINE))
        return client, name

    def _qdrant_upsert(self, chunks, vectors):
        from qdrant_client import models
        client, name = self._qdrant(len(vectors[0]))
        try:
            for start in range(0, len(chunks), 128):
                client.upsert(name, points=[models.PointStruct(id=c['id'], vector=v, payload={'doc_id': c['doc_id']})
                              for c, v in zip(chunks[start:start + 128], vectors[start:start + 128])], wait=True)
        finally:
            client.close()

    async def search(self, query, kb_ids=None, filters=None, top_k=8, snapshot=None):
        if not query.strip() or not 1 <= top_k <= 30:
            raise ValueError('Query is required; top_k must be 1–30')
        rows = snapshot if snapshot is not None else self.corpus(kb_ids or [], filters)
        if not rows:
            return {'results': [], 'mode': 'keyword', 'warnings': ['No eligible evidence']}
        # Use an ephemeral FTS index for snapshots so deleted/revised live data cannot alter resumed research.
        terms = tokens(query)[:80]
        lexical = []
        if terms:
            with sqlite3.connect(':memory:') as db:
                db.execute('CREATE VIRTUAL TABLE search USING fts5(id UNINDEXED, terms)')
                db.executemany('INSERT INTO search VALUES(?,?)', [(r['id'], ' '.join(tokens(r['text'] + ' ' + r['title']))) for r in rows])
                expression = ' OR '.join('"' + t.replace('"', '""') + '"' for t in terms)
                lexical = [r[0] for r in db.execute('SELECT id FROM search WHERE search MATCH ? ORDER BY bm25(search) LIMIT 20', (expression,))]
        dense, warnings = [], []
        if self.embedding:
            try:
                vectors = await self._embed([r['text'] for r in rows])
                query_vector = (await self._embed([query]))[0]
                if len(query_vector) != len(vectors[0]):
                    raise ValueError('Embedding dimensions differ')
                if self.backend == 'qdrant' and snapshot is None:
                    await asyncio.to_thread(self._qdrant_upsert, rows, vectors)
                    def remote_search():
                        from qdrant_client import models
                        client, name = self._qdrant(len(query_vector))
                        try:
                            result = client.query_points(name, query=query_vector,
                                query_filter=models.Filter(must=[models.HasIdCondition(has_id=[r['id'] for r in rows])]), limit=20)
                            return [str(p.id).replace('-', '') for p in result.points if p.score > 0.15]
                        finally:
                            client.close()
                    dense = await asyncio.to_thread(remote_search)
                else:
                    scores = [(r['id'], sum(a * b for a, b in zip(vector, query_vector))) for r, vector in zip(rows, vectors)]
                    dense = [key for key, score in sorted(scores, key=lambda p: p[1], reverse=True)[:20] if score > 0.15]
            except Exception as exc:
                warnings.append(f'Semantic search unavailable; keyword fallback ({type(exc).__name__})')
        else:
            warnings.append('Embedding not configured; keyword search only')
        rank = {}
        for ranking in (lexical, dense):
            for index, key in enumerate(ranking):
                rank[key] = rank.get(key, 0) + 1 / (61 + index)
        by_id = {r['id']: r for r in rows}
        results, per_doc = [], {}
        # Check deletion once more after potentially slow model/service calls.
        live_ids = None if snapshot is not None else {r['id'] for r in self.corpus(kb_ids or [], filters)}
        for key in sorted(rank, key=rank.get, reverse=True):
            if key not in by_id or (live_ids is not None and key not in live_ids):
                continue
            row = by_id[key]
            if per_doc.get(row['doc_id'], 0) >= max(3, top_k // 2):
                continue
            per_doc[row['doc_id']] = per_doc.get(row['doc_id'], 0) + 1
            results.append({**row, 'evidence_id': key, 'score': rank[key]})
            if len(results) == top_k:
                break
        return {'results': results, 'mode': 'hybrid' if dense else 'keyword', 'warnings': warnings}
