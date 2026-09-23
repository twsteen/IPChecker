#!/usr/bin/env python3
"""
VHDL Entity Usage Analyzer

Features:
 - Recursive VHDL search
 - Entity detection
 - Component detection
 - Instantiation detection
 - Hierarchy generation
 - CSV export
 - Graphviz export
 - Unused entity detection

Usage:

python vhdl_usage_analyzer.py c:/fpga c:/common_ip --csv --dot --hierarchy

"""

import re
import csv
import argparse

from pathlib import Path
from collections import defaultdict


OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

##############################################################################
# REGEX DEFINITIONS
##############################################################################

ENTITY_RE = re.compile(
    r'\bentity\s+(\w+)\s+is\b',
    re.IGNORECASE
)

COMPONENT_RE = re.compile(
    r'\bcomponent\s+(\w+)\b',
    re.IGNORECASE
)

COMPONENT_INSTANCE_RE = re.compile(
    r'(\w+)\s*:\s*(?:component\s+)?(\w+)\s*(?:generic\s+map\s*\(.*?\)\s*)?\s*port\s+map',
    re.IGNORECASE | re.DOTALL
)

DIRECT_ENTITY_RE = re.compile(
    r'(\w+)\s*:\s*entity\s+(?:\w+\.)?(\w+)',
    re.IGNORECASE
)

SIMPLE_INSTANCE_RE = re.compile(
    r'(\w+)\s*:\s*(\w+)'
)

COMMENT_RE = re.compile(r'--.*?$',
                        re.MULTILINE)


##############################################################################
# DATA CLASSES
##############################################################################

class EntityInfo:

    def __init__(self, name, file, line):
        self.name = name.lower()
        self.file = file
        self.line = line


class InstanceInfo:

    def __init__(self,
                 entity_name,
                 instance_name,
                 file,
                 line):

        self.entity_name = entity_name.lower()
        self.instance_name = instance_name
        self.file = file
        self.line = line


##############################################################################
# HELPERS
##############################################################################

def strip_comments(text):
    return COMMENT_RE.sub('', text)


def find_line_number(text, position):
    return text.count('\n', 0, position) + 1


def load_vhdl_files(vhdl_files):

    file_contents = {}

    for file in vhdl_files:

        try:

            text = file.read_text(
                encoding="utf-8",
                errors="ignore"
            )

            file_contents[file] = strip_comments(text)

        except Exception as ex:

            print(
                f"ERROR reading {file}: {ex}"
            )

    return file_contents

##############################################################################
# STEP 1 - FIND FILES
##############################################################################

def is_excluded(file):

    excluded_dirs = {
        "sim_only"
    }

    return any(
        part.lower() in excluded_dirs
        for part in file.parts
    )


def find_vhdl_files(search_dirs):

    files = set()

    extra_file = Path(
        r"H:\ddm\hecb_odf\qsys\hecb_nios\generated\syn\synthesis\hecb_nios.vhd"
    )

    if extra_file.exists():
        files.add(extra_file)
    else:
        print(f"Error: Extra file does not exists {extra_file}")

    for directory in search_dirs:

        root = Path(directory)

        if not root.exists():
            print(f"WARNING: missing directory {root}")
            continue

        for file in root.rglob("*.vhd"):

            if not is_excluded(file):
                files.add(file)

    print(f"Found {len(files)} VHDL files")

    return sorted(files)


##############################################################################
# STEP 2 - PARSE ENTITIES
##############################################################################

def parse_entities(file_contents):

    entities = {}

    for file, text in file_contents.items():

        for match in ENTITY_RE.finditer(text):

            entity_name = match.group(1).lower()
            line = find_line_number(
                text,
                match.start()
            )

            entities[entity_name] = EntityInfo(
                entity_name,
                file,
                line
            )

    return entities


##############################################################################
# STEP 3 - PARSE COMPONENTS
##############################################################################

def parse_components(vhdl_files):

    result = defaultdict(set)

    for file in vhdl_files:

        try:

            text = file.read_text(
                encoding="utf-8",
                errors="ignore"
            )

            text = strip_comments(text)

            for match in COMPONENT_RE.finditer(text):

                component_name = match.group(1).lower()

                result[file].add(component_name)

        except Exception:
            pass

    return result


##############################################################################
# STEP 4 - PARSE INSTANTIATIONS
##############################################################################

def parse_instantiations(file_contents, entities):

    seen_instances = set()
    usages = defaultdict(list)

    hierarchy = defaultdict(set)

    entity_names = set(entities.keys())

    for file, text in file_contents.items():

        parent_entities = []

        for em in ENTITY_RE.finditer(text):

            parent_entities.append(
                em.group(1).lower()
            )

        current_parent = (
            parent_entities[0]
            if parent_entities
            else file.stem.lower()
        )

        # direct entity instantiation

        for match in DIRECT_ENTITY_RE.finditer(text):

            instance_name = match.group(1)
            entity_name = match.group(2).lower()

            if entity_name not in entity_names:
                continue

            if file == entities[entity_name].file:
                continue

            line = find_line_number(
                text,
                match.start()
            )

            inst = InstanceInfo(
                entity_name,
                instance_name,
                file,
                line
            )

            key = (
                str(file),
                line,
                entity_name
            )

            if key in seen_instances:
                continue

            seen_instances.add(key)

            usages[entity_name].append(inst)

            hierarchy[current_parent].add(
                entity_name
            )

        # component instantiations

        for match in COMPONENT_INSTANCE_RE.finditer(text):

            instance_name = match.group(1)
            target = match.group(2).lower()

            if target not in entity_names:
                continue

            if file == entities[target].file:
                continue

            line = find_line_number(
                text,
                match.start()
            )

            inst = InstanceInfo(
                target,
                instance_name,
                file,
                line
            )

            key = (
                str(file),
                line,
                target
            )

            if key in seen_instances:
                continue

            seen_instances.add(key)

            usages[target].append(inst)

            hierarchy[current_parent].add(
                target
            )

    return usages, hierarchy


