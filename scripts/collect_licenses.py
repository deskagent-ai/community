#!/usr/bin/env python3
# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Collect all third-party licenses for distribution.

Usage:
    python collect_licenses.py [--output PATH]

This script:
1. Uses pip to get all installed packages and their licenses
2. Fetches license files from package metadata
3. Generates a comprehensive THIRD_PARTY_LICENSES.md file
"""

import subprocess
import sys
import json
import importlib.metadata
from pathlib import Path
from datetime import datetime


# Additional license info for packages where pip-licenses might not find it
MANUAL_LICENSES = {
    "spacy-model-de_core_news_lg": {
        "license": "CC BY-SA 4.0",
        "author": "Explosion AI",
        "url": "https://spacy.io/models/de",
        "notice": "This model is licensed under CC BY-SA 4.0. Attribution required."
    },
    "spacy-model-en_core_web_lg": {
        "license": "CC BY-SA 4.0",
        "author": "Explosion AI",
        "url": "https://spacy.io/models/en",
        "notice": "This model is licensed under CC BY-SA 4.0. Attribution required."
    },
    "python-embedded": {
        "license": "PSF License",
        "author": "Python Software Foundation",
        "url": "https://www.python.org/",
        "notice": "Python is licensed under the PSF License Agreement."
    },
    "portable-git": {
        "license": "GPL-2.0",
        "author": "Git Contributors",
        "url": "https://git-scm.com/",
        "notice": "Git is licensed under GPL-2.0. Source available at https://github.com/git/git"
    }
}


def get_package_license_text(package_name: str) -> str | None:
    """Try to get the full license text for a package."""
    try:
        dist = importlib.metadata.distribution(package_name)

        # Try to find LICENSE file in package metadata
        if dist.files:
            for file in dist.files:
                name_lower = file.name.lower()
                if 'license' in name_lower or 'copying' in name_lower:
                    try:
                        return file.read_text()
                    except Exception:
                        pass

        # Try metadata license field
        license_text = dist.metadata.get('License')
        if license_text and len(license_text) > 50:  # Likely full text, not just name
            return license_text

    except Exception:
        pass

    return None


def get_installed_packages() -> list[dict]:
    """Get all installed packages with their license info."""
    packages = []

    for dist in importlib.metadata.distributions():
        meta = dist.metadata
        name = meta['Name']
        version = meta['Version']

        # Get license info
        license_name = meta.get('License', 'Unknown')

        # Sometimes license is in classifiers
        if license_name in ('UNKNOWN', 'Unknown', ''):
            classifiers = meta.get_all('Classifier') or []
            for c in classifiers:
                if c.startswith('License :: OSI Approved ::'):
                    license_name = c.split('::')[-1].strip()
                    break

        # Get author info
        author = meta.get('Author', meta.get('Author-email', 'Unknown'))

        # Get homepage
        homepage = meta.get('Home-page', meta.get('Project-URL', ''))
        if isinstance(homepage, str) and ', ' in homepage:
            homepage = homepage.split(', ')[-1]

        # Get full license text
        license_text = get_package_license_text(name)

        packages.append({
            'name': name,
            'version': version,
            'license': license_name,
            'author': author,
            'homepage': homepage,
            'license_text': license_text
        })

    # Sort by name
    packages.sort(key=lambda x: x['name'].lower())

    return packages


def generate_markdown(packages: list[dict], output_path: Path) -> None:
    """Generate the THIRD_PARTY_LICENSES.md file."""

    lines = [
        "# Third-Party Licenses",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "This file contains the licenses for all third-party software used in DeskAgent.",
        "",
        "---",
        "",
        "## Summary",
        "",
        "| Package | Version | License |",
        "|---------|---------|---------|",
    ]

    # Summary table
    for pkg in packages:
        license_short = pkg['license'][:50] + '...' if len(pkg['license']) > 50 else pkg['license']
        lines.append(f"| {pkg['name']} | {pkg['version']} | {license_short} |")

    # Add manual entries to summary
    for name, info in MANUAL_LICENSES.items():
        lines.append(f"| {name} | - | {info['license']} |")

    lines.extend([
        "",
        "---",
        "",
        "## Full License Texts",
        "",
    ])

    # Full license texts
    for pkg in packages:
        lines.extend([
            f"### {pkg['name']} {pkg['version']}",
            "",
            f"- **License:** {pkg['license']}",
            f"- **Author:** {pkg['author']}",
        ])

        if pkg['homepage']:
            lines.append(f"- **Homepage:** {pkg['homepage']}")

        lines.append("")

        if pkg['license_text']:
            lines.extend([
                "```",
                pkg['license_text'].strip(),
                "```",
            ])
        else:
            lines.append("*License text not available in package metadata.*")

        lines.extend(["", "---", ""])

    # Manual entries (spaCy models, Python, Git)
    lines.extend([
        "## Additional Components",
        "",
    ])

    for name, info in MANUAL_LICENSES.items():
        lines.extend([
            f"### {name}",
            "",
            f"- **License:** {info['license']}",
            f"- **Author:** {info['author']}",
            f"- **URL:** {info['url']}",
            "",
            info['notice'],
            "",
            "---",
            "",
        ])

    # Write file
    output_path.write_text('\n'.join(lines), encoding='utf-8')
    print(f"Generated: {output_path}")
    print(f"Total packages: {len(packages) + len(MANUAL_LICENSES)}")


def generate_plain_text(packages: list[dict], output_path: Path) -> None:
    """Generate a plain text version for embedding in the app."""

    lines = [
        "=" * 78,
        "THIRD-PARTY SOFTWARE LICENSES",
        "=" * 78,
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d')}",
        "",
        "DeskAgent uses the following open-source software:",
        "",
    ]

    for pkg in packages:
        lines.extend([
            "-" * 78,
            f"{pkg['name']} {pkg['version']}",
            f"License: {pkg['license']}",
            f"Author: {pkg['author']}",
            "-" * 78,
        ])

        if pkg['license_text']:
            lines.extend([
                "",
                pkg['license_text'].strip(),
                "",
            ])
        else:
            lines.append("")

    # Manual entries
    lines.extend([
        "=" * 78,
        "ADDITIONAL COMPONENTS",
        "=" * 78,
        "",
    ])

    for name, info in MANUAL_LICENSES.items():
        lines.extend([
            "-" * 78,
            name,
            f"License: {info['license']}",
            f"Author: {info['author']}",
            f"URL: {info['url']}",
            "-" * 78,
            "",
            info['notice'],
            "",
        ])

    output_path.write_text('\n'.join(lines), encoding='utf-8')
    print(f"Generated: {output_path}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Collect third-party licenses')
    parser.add_argument('--output', '-o', type=Path,
                        default=Path(__file__).parent.parent.parent / 'THIRD_PARTY_LICENSES.md',
                        help='Output file path')
    parser.add_argument('--format', '-f', choices=['markdown', 'text', 'both'],
                        default='both', help='Output format')

    args = parser.parse_args()

    print("Collecting package information...")
    packages = get_installed_packages()

    if args.format in ('markdown', 'both'):
        md_path = args.output if args.output.suffix == '.md' else args.output.with_suffix('.md')
        generate_markdown(packages, md_path)

    if args.format in ('text', 'both'):
        txt_path = args.output.with_suffix('.txt')
        generate_plain_text(packages, txt_path)

    print("\nDone!")
    print("\nRemember to review the output and add any missing license texts manually.")


if __name__ == '__main__':
    main()
