#!/usr/bin/env python3

# netdiff - KiCad Schematic/Netlist Diff Tool
# Requires KiCad 9 for proper netlist generation from schematics
#
# Derived from CraftyJon's netdiff gist:
# https://gist.github.com/craftyjon/8bcc0d2adf26366beb137dc338b5b43b
# This file preserves the original MIT license and is compatible with
# commercial use and redistribution.
#
# Copyright (c) 2019 Jon Evans <jon@craftyjon.com>

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import argparse
import os
import shutil
import subprocess
import sexpdata
import sys
import tempfile


def save_git_schematics_to_temp(git_root, revision):
    """Save all .kicad_sch and .kicad_pro files from a git revision to a temp directory."""
    temp_dir = tempfile.mkdtemp()
    all_files = []

    for pattern in ('*.kicad_sch', '*.kicad_pro'):
        try:
            result = subprocess.run(
                ['git', 'ls-files', pattern],
                cwd=git_root,
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                all_files.extend(result.stdout.strip().split('\n'))
        except Exception:
            pass

    for file_path in all_files:
        if not file_path.strip():
            continue
        try:
            result = subprocess.run(
                ['git', 'show', f'{revision}:{file_path}'],
                cwd=git_root,
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                temp_path = os.path.join(temp_dir, file_path)
                os.makedirs(os.path.dirname(temp_path), exist_ok=True)
                with open(temp_path, 'w') as f:
                    f.write(result.stdout)
        except Exception:
            pass

    return temp_dir if any(fp.strip() for fp in all_files) else None


def extract_nets(data, filename):
    """Extract connection data from a netlist or schematic."""
    if is_netlist(data):
        nets_data = data[6][1:] if len(data) > 6 else []
        return unpack(nets_data)
    elif is_schematic(data):
        netlist_data = generate_netlist_from_sch(filename)
        if netlist_data:
            nets_data = netlist_data[6][1:] if len(netlist_data) > 6 else []
            return unpack(nets_data)
        return extract_nets_from_sch(data)
    else:
        raise ValueError(f"Unrecognized file format for {filename}")


def is_netlist(data):
    """Return True when the S-expression looks like a KiCad netlist."""
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, sexpdata.Symbol):
            return first.value() in ('export', 'export_netlist')
    return False


def is_schematic(data):
    """Return True when the S-expression looks like a KiCad schematic."""
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, sexpdata.Symbol):
            return first.value() == 'kicad_sch'
    return False


