from __future__ import annotations

from typing import Callable


def run_server(*, run_api_server: Callable[[object, int, object], None], app: object, port: int, logger: object) -> None:
    run_api_server(app, port, logger)


def run_main(
    *,
    build_arg_parser: Callable[[], object],
    run_server_fn: Callable[[int], None],
    run_interactive_fn: Callable[[], None],
    run_person_generation: Callable[..., None],
    person_text_resolver: Callable[[object], str],
    create_client: Callable[[], object],
    validate_input_text: Callable[[object], str | None],
    resolve_targets: Callable[[object, str, bool], list[str]],
    generate_for_person: Callable[..., dict],
) -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    if getattr(args, "serve", False):
        return run_server_fn(getattr(args, "port", 8765))
    if not person_text_resolver(args):
        return run_interactive_fn()
    return run_person_generation(
        person_text=person_text_resolver(args),
        create_client=create_client,
        validate_input_text=validate_input_text,
        resolve_targets=resolve_targets,
        generate_for_person=generate_for_person,
    )
