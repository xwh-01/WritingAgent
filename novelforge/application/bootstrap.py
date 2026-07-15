"""Composition root for storage-related application services."""

from __future__ import annotations

from dataclasses import dataclass

from novelforge.application.exports import StoryExportService
from novelforge.application.indexing import DerivedIndexService
from novelforge.application.storage import StoryStorageService
from novelforge.core.config import IndexBackendConfig, StorageConfig
from novelforge.indexes.graph_store import NetworkXGraphStore
from novelforge.indexes.interfaces import IFTSStore, IGraphStore, IVectorStore
from novelforge.indexes.text_store import SQLiteFTSStore
from novelforge.indexes.vector_store import ChromaVectorStore, InMemoryVectorStore
from novelforge.storage.artifacts import ArtifactStore
from novelforge.storage.repository import StoryRepository


@dataclass(frozen=True)
class StorageRuntime:
    """Concrete stores and the services that own cross-store behavior."""

    repository: StoryRepository
    artifacts: ArtifactStore
    vector_index: IVectorStore
    graph_index: IGraphStore
    full_text_index: IFTSStore
    indexes: DerivedIndexService
    exports: StoryExportService
    storage: StoryStorageService


def build_storage_runtime(
    config: StorageConfig,
    backends: IndexBackendConfig | None = None,
) -> StorageRuntime:
    """Build one internally consistent set of storage dependencies."""
    backends = backends or IndexBackendConfig()
    repository = StoryRepository(database_path=config.database_path)
    artifacts = ArtifactStore(config.artifact_directory)
    if backends.vector_store == "chroma":
        vector_index = ChromaVectorStore(config.vector_index_directory)
    elif backends.vector_store == "in_memory":
        vector_index = InMemoryVectorStore()
    else:
        raise ValueError(f"Unsupported vector index backend: {backends.vector_store}")
    if backends.graph_store != "networkx":
        raise ValueError(f"Unsupported graph index backend: {backends.graph_store}")
    if backends.text_store != "sqlite_fts":
        raise ValueError(f"Unsupported full-text index backend: {backends.text_store}")
    graph_index = NetworkXGraphStore(config.graph_index_directory)
    full_text_index = SQLiteFTSStore(config.full_text_index_path)
    indexes = DerivedIndexService(
        vector_store=vector_index,
        text_store=full_text_index,
        graph_store=graph_index,
    )
    exports = StoryExportService(artifacts)
    storage = StoryStorageService(
        repository,
        artifacts,
        indexes,
        vector_path=config.vector_index_directory,
        graph_path=config.graph_index_directory,
        full_text_path=config.full_text_index_path,
    )
    return StorageRuntime(
        repository=repository,
        artifacts=artifacts,
        vector_index=vector_index,
        graph_index=graph_index,
        full_text_index=full_text_index,
        indexes=indexes,
        exports=exports,
        storage=storage,
    )
