__all__ = [
    "OntologyBindingService",
    "OntologyCoreferenceService",
    "OntologyGenerationPipeline",
    "OntologyShapeFinalizer",
]


def __getattr__(name: str):
    if name == "OntologyBindingService":
        from .binding import OntologyBindingService

        return OntologyBindingService
    if name == "OntologyCoreferenceService":
        from .coreference import OntologyCoreferenceService

        return OntologyCoreferenceService
    if name == "OntologyGenerationPipeline":
        from .pipeline import OntologyGenerationPipeline

        return OntologyGenerationPipeline
    if name == "OntologyShapeFinalizer":
        from .shape_finalization import OntologyShapeFinalizer

        return OntologyShapeFinalizer
    raise AttributeError(name)
