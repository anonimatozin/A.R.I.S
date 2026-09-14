"""Segurança do A.R.I.S. — utilitários de proteção de fronteira de processo."""

from core.security.shell import (
    ShellInjectionError,
    InputValidationError,
    PathTraversalError,
    CommandNotWhitelistedError,
    validate_shell_input,
    validate_filename,
    validate_process_name,
    validate_url,
    safe_resolve,
)

__all__ = [
    "ShellInjectionError",
    "InputValidationError",
    "PathTraversalError",
    "CommandNotWhitelistedError",
    "validate_shell_input",
    "validate_filename",
    "validate_process_name",
    "validate_url",
    "safe_resolve",
]
