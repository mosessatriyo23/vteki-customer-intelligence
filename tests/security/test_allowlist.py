"""Check controllable project dependencies and imports, not global installations."""

import ast
import configparser
import re
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    try:
        import tomli as tomllib
    except ModuleNotFoundError:
        tomllib = None

ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIRS = ("services", "api", "worker", "generator", "migrations")
PROHIBITED_DISTRIBUTIONS = {
    "smtplib", "twilio", "sendgrid", "mailgun", "boto3", "telebot",
    "python-telegram-bot", "slack-sdk",
}
PROHIBITED_MODULES = {
    "smtplib", "twilio", "sendgrid", "mailgun", "boto3", "telebot",
    "telegram", "slack_sdk",
}


def distribution_name(requirement):
    match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9_.-]*)", requirement)
    return re.sub(r"[-_.]+", "-", match.group(1)).lower() if match else None


def prohibited_requirements(requirements, location):
    return [f"{location}: {requirement}" for requirement in requirements
            if distribution_name(requirement) in PROHIBITED_DISTRIBUTIONS]


def _project_files(pattern):
    for path in ROOT.rglob(pattern):
        if not any(part in {".git", ".venv", "venv", "node_modules"} for part in path.parts):
            yield path


def test_no_prohibited_dependencies_declared():
    """Inspect dependency declarations owned by this repository."""
    violations = []
    for path in _project_files("requirements*.txt"):
        lines = path.read_text(encoding="utf-8").splitlines()
        violations.extend(prohibited_requirements(
            (line for line in lines if line.strip() and not line.lstrip().startswith(("#", "-"))),
            path.relative_to(ROOT),
        ))
    for path in _project_files("pyproject.toml"):
        if tomllib is None:
            violations.append(f"{path.relative_to(ROOT)}: requires tomllib/tomli for review")
            continue
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        project = data.get("project", {})
        requirements = list(project.get("dependencies", []))
        requirements += [item for group in project.get("optional-dependencies", {}).values() for item in group]
        requirements += data.get("build-system", {}).get("requires", [])
        for group in data.get("dependency-groups", {}).values():
            requirements += [item for item in group if isinstance(item, str)]
        violations.extend(prohibited_requirements(requirements, path.relative_to(ROOT)))
        for tool in ("poetry", "pdm"):
            section = data.get("tool", {}).get(tool, {})
            for key in ("dependencies", "dev-dependencies"):
                violations.extend(prohibited_requirements(section.get(key, {}), path.relative_to(ROOT)))
            for group in section.get("group", {}).values():
                violations.extend(prohibited_requirements(group.get("dependencies", {}), path.relative_to(ROOT)))
    for path in _project_files("setup.cfg"):
        config = configparser.ConfigParser()
        config.read(path, encoding="utf-8")
        for section in config.sections():
            if section in ("options", "options.extras_require"):
                for key, value in config[section].items():
                    if section == "options" and key not in {"install_requires", "setup_requires", "tests_require"}:
                        continue
                    violations.extend(prohibited_requirements(value.splitlines(), path.relative_to(ROOT)))
    assert not violations, "[NFR-10 / T-SEC-03] Forbidden project dependencies:\n" + "\n".join(violations)


def test_no_prohibited_imports_in_source_code():
    """Parse actual application imports (ignore comments and host environment)."""
    violations = []
    for directory in SOURCE_DIRS:
        for path in (ROOT / directory).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules = (alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    modules = (node.module or "",)
                else:
                    continue
                for module in modules:
                    if module.split(".")[0] in PROHIBITED_MODULES:
                        violations.append(f"{path.relative_to(ROOT)}:{node.lineno}: {module}")
    assert not violations, "[NFR-10 / T-SEC-03] Forbidden source imports:\n" + "\n".join(violations)
