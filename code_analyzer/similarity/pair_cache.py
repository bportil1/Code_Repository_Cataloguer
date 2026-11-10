"""Disposable project-local cache of *exhaustive* rooted-neighborhood comparisons.

A cache row is a measurement, not scientific input.  Both the canonical function
nodes and all directed call edges participate in its graph fingerprint.  Every
cache key also names the similarity settings and implementation revision.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import sqlite3

from .engine import FunctionGraph, SimilarityConfig, compare_functions

SCHEMA_VERSION = 1
ALGORITHM_VERSION = 'rooted-neighborhood-v1'
CACHE_RELATIVE_PATH = Path('.codebase_catalog') / 'similarity_pairs.sqlite3'


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':'), allow_nan=False)


def _digest(value: object) -> str:
    return hashlib.sha256(_json(value).encode('utf-8')).hexdigest()


def graph_fingerprint(graph: FunctionGraph) -> str:
    """Include descriptors, names, directed edges, external flags and multiplicity."""
    nodes = [(key, asdict(graph.nodes[key])) for key in sorted(graph.nodes)]
    edges = sorted(
        (edge.source, edge.target, edge.is_external)
        for outgoing in graph.outgoing.values()
        for edge in outgoing
    )
    return _digest([ALGORITHM_VERSION, nodes, edges])


def _canonical(left: str, right: str) -> tuple[str, str]:
    return (left, right) if left <= right else (right, left)


def _checksum(graph_hash: str, config_hash: str, left: str, right: str,
              score: float, root_similarity: float) -> str:
    return _digest([graph_hash, config_hash, left, right, score, root_similarity])


class PairwiseScoreCache:
    """One connection per analysis operation; rows commit transactionally.

    A cache failure never licenses approximate comparison: the original engine
    computes any missing, malformed, or unverifiable measurement.
    """

    def __init__(self, project_root: str | Path, graph: FunctionGraph,
                 config: SimilarityConfig) -> None:
        config.validate()
        self.root = Path(project_root).expanduser().resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError('Project root must be a directory')
        self.path = self.root / CACHE_RELATIVE_PATH
        self.graph = graph
        self.config = config
        self.graph_hash = graph_fingerprint(graph)
        self.config_hash = _digest([ALGORITHM_VERSION, asdict(config)])
        self.hits = 0
        self.misses = 0
        self._db: sqlite3.Connection | None = None
        self._open()

    def _open(self) -> None:
        if self.path.parent.is_symlink() or self.path.is_symlink():
            raise ValueError('Similarity cache must not be a symbolic link')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._init_database()
        except sqlite3.DatabaseError:
            # Cache files are disposable; never touch the authoritative catalog.
            if self._db is not None:
                self._db.close()
                self._db = None
            if self.path.is_symlink():
                raise ValueError('Similarity cache must not be a symbolic link')
            self.path.unlink(missing_ok=True)
            self._init_database()

    def _init_database(self) -> None:
        db = sqlite3.connect(str(self.path), timeout=10)
        try:
            db.execute('PRAGMA journal_mode=DELETE')
            db.execute('CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            db.execute('''CREATE TABLE IF NOT EXISTS pair_scores (
                graph_hash TEXT NOT NULL, config_hash TEXT NOT NULL,
                left_id TEXT NOT NULL, right_id TEXT NOT NULL,
                score REAL NOT NULL, root_similarity REAL NOT NULL,
                checksum TEXT NOT NULL,
                PRIMARY KEY(graph_hash, config_hash, left_id, right_id)
            )''')
            values = dict(db.execute('SELECT key, value FROM meta').fetchall())
            if values and (values.get('schema_version') != str(SCHEMA_VERSION)
                           or values.get('project_root') != str(self.root)):
                db.execute('DELETE FROM pair_scores')
                db.execute('DELETE FROM meta')
            db.executemany('INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)', [
                ('schema_version', str(SCHEMA_VERSION)),
                ('project_root', str(self.root)),
            ])
            # Changed graph invalidates every previous function-pair measurement.
            db.execute('DELETE FROM pair_scores WHERE graph_hash <> ?', (self.graph_hash,))
            db.commit()
            self._db = db
        except Exception:
            db.close()
            raise

    def score(self, left: str, right: str) -> tuple[float, float]:
        if left not in self.graph.nodes or right not in self.graph.nodes:
            raise KeyError('Unknown function identifier')
        left, right = _canonical(left, right)
        if left == right:
            return (1.0, 1.0)
        db = self._db
        if db is not None:
            try:
                row = db.execute('''SELECT score, root_similarity, checksum FROM pair_scores
                    WHERE graph_hash=? AND config_hash=? AND left_id=? AND right_id=?''',
                    (self.graph_hash, self.config_hash, left, right)).fetchone()
                if row:
                    score, root_similarity, checksum = row
                    if (all(isinstance(item, (int, float)) and math.isfinite(item)
                            and -1e-9 <= item <= 1 + 1e-9
                            for item in (score, root_similarity))
                            and checksum == _checksum(self.graph_hash, self.config_hash,
                                                      left, right, score, root_similarity)):
                        self.hits += 1
                        return (float(score), float(root_similarity))
            except sqlite3.DatabaseError:
                # The scientific engine remains available even if cache I/O fails.
                try:
                    db.close()
                finally:
                    db = None
                    self._db = None
        self.misses += 1
        result = compare_functions(self.graph, left, right, self.config, include_pairs=False)
        score = float(result.score)
        root_similarity = float(result.layers[0].node_similarity)
        if db is not None:
            try:
                db.execute('''INSERT OR REPLACE INTO pair_scores
                    (graph_hash, config_hash, left_id, right_id, score, root_similarity, checksum)
                    VALUES(?,?,?,?,?,?,?)''',
                    (self.graph_hash, self.config_hash, left, right, score,
                     root_similarity, _checksum(self.graph_hash, self.config_hash,
                                                left, right, score, root_similarity)))
            except sqlite3.DatabaseError:
                try:
                    db.close()
                finally:
                    self._db = None
        return score, root_similarity

    def close(self) -> None:
        if self._db is not None:
            try:
                self._db.commit()
            finally:
                self._db.close()
                self._db = None

    def __enter__(self) -> PairwiseScoreCache:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
