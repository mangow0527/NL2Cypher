from __future__ import annotations

from .ontology_path_selection import (
    CandidatePath,
    OntologyPathSelectionService,
    OntologyPathSelectionTrace,
    OntologyPathSelectionValidationError,
    PathEvidence,
    PathRequest,
    SelectedPath,
    build_candidate_paths,
    build_path_requests,
    validate_path_selection,
)

PathFillingValidationError = OntologyPathSelectionValidationError
PathFillingTrace = OntologyPathSelectionTrace
OntologyPathFillingService = OntologyPathSelectionService