##############################################################################
# REPORTING
##############################################################################

def print_report(entities,
                 usages):

    print()
    print("=" * 80)
    print("ENTITY USAGE REPORT")
    print("=" * 80)

    for entity_name in sorted(entities):

        e = entities[entity_name]

        print()
        print(f"Entity : {entity_name}")
        print(
            f"Defined: {e.file}:{e.line}"
        )

        users = usages.get(
            entity_name,
            []
        )

        if not users:

            print("Used   : UNUSED")
            continue

        print(
            f"Used in {len(users)} instance(s)"
        )

        for inst in users:

            print(
                f"  {inst.file}:{inst.line}"
                f" ({inst.instance_name})"
            )


##############################################################################
# UNUSED
##############################################################################

def print_unused(
        entities,
        usages):

    print()
    print("=" * 80)
    print("UNUSED ENTITIES")
    print("=" * 80)

    unused = 0

    for entity_name in sorted(entities):

        if entity_name not in usages:

            unused += 1
            print(entity_name)

    print()
    print(f"Total unused: {unused}")


##############################################################################
# CSV
##############################################################################

def export_csv(
        filename,
        entities,
        usages):

    with open(
        filename,
        "w",
        newline="",
        encoding="utf-8"
    ) as f:

        writer = csv.writer(f)

        writer.writerow([
            "Entity",
            "DefinitionFile",
            "DefinitionLine",
            "Users",
            "UserFiles"
        ])

        for entity_name in sorted(entities):

            entity = entities[entity_name]

            user_files = sorted(
                {
                    str(u.file)
                    for u in usages.get(
                        entity_name,
                        []
                    )
                }
            )

            writer.writerow([
                entity_name,
                entity.file,
                entity.line,
                len(user_files),
                ";".join(user_files)
            ])

    print(
        f"CSV exported: {filename}"
    )


##############################################################################
# HIERARCHY
##############################################################################

def print_hierarchy(hierarchy):

    print()
    print("=" * 80)
    print("ENTITY HIERARCHY")
    print("=" * 80)

    for parent in sorted(hierarchy):

        print(parent)

        for child in sorted(
                hierarchy[parent]):

            print(
                f"   └── {child}"
            )


##############################################################################
# DOT EXPORT
##############################################################################

def export_dot(filename, hierarchy):

    with open(
            filename,
            "w",
            encoding="utf-8") as f:

        f.write("digraph FPGA {\n")

        for parent in hierarchy:

            for child in hierarchy[parent]:

                f.write(
                    f'    "{parent}" -> "{child}";\n'
                )

        f.write("}\n")

    print(
        f"DOT exported: {filename}"
    )

def save_report(filename,
                entities,
                usages):

    with open(filename, "w", encoding="utf-8") as f:

        f.write("=" * 80 + "\n")
        f.write("ENTITY USAGE REPORT\n")
        f.write("=" * 80 + "\n")

        for entity_name in sorted(entities):

            e = entities[entity_name]

            f.write("\n")
            f.write(f"Entity : {entity_name}\n")
            f.write(f"Defined: {e.file}:{e.line}\n")

            users = usages.get(
                entity_name,
                []
            )

            if not users:
                f.write("Used   : UNUSED\n")
                continue

            f.write(
                f"Used in {len(users)} instance(s)\n"
            )

            for inst in users:

                f.write(
                    f"  {inst.file}:{inst.line}"
                    f" ({inst.instance_name})\n"
                )

    print(
        f"Report saved to {filename}"
    )

def save_unused(filename,
                entities,
                usages):

    unused_count = 0

    with open(filename, "w", encoding="utf-8") as f:

        f.write("UNUSED ENTITIES\n")
        f.write("=" * 80 + "\n")

        for entity_name in sorted(entities):

            if entity_name not in usages:

                unused_count += 1
                f.write(f"{entity_name}\n")

        f.write("\n")
        f.write(
            f"Total unused: {unused_count}\n"
        )

    print(
        f"Unused entity list saved to {filename}"
    )


##############################################################################
# MAIN
##############################################################################

def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--csv",
        action="store_true"
    )

    SEARCH_DIRS = [
        r"H:\ddm\hecb_odf\hdl"
    ]

    parser.add_argument(
        "--dot",
        action="store_true"
    )

    parser.add_argument(
        "--hierarchy",
        action="store_true"
    )

    parser.add_argument(
        "--unused",
        action="store_true"
    )

    args = parser.parse_args()

    vhdl_files = find_vhdl_files(
        SEARCH_DIRS
    )

    print(
        f"Found "
        f"{len(vhdl_files)} VHDL files"
    )

    file_contents = load_vhdl_files(
        vhdl_files
    )

    entities = parse_entities(
        file_contents
    )

    print(
        f"Found "
        f"{len(entities)} entities"
    )

    usages, hierarchy = (
        parse_instantiations(
            file_contents,
            entities
        )
    )

    print_report(
        entities,
        usages
    )

    save_report(
        OUTPUT_DIR / "entity_usage_report.txt",
        entities,
        usages
    )

    save_unused(
        OUTPUT_DIR / "unused_entities.txt",
        entities,
        usages
    )

    if args.unused:
        print_unused(
            entities,
            usages
        )

    if args.hierarchy:
        print_hierarchy(
            hierarchy
        )

    if args.csv:
        export_csv(
            "entity_usage.csv",
            entities,
            usages
        )

    if args.dot:
        export_dot(
            "entity_hierarchy.dot",
            hierarchy
        )


if __name__ == "__main__":
    main()