def find_git_root(path):
    """Find the git repository root directory for a given path"""
    try:
        result = subprocess.run(
            ['git', 'rev-parse', '--show-toplevel'],
            cwd=os.path.dirname(os.path.abspath(path)),
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def get_git_file_content(repo_root, filepath, revision='HEAD'):
    """Get file content from git at a specific revision"""
    try:
        # Get relative path from repo root
        abs_path = os.path.abspath(filepath)
        rel_path = os.path.relpath(abs_path, repo_root)
        
        result = subprocess.run(
            ['git', 'show', f'{revision}:{rel_path}'],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode == 0:
            return result.stdout
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
        pass
    
    return None


def find_kicad_project_root(sch_file):
    """Find the KiCad project root by looking for .kicad_pro file"""
    search_dir = os.path.dirname(os.path.abspath(sch_file))
    
    # Search up the directory tree for .kicad_pro
    for _ in range(10):  # Limit search depth
        for file in os.listdir(search_dir):
            if file.endswith('.kicad_pro'):
                return search_dir
        
        parent = os.path.dirname(search_dir)
        if parent == search_dir:  # Reached filesystem root
            break
        search_dir = parent
    
    # Fallback: return directory of the schematic
    return os.path.dirname(os.path.abspath(sch_file))


def find_root_schematic(project_root):
    """Find the main/root schematic file in the project"""
    # Look for a schematic file matching the project directory name
    proj_name = os.path.basename(project_root)
    
    candidates = [
        os.path.join(project_root, f'{proj_name}.kicad_sch'),
        os.path.join(project_root, 'main.kicad_sch'),
    ]
    
    for path in candidates:
        if os.path.exists(path):
            return path
    
    # Fallback: return the first .kicad_sch found
    for file in os.listdir(project_root):
        if file.endswith('.kicad_sch'):
            return os.path.join(project_root, file)
    
    return None


# The netlist comparison algorithm below is adapted from CraftyJon's original
# netdiff.py gist. The main diffing behavior and output formatting follow the
# same MIT-licensed logic as the original source.
def unpack(sexpr):
    """Parse netlist S-expression format"""
    ret = {}
    for net in sexpr:
        code = net[1][1]
        name = net[2][1]
        if isinstance(name, sexpdata.Symbol):
            name = name.value()
        name = str(name)

        members = []
        if len(net) < 4:
            continue

        for node in net[3:]:
            if len(node) < 3:
                continue
            
            ref = node[1][1]
            pin = node[2][1]

            if isinstance(ref, sexpdata.Symbol):
                ref = ref.value()

            if isinstance(pin, sexpdata.Symbol):
                pin = pin.value()

            ref = str(ref)
            pin = str(pin)

            members.append((ref, pin))

        members.sort()
        ret[name] = members

    return ret


def generate_netlist_from_sch(sch_file):
    """Generate a netlist from a KiCad schematic using KiCad's CLI.
    If KiCad 9 is not available, return None and fall back to schematic parsing.
    """
    if not kicad9_available():
        return None

    try:
        project_root = find_kicad_project_root(sch_file)
        root_sch = find_root_schematic(project_root)
        
        if not root_sch or not os.path.exists(root_sch):
            return None
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.net', delete=False) as f:
            netlist_file = f.name
        
        try:
            result = subprocess.run(
                ['kicad-cli', 'sch', 'export', 'netlist', root_sch, '--output', netlist_file],
                cwd=project_root,
                capture_output=True,
                timeout=30
            )
            
            if result.returncode == 0 and os.path.exists(netlist_file) and os.path.getsize(netlist_file) > 0:
                with open(netlist_file, 'r') as f:
                    data = sexpdata.load(f)
                os.unlink(netlist_file)
                return data
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        
        if os.path.exists(netlist_file):
            os.unlink(netlist_file)
    except Exception:
        pass
    
    return None


def extract_nets_from_sch(sch_data):
    """Parse KiCad schematic and build a comparison dict from components"""
    components = {}  # ref -> component info dict
    
    for item in sch_data:
        if not isinstance(item, list) or len(item) == 0:
            continue
        
        item_type = item[0]
        if isinstance(item_type, sexpdata.Symbol):
            item_type = item_type.value()
        
        if item_type == 'symbol':
            ref = None
            value = None
            properties = {}
            
            # Extract reference, value, and other properties from the schematic instance
            for element in item:
                if isinstance(element, list) and len(element) > 0:
                    elem_type = element[0]
                    if isinstance(elem_type, sexpdata.Symbol):
                        elem_type = elem_type.value()
                    
                    if elem_type == 'property' and len(element) > 2:
                        prop_name = element[1]
                        prop_value = element[2]
                        
                        if isinstance(prop_value, sexpdata.Symbol):
                            prop_value = prop_value.value()
                        else:
                            prop_value = str(prop_value)
                        
                        if prop_name == 'Reference':
                            ref = prop_value
                        elif prop_name == 'Value':
                            value = prop_value
                        else:
                            properties[prop_name] = prop_value
            
            if ref:
                # Create pseudo-nets from component data for comparison
                # The "net" is the reference + value + key properties
                components[ref] = (value, frozenset(sorted(properties.items())))
    
    # Build nets dict where each component becomes a pseudo-net
    nets = {}
    for ref in sorted(components.keys()):
        value, props = components[ref]
        net_name = f"{ref}_{value}"
        # Store the component info as a tuple so it can be compared
        nets[net_name] = [(ref, value)]
    
    return nets if nets else {}


def parse_git_spec(spec):
    """Parse git revision syntax and return (revision, path, display_name)"""
    if ':' in spec:
        rev, path = spec.split(':', 1)
        return rev, path, f"{rev[:7]} ({path})"
    return None, spec, spec


def load_file(filename):
    """Load and parse a KiCad file."""
    with open(filename, 'r') as f:
        return sexpdata.load(f)


def kicad9_available():
    """Return True if KiCad 9 is installed and available."""
    try:
        result = subprocess.run(
            ['kicad-cli', '--version'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            version_line = result.stdout.strip().split('\n')[0]
            return '9.' in version_line
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return False


def load_git_revision(git_root, revision, filepath):
    """Load a file from git revision, returning parsed data and temp project dir."""
    git_content = get_git_file_content(git_root, filepath, revision)
    if not git_content:
        return None, None

    parsed = sexpdata.loads(git_content)
    if is_schematic(parsed):
        temp_proj = save_git_schematics_to_temp(git_root, revision)
        if temp_proj:
            temp_path = os.path.join(temp_proj, filepath)
            if os.path.exists(temp_path):
                return load_file(temp_path), temp_proj
    return parsed, None


def load_source(spec, git_root):
    """Load a path or git revision and return parsed data, temp project dir, and path."""
    git_rev, path, display = parse_git_spec(spec)
    if git_rev and git_root:
        data, temp_proj = load_git_revision(git_root, git_rev, path)
        if data is not None:
            return data, temp_proj, path, display
    return load_file(path), None, path, display


def main():
    parser = argparse.ArgumentParser(
        description='Compare KiCad schematics or netlists (git-aware diff tool)',
        epilog='Git integration: Use "commit:path/file.kicad_sch" to compare specific git revisions'
    )
    parser.add_argument('first_file', help='First file (can be commit:path for git revisions)')
    parser.add_argument('second_file', nargs='?', help='Second file (can be commit:path for git revisions)')
    parser.add_argument('--label', nargs=2, default=None, metavar=('A', 'B'),
                        help='Custom labels for the two files')
    parser.add_argument('--textconv', action='store_true',
                        help='Output normalized netlist text for git diff driver (single file only)')

    args = parser.parse_args()

    if args.textconv:
        # Textconv mode: output normalized netlist for a single file
        if not args.first_file or args.second_file:
            parser.error("--textconv requires exactly one file argument")
        
        git_rev, file_spec, _ = parse_git_spec(args.first_file)
        git_root = find_git_root(file_spec) or find_git_root('.')
        
        data, temp_proj, file_path, _ = load_source(args.first_file, git_root)
        nets = extract_nets(data, os.path.join(temp_proj, file_path) if temp_proj else file_path)
        
        # Output normalized netlist text
        for net_name in sorted(nets.keys()):
            print(f"{net_name}: {nets[net_name]}")
        
        if temp_proj and os.path.exists(temp_proj):
            shutil.rmtree(temp_proj)
        return

    # Normal diff mode requires two files
    if not args.second_file:
        parser.error("Two files required for comparison (or use --textconv for single file)")

    fn_a = args.first_file
    fn_b = args.second_file
    label_a = args.label[0] if args.label else None
    label_b = args.label[1] if args.label else None

    git_rev_a, file_a_spec, _ = parse_git_spec(fn_a)
    git_rev_b, file_b_spec, _ = parse_git_spec(fn_b)
    git_root = find_git_root(file_a_spec) or find_git_root(file_b_spec) or find_git_root('.')

    a_data, temp_proj_a, file_a, display_a = load_source(fn_a, git_root)
    b_data, temp_proj_b, file_b, display_b = load_source(fn_b, git_root)

    if label_a:
        display_a = label_a
    if label_b:
        display_b = label_b

    nets_a = extract_nets(a_data, os.path.join(temp_proj_a, file_a) if temp_proj_a else file_a)
    nets_b = extract_nets(b_data, os.path.join(temp_proj_b, file_b) if temp_proj_b else file_b)

    sa = set(nets_a.keys())
    sb = set(nets_b.keys())

    only_a = sa - sb
    only_b = sb - sa
    both = sa & sb

    if len(only_a) == len(only_b) == 0:
        print(f"{display_a} and {display_b} are identical")
        sys.exit(0)

    print(f"A: {display_a}\nB: {display_b}")

    changed_header = False
    for net_name in sorted(both):
        if nets_a[net_name] != nets_b[net_name]:
            if not changed_header:
                print("\nChanged nets:\n")
                changed_header = True
            print(f"{net_name}: {nets_a[net_name]} => {nets_b[net_name]}")

    discards_a = set()
    discards_b = set()
    renamed_header = False
    for net_name in sorted(only_a):
        for candidate in only_b:
            if nets_a[net_name] == nets_b[candidate]:
                if not renamed_header:
                    print("\nRenamed nets (no connection changes):\n")
                    renamed_header = True
                print(f"{net_name} => {candidate}")
                discards_a.add(net_name)
                discards_b.add(candidate)

    only_a.difference_update(discards_a)
    only_b.difference_update(discards_b)

    if only_a:
        print(f"\nOnly in {display_a}:\n")
        for el in sorted(only_a):
            print(f"{el}: {nets_a[el]}")

    if only_b:
        print(f"\nOnly in {display_b}:\n")
        for el in sorted(only_b):
            print(f"{el}: {nets_b[el]}")

    if temp_proj_a and os.path.exists(temp_proj_a):
        shutil.rmtree(temp_proj_a)
    if temp_proj_b and os.path.exists(temp_proj_b):
        shutil.rmtree(temp_proj_b)


if __name__ == '__main__':
    main()
