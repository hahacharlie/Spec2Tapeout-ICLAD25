from __future__ import annotations

from pathlib import Path

VALID_SUITES = ("visible", "hidden")


def normalize_suite(suite: str) -> str:
    normalized = suite.strip().lower()
    if normalized not in VALID_SUITES:
        raise ValueError(
            f"Invalid suite '{suite}'. Expected one of: {', '.join(VALID_SUITES)}"
        )
    return normalized


def infer_suite_from_problem_path(problem_path: Path) -> str | None:
    matches = [part for part in problem_path.parts if part in VALID_SUITES]
    if not matches:
        return None

    distinct = set(matches)
    if len(distinct) > 1:
        raise ValueError(
            f"Ambiguous suite in problem path {problem_path}: found {sorted(distinct)}"
        )
    return matches[0]


def resolve_run_suite(
    problem_paths: list[Path],
    explicit_suite: str | None = None,
) -> str:
    normalized_explicit = (
        normalize_suite(explicit_suite) if explicit_suite is not None else None
    )

    inferred_by_path: dict[str, str] = {}
    unscoped_paths: list[str] = []

    for problem_path in problem_paths:
        inferred = infer_suite_from_problem_path(problem_path)
        if inferred is None:
            unscoped_paths.append(str(problem_path))
        else:
            inferred_by_path[str(problem_path)] = inferred

    distinct_inferred = set(inferred_by_path.values())

    if normalized_explicit is not None:
        conflicts = [
            path
            for path, inferred in inferred_by_path.items()
            if inferred != normalized_explicit
        ]
        if conflicts:
            raise ValueError(
                f"Problem paths conflict with --suite {normalized_explicit}: "
                + ", ".join(conflicts)
            )
        return normalized_explicit

    if len(distinct_inferred) > 1:
        raise ValueError(
            "Mixed suites in one run are not allowed: "
            + ", ".join(
                f"{path} -> {suite}"
                for path, suite in sorted(inferred_by_path.items())
            )
        )

    if unscoped_paths:
        raise ValueError(
            "Could not infer suite from problem path(s): "
            + ", ".join(unscoped_paths)
            + ". Pass --suite visible or --suite hidden."
        )

    if not distinct_inferred:
        raise ValueError(
            "No problem suite could be inferred. Pass --suite visible or --suite hidden."
        )

    return next(iter(distinct_inferred))


def default_output_dir_for_suite(suite: str) -> Path:
    return Path("solutions") / normalize_suite(suite)


def default_workspace_dir_for_suite(suite: str) -> Path:
    return Path("solutions") / "workspace" / normalize_suite(suite)
