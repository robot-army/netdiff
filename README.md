# netdiff - KiCad Schematic/Netlist Diff Tool

A command-line tool for comparing KiCad schematics and netlists with git integration.

## Features

- **Netlist Comparison**: Compare exported `.net` files to see electrical changes
- **Schematic Comparison**: Compare `.kicad_sch` files to see component changes
- **Git Integration**: Use git revision syntax to compare any two commits directly
- **Project-Aware**: Automatically locates KiCad projects and uses proper context for netlister
- **Multiple File Formats**: Supports both netlist exports and schematic files

## Installation

1. Clone this repository:
   ```bash
   git clone https://github.com/robot-army/netdiff.git
   cd netdiff
   ```

2. Install dependencies:
   ```bash
   pip install sexpdata
   ```

3. Ensure KiCad 9 is installed and `kicad-cli` is available in your PATH.

## Usage

### Compare Two Files

```bash
netdiff.py file1.kicad_sch file2.kicad_sch
netdiff.py netlist1.net netlist2.net
```

### Compare Git Revisions

Use `commit:path` syntax to compare any two git revisions:

```bash
cd /path/to/kicad/project
netdiff.py '096d248:kicad-layout/fec.kicad_sch' '95538d4:kicad-layout/fec.kicad_sch'
netdiff.py 'HEAD~3:kicad-layout/fec.kicad_sch' 'HEAD:kicad-layout/fec.kicad_sch'
```

### Custom Labels

Add custom labels to the output:

```bash
netdiff.py file1.kicad_sch file2.kicad_sch --label "Old Design" "New Design"
```

### Git Difftool Integration

To use as a git external diff tool for `.kicad_sch` files, add to your `.git/config`:

```ini
[diff "kicad_sch"]
    command = /path/to/netdiff.py "$2" "$5" --label "$3" "$1"
```

Then in `.gitattributes`:

```
*.kicad_sch diff=kicad_sch
```

## Output

The tool outputs three categories of differences:

- **Changed nets**: Nets with modified connections (component/pin changes)
- **Renamed nets**: Nets with same connections but different names
- **Only in A/B**: Components/nets that exist in only one file

### Example Output

```
A: HEAD~1 (kicad-layout/fec_1.kicad_sch)
B: HEAD (kicad-layout/fec_1.kicad_sch)

Only in A:

SJ19_MOMENTARY-SWITCH-SPST-PTH-6.0MM: [('SJ19', 'MOMENTARY-SWITCH-SPST-PTH-6.0MM')]

Only in B:

#SUPPLY20_PWR_FLAG: [('#SUPPLY20', 'PWR_FLAG')]
C117_1u: [('C117', '1u')]
```

## How It Works

### For Netlists (.net files)
- Parses the S-expression netlist format
- Extracts net names and connected components/pins
- Compares net definitions between two files

### For Schematics (.kicad_sch files)
- **Preferred**: Uses KiCad's `kicad-cli` to export full netlists when possible
- **Fallback**: Parses schematic structure directly to extract:
  - Component references (U1, R1, C1, etc.)
  - Component values (10k, 100µF, etc.)
  - Creates pseudo-nets for comparison
- Understands hierarchical schematics and sub-sheets

### Git Integration
- Automatically detects git repositories
- Uses `git show commit:path` to retrieve file contents at specific revisions
- Works from anywhere in the git repository
- Displays commit hashes and file paths in output

## Limitations

- **Complex netlists**: Requires KiCad CLI for accurate cross-sheet net resolution
- **Library issues**: If libraries can't be found, kicad-cli will fail
- **Hierarchical projects**: Component extraction only analyzes individual sheets; full netlist requires proper netlister
- **Layout changes**: Moving components without changing connections won't show as changes (correct behavior for netlist comparison)

## Contributing

Improvements welcome, especially:
- Better integration with kicad-cli for library resolution
- Support for additional KiCad formats
- Performance improvements for large schematics